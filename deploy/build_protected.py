#!/usr/bin/env python3
"""Compile device Python with Nuitka Standalone; ship readable Shell scripts.

Only a private build copy is adapted. Never import the device application here:
its imports create directories and connect to production resources.
"""
import argparse
import ast
import hashlib
import importlib.util
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'exec/app'
EXCLUDED = {'tests', '__pycache__', 'instance', 'tee', 'bin', 'keys'}
TEMPLATES = Path(__file__).with_name('protected')


def log(message):
    print('[protected-build] ' + message, flush=True)


def run(command, **kwargs):
    # Log commands, never configuration contents, credentials or private keys.
    log(shlex.join(list(map(str, command))))
    subprocess.run(list(map(str, command)), check=True, **kwargs)


def sources(app):
    """Inventory every device Python/Shell source; development tests stay local."""
    result = []
    for path in sorted(app.rglob('*')):
        relative = path.relative_to(app)
        if any(part in EXCLUDED or part.startswith('.') or part.startswith('build')
               for part in relative.parts):
            continue
        if path.suffix in {'.py', '.sh'}:
            if path.is_symlink() or not path.is_file():
                raise ValueError('Not a regular source: ' + str(path))
            result.append(relative.as_posix())
    if 'main.py' not in result or 'upgrade/upgrade.py' not in result:
        raise ValueError('Both service entry points are required')
    return result


def module_name(relative):
    parts = list(Path(relative).with_suffix('').parts)
    if parts[-1] == '__init__':
        parts.pop()
    return '.'.join(parts)


def replace_once(text, old, new):
    """Fail closed when upstream code changes instead of silently missing a fix."""
    if text.count(old) != 1:
        raise ValueError('Build adaptation no longer matches: ' + old[:100])
    return text.replace(old, new, 1)


def is_main_guard(node):
    return (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
            and len(node.test.ops) == 1 and isinstance(node.test.ops[0], ast.Eq)
            and isinstance(node.test.left, ast.Name) and node.test.left.id == '__name__'
            and len(node.test.comparators) == 1
            and isinstance(node.test.comparators[0], ast.Constant)
            and node.test.comparators[0].value == '__main__')


def adapt_python(text, relative, frozen_definitions=None):
    """Retain module-level CLI scope and original code; change bootstrap only.

    runpy/exec(source) cannot run compiled modules safely. A static dispatcher
    imports the selected module, whose original main guard now also accepts the
    selected entry. All other modules retain normal import-only behavior.
    """
    # __file__ is absolute and logical in this build. Do not resolve a version
    # symlink when deriving persistent state (otherwise Session keys move into
    # each immutable release and logins unexpectedly expire after upgrades).
    text = text.replace('Path(__file__).resolve()', 'Path(__file__)')
    tree = ast.parse(text)
    if relative == 'script/generate_point_labels.py':
        # This utility reads Python ASTs. Freeze its build-time extraction rather
        # than shipping source or attempting to parse the published ELF launchers.
        if frozen_definitions is None:
            raise ValueError('Point-definition snapshot is required')
        text = replace_once(text, 'def extract_definitions(root):',
                            'def extract_definitions(root):\n'
                            '    # Protected builds use the definitions of this exact release.\n'
                            '    return ' + repr(frozen_definitions) + '\n')
    # Use offsets so comments, business code and main-guard global scope survive.
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    for node in reversed(tree.body):
        if is_main_guard(node):
            # Current project guards are single-line; reject a changed layout.
            line = lines[node.lineno - 1]
            if not line.rstrip().endswith(':'):
                raise ValueError('Unsupported main guard: ' + relative)
            lines[node.lineno - 1] = (
                f'if __name__ == "__main__" or _ems_runtime.entry == {relative!r}:\n')
    text = ''.join(lines)
    tree = ast.parse(text)
    insert_line = 0
    for index, node in enumerate(tree.body):
        if ((index == 0 and isinstance(node, ast.Expr)
             and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str))
                or (isinstance(node, ast.ImportFrom) and node.module == '__future__')):
            insert_line = node.end_lineno
        else:
            break
    prelude = (
        '\n# Build-only bootstrap: preserve installed resource/config paths.\n'
        'import _ems_runtime\n'
        f'__file__ = str(_ems_runtime.logical_root / {relative!r})\n'
    )
    lines = text.splitlines(keepends=True)
    lines.insert(insert_line, prelude)
    result = ''.join(lines)
    ast.parse(result)
    return result


def point_definitions(app):
    # This specific offline generator is standard-library-only. No backend import.
    spec = importlib.util.spec_from_file_location(
        '_ems_point_snapshot', app / 'script/generate_point_labels.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.extract_definitions(app)


def adapt_shell(text, relative):
    """Keep Shell readable; adapt its calls to compiled Python tools only."""
    if relative == 'script/enable_https.sh':
        # Python tools are ELF launchers; execute them without a Python interpreter.
        for name in ('https_config.py', 'https_certificates.py'):
            text = text.replace(f'python3 "$SCRIPT_DIR/{name}"', f'"$SCRIPT_DIR/{name}"')
        start = text.index('    if [ "$SCRIPT_DIR" != /usr/local/lib/g3-https ]; then')
        end = text.index('\n    if ! systemctl cat nginx.service', start)
        text = text[:start] + '''    # Preserve an independent complete runtime for boot/renewal services.
    # Never copy just an ELF launcher: it also needs .runtime and its libraries.
    if [ "$SCRIPT_DIR" != /usr/local/lib/g3-https/script ]; then
        echo '[protected] Installing independent HTTPS runtime' >&2
        install -d -m 755 /usr/local/lib/g3-https/script
        cp -a -- "$SCRIPT_DIR/../.runtime" /usr/local/lib/g3-https/
        for helper in enable_https.sh https_config.py https_certificates.py; do
            install -m 755 "$SCRIPT_DIR/$helper" "/usr/local/lib/g3-https/script/$helper"
        done
    fi
''' + text[end:]
        text = text.replace('ExecStart=/usr/local/lib/g3-https/enable_https.sh',
                            'ExecStart=/usr/local/lib/g3-https/script/enable_https.sh')
    if relative == 'script/upgrade.sh':
        start = text.index('PACKAGE_DB_TOOL=""')
        end = text.index('\nUPGRADE_STATUS_DIR=', start)
        text = text[:start] + '''# Protected build: keep an executable and ALL its libraries across app replacement.
PACKAGE_DB_TOOL=""
PACKAGE_DB_SNAPSHOT=""
if [ -x "$BASE_DIR/app/script/manage_upgrade_db.py" ]; then
  if ! PACKAGE_DB_SNAPSHOT=$(mktemp -d /tmp/ems-upgrade-db.XXXXXX); then
    echo '[protected] Cannot create database runtime snapshot; aborting upgrade' >&2
    exit 1
  fi
  if ! { mkdir -p "$PACKAGE_DB_SNAPSHOT/script" &&
         cp -a -- "$BASE_DIR/app/.runtime" "$PACKAGE_DB_SNAPSHOT/" &&
         cp -p -- "$BASE_DIR/app/script/manage_upgrade_db.py" "$PACKAGE_DB_SNAPSHOT/script/"; }; then
    echo '[protected] Cannot preserve database runtime; aborting upgrade' >&2
    rm -rf -- "$PACKAGE_DB_SNAPSHOT"
    exit 1
  fi
  PACKAGE_DB_TOOL="$PACKAGE_DB_SNAPSHOT/script/manage_upgrade_db.py"
  echo '[protected] Upgrade database runtime preserved' >&2
fi
''' + text[end:]
        text = text.replace('python3 -c "$PACKAGE_DB_TOOL"', '"$PACKAGE_DB_TOOL"')
        text = replace_once(text, 'cleanup_prepared() {', '''cleanup_prepared() {
  # Remove only the private snapshot created by this upgrade process.
  if [ -n "$PACKAGE_DB_SNAPSHOT" ]; then
    "$RM" -rf -- "$PACKAGE_DB_SNAPSHOT"
  fi''')
    if relative == 'script/rotate_identity_key.sh':
        # Inline Python imports local PKI modules, so external Python is unsuitable.
        # The same body is compiled as a module and the shell keeps its CLI name.
        text = '''#!/bin/sh
# Build-only wrapper: original identity-rotation Python is compiled by Nuitka.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$SCRIPT_DIR/_rotate_identity_key.py" "$SCRIPT_DIR" "$@"
'''
    return text


def make_dispatcher(entries):
    lines = [TEMPLATES.joinpath('dispatcher.py.in').read_text()]
    # Static imports are visible to Nuitka. Selecting a tool never imports Flask
    # unless that tool itself needs the backend; no runpy or source-code exec.
    for index, (relative, module) in enumerate(sorted(entries.items())):
        lines.append(f'{"if" if index == 0 else "elif"} _ems_runtime.entry == {relative!r}:\n'
                     f'    import {module}\n')
    lines.append('else:\n    raise SystemExit("Unknown protected entry")\n')
    return ''.join(lines)


def stage(app, work, inventory):
    stage_dir = work / 'source'
    stage_dir.mkdir(parents=True)
    frozen = point_definitions(app)
    entries = {}
    for relative in inventory:
        source = (app / relative).read_text(encoding='utf-8-sig')
        target = stage_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if relative.endswith('.py'):
            target.write_text(adapt_python(source, relative, frozen), encoding='utf-8')
            name = module_name(relative)
            if not name:
                # Root __init__ also gets a compiled target, even if currently empty.
                name = '_ems_app_init'
                stage_dir.joinpath(name + '.py').write_text(target.read_text())
            entries[relative] = name
        else:
            target.write_text(adapt_shell(source, relative), encoding='utf-8')
    # Namespace packages are made explicit only inside the build copy.
    for directory in sorted({p.parent for p in stage_dir.rglob('*.py')}):
        if directory != stage_dir:
            directory.joinpath('__init__.py').touch(exist_ok=True)
    rotation = (app / 'script/rotate_identity_key.sh').read_text()
    marker = '<<\'PY\'\n'
    body = rotation.split(marker, 1)[1].rsplit('\nPY', 1)[0] + '\n'
    relative = 'script/_rotate_identity_key.py'
    stage_dir.joinpath(relative).write_text(adapt_python(body, relative), encoding='utf-8')
    entries[relative] = 'script._rotate_identity_key'
    stage_dir.joinpath('_ems_runtime.py').write_text(TEMPLATES.joinpath('runtime.py.in').read_text())
    stage_dir.joinpath('_ems_dispatch.py').write_text(make_dispatcher(entries))
    return stage_dir, entries


def launcher_source(relative):
    # Keep historical .py filenames as native ELF entries. Shell stays readable.
    return (TEMPLATES.joinpath('launcher.c.in').read_text()
            .replace('@ENTRY@', json.dumps(relative))
            .replace('@DEPTH@', str(len(Path(relative).parts))))


def requirement_names():
    """Read distribution names for inventory, not mandatory Nuitka inclusions."""
    names = set()
    for line in (ROOT / 'requirements.txt').read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        match = re.match(r'([A-Za-z0-9][A-Za-z0-9._-]*)', line.strip())
        if not match:
            raise ValueError('Unsupported requirement for dependency inventory: ' + line)
        names.add(match.group(1))
    return sorted(names)


def collect_distribution_metadata():
    """Read installed versions without importing any application/dependency code."""
    records = []
    for name in requirement_names():
        distribution = importlib.metadata.distribution(name)
        metadata = distribution.read_text('METADATA')
        if not metadata:
            raise ValueError('Missing installed METADATA: ' + name)
        records.append(dict(name=distribution.metadata['Name'], version=distribution.version,
                            metadata=metadata))
    return records


def publish_distribution_metadata(runtime, records):
    """Keep version discovery while avoiding Nuitka's unrelated-package error.

    Nuitka handles metadata required by compiled code itself. For the remaining
    requirements, publish only declarative METADATA after compilation: no extra
    imports, executable entry points or Python source. These records describe
    build dependencies and do not prove that every package is used at runtime.
    """
    normalize = lambda name: re.sub(r'[-_.]+', '-', name).lower()
    existing = {normalize(d.metadata['Name']): d.version
                for d in importlib.metadata.distributions(path=[str(runtime)])}
    for record in records:
        name, version = record['name'], record['version']
        if normalize(name) in existing:
            if existing[normalize(name)] != version:
                raise ValueError('Conflicting runtime distribution version: ' + name)
            continue
        safe_name = re.sub(r'[^A-Za-z0-9._]+', '_', name)
        safe_version = re.sub(r'[^A-Za-z0-9._]+', '_', version)
        directory = runtime / (safe_name + '-' + safe_version + '.dist-info')
        directory.mkdir(parents=True, exist_ok=True)
        directory.joinpath('METADATA').write_text(record['metadata'], encoding='utf-8')
    log(f'Dependency metadata ready: {len(records)} declared distributions; '
        'no blanket Nuitka metadata flags')


def publish_shell(source, target):
    """Publish adapted Shell text with executable mode; no obfuscator is used."""
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    target.chmod(0o755)
    log('Readable Shell script ready: ' + str(target))


def audit(payload, inventory, target_arch=None):
    """Require compiled Python and readable Shell; reject build intermediates."""
    for relative in inventory:
        path = payload / relative
        if not path.is_file():
            raise ValueError('Missing source replacement: ' + relative)
        if relative.endswith('.py') and path.read_bytes()[:4] != b'\x7fELF':
            raise ValueError('Missing/unprotected source replacement: ' + relative)
        if relative.endswith('.sh'):
            if not path.read_bytes().startswith(b'#!') or not os.access(path, os.X_OK):
                raise ValueError('Shell must be a readable executable script: ' + relative)
    for path in payload.rglob('*'):
        if path.is_symlink():
            raise ValueError('Symlinks must be dereferenced in release: ' + str(path))
        if not path.is_file():
            continue
        if path.suffix == '.py' and path.read_bytes()[:4] != b'\x7fELF':
            raise ValueError('Plaintext Python in release: ' + str(path))
        if path.suffix in {'.pyc', '.pyo', '.c', '.h'}:
            raise ValueError('Build intermediate in release: ' + str(path))
        if target_arch:
            with path.open('rb') as stream:
                header = stream.read(20)
            if header[:4] == b'\x7fELF':
                machine = {'aarch64': b'\xb7\x00', 'x86_64': b'\x3e\x00'}[target_arch]
                if header[:6] != b'\x7fELF\x02\x01' or header[18:20] != machine:
                    raise ValueError('Wrong architecture in release: ' + str(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'deploy/build-output/protected')
    parser.add_argument('--plan', action='store_true', help='Stage adaptations and commands; no compiler/device execution')
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--target-arch', choices=('aarch64', 'x86_64'), default='aarch64')
    parser.add_argument('--logical-root', default='/home/zlg/app', help='Stable installed app path used by existing code')
    args = parser.parse_args()
    if args.jobs < 1 or not Path(args.logical_root).is_absolute():
        parser.error('Positive --jobs and absolute --logical-root are required')
    output = args.output.resolve()
    # Do not clean/reuse directories: stale artifacts must never enter a release.
    if output.exists():
        parser.error('Output already exists; choose a fresh --output: ' + str(output))
    if not args.plan:
        machine = {'arm64': 'aarch64', 'AMD64': 'x86_64'}.get(platform.machine(), platform.machine())
        if sys.platform != 'linux' or machine != args.target_arch:
            parser.error('Use native Linux ' + args.target_arch + ' (or a matching VM); no implicit cross compilation')
        for tool in ('cc', 'patchelf', 'bash', 'sh'):
            if not shutil.which(tool):
                parser.error('Missing build dependency: ' + tool)
        if importlib.util.find_spec('nuitka') is None:
            parser.error('Install Nuitka in the selected Python environment')
    inventory = sources(APP)
    log(f'Inventory: {sum(p.endswith(".py") for p in inventory)} Python, '
        f'{sum(p.endswith(".sh") for p in inventory)} readable Shell scripts; '
        'only Python is compiled; tests and device secrets excluded')
    output.mkdir(parents=True, mode=0o700)
    work = output / 'work'
    source, entries = stage(APP, work, inventory)
    payload = output / 'release/app'
    # One standalone contains all modules and static CLI entries. The 8000/9000
    # processes remain separate. Publish immutable version directories so the
    # still-running 9000 never loses its libraries during an application upgrade.
    command = [sys.executable, '-m', 'nuitka', '--mode=standalone',
               '--output-dir=' + str(work / 'nuitka'), '--output-filename=ems-runtime',
               '--jobs=' + str(args.jobs), '--include-module=engineio.async_drivers.threading',
               '--include-module=pymysql', '--include-module=sqlalchemy.dialects.mysql.pymysql',
               '--report=' + str(output / 'nuitka-report.xml')]
    # Never force metadata for every installed requirement. Nuitka 4.3.5 rejects
    # records whose related module is not compiled (e.g. packaging, wheel).
    # Preserve inventory as declarative files after Standalone compilation.
    # All Python files are represented by static dispatcher imports, including
    # modules not reachable from today's two HTTP service entry points.
    command.append(str(source / '_ems_dispatch.py'))
    plan = dict(scope='exec/app device code', sources=inventory, entries=entries,
                command=command, target_arch=args.target_arch, logical_root=args.logical_root,
                source_sha256={r: hashlib.sha256((APP / r).read_bytes()).hexdigest() for r in inventory})
    (output / 'build-plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n')
    if args.plan:
        log('Plan/staged sources ready: ' + str(output))
        log('No compilation, service startup or deployment performed')
        return
    env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(source), str(source / 'script'))))
    dependency_metadata = collect_distribution_metadata()
    log(f'Captured versions of {len(dependency_metadata)} declared build dependencies')
    run(command, cwd=source, env=env)
    distributions = list((work / 'nuitka').glob('*.dist'))
    if len(distributions) != 1:
        raise RuntimeError('Expected exactly one complete Nuitka Standalone directory')
    runtime = payload / '.runtime/ems.dist'
    shutil.copytree(distributions[0], runtime, symlinks=False)
    publish_distribution_metadata(runtime, dependency_metadata)
    # Native Python entry launchers are built outside the release tree.
    launcher_files = sorted(set(r for r in inventory if r.endswith('.py')) | set(entries))
    for index, relative in enumerate(launcher_files):
        target = payload / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        cfile = work / f'launcher-{index}.c'
        cfile.write_text(launcher_source(relative))
        run(['cc', '-O2', '-Wall', '-Wextra', '-Werror', '-s', '-o', target, cfile])
    for relative in (r for r in inventory if r.endswith('.sh')):
        target = payload / relative
        # Keep Shell readable, including compatibility changes for Python tools.
        publish_shell(source / relative, target)
    # Explicit public/static allowlist. Never recursively copy device config/keys.
    for relative in ('keys/ota_public_key.pem', 'script/upgrade_schema.sql', 'sbom/components.json'):
        path = APP / relative
        if path.is_file():
            target = payload / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    runtime.joinpath('logical-root.txt').write_text(args.logical_root + '\n')
    audit(payload, inventory, args.target_arch)
    # Smoke-check bootstrap without importing MySQL/Modbus/Flask or starting ports.
    run([runtime / 'ems-runtime', '--ems-info'])
    metadata = dict(plan, python=sys.version, machine=platform.machine(),
                    build_dependencies={r['name']: r['version'] for r in dependency_metadata},
                    nuitka=subprocess.check_output([sys.executable, '-m', 'nuitka', '--version'], text=True),
                    artifacts={p.relative_to(payload).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in sorted(payload.rglob('*')) if p.is_file()})
    (output / 'release/manifest.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
    bundle = output / 'ems-protected-app.tar.gz'
    with tarfile.open(bundle, 'w:gz') as archive:
        archive.add(output / 'release', arcname='ems-protected')
    log('Compiled Python / readable Shell bundle ready: ' + str(bundle))
    log('work/ contains source and compiler intermediates; NEVER deploy that directory')
    log('Existing deploy/install.py and app.zip upgrade layouts are NOT compatible; see PROTECTED_BUILD.md')


if __name__ == '__main__':
    main()
