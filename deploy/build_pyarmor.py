#!/usr/bin/env python3
"""Obfuscate device Python using PyArmor 9; keep Shell readable and Python-based.

Only a private staging copy is adapted. No service, database or device operation
is performed. The existing Nuitka builder is a separate, unchanged alternative.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile

from build_protected import APP, ROOT, log, point_definitions, replace_once, sources


def adapt_upgrade(text):
    """Keep the old DB helper and its matching runtime across app replacement."""
    start = text.index('PACKAGE_DB_TOOL=""')
    end = text.index('\nUPGRADE_STATUS_DIR=', start)
    text = text[:start] + '''# PyArmor build: preserve the helper FILE and matching runtime before replacing app.
PACKAGE_DB_TOOL=""
PACKAGE_DB_SNAPSHOT=""
if [ -f "$BASE_DIR/app/script/manage_upgrade_db.py" ]; then
  if ! PACKAGE_DB_SNAPSHOT=$(mktemp -d /tmp/ems-pyarmor-db.XXXXXX); then
    echo '[pyarmor] Cannot create database snapshot; aborting upgrade' >&2
    exit 1
  fi
  if ! cp -p -- "$BASE_DIR/app/script/manage_upgrade_db.py" "$PACKAGE_DB_SNAPSHOT/manage_upgrade_db.py"; then
    rm -rf -- "$PACKAGE_DB_SNAPSHOT"
    exit 1
  fi
  PACKAGE_DB_RUNTIME_FOUND=0
  for runtime in "$BASE_DIR/app"/pyarmor_runtime_*; do
    [ -d "$runtime" ] || continue
    if ! cp -a -- "$runtime" "$PACKAGE_DB_SNAPSHOT/"; then
      rm -rf -- "$PACKAGE_DB_SNAPSHOT"
      exit 1
    fi
    PACKAGE_DB_RUNTIME_FOUND=1
  done
  if [ "$PACKAGE_DB_RUNTIME_FOUND" -ne 1 ]; then
    echo '[pyarmor] Missing database runtime; aborting upgrade' >&2
    rm -rf -- "$PACKAGE_DB_SNAPSHOT"
    exit 1
  fi
  PACKAGE_DB_TOOL="$PACKAGE_DB_SNAPSHOT/manage_upgrade_db.py"
  echo '[pyarmor] Upgrade database helper and runtime preserved' >&2
fi
''' + text[end:]
    text = text.replace('python3 -c "$PACKAGE_DB_TOOL"', 'python3 "$PACKAGE_DB_TOOL"')
    return replace_once(text, 'cleanup_prepared() {', '''cleanup_prepared() {
  # Only remove the private snapshot belonging to this upgrade process.
  if [ -n "$PACKAGE_DB_SNAPSHOT" ]; then
    "$RM" -rf -- "$PACKAGE_DB_SNAPSHOT"
  fi''')


def stage(source_app, work, inventory):
    app = work / 'source/app'
    app.mkdir(parents=True)
    frozen = point_definitions(source_app)
    for relative in inventory:
        original = source_app / relative
        target = app / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        text = original.read_text(encoding='utf-8-sig')
        if relative == 'script/upgrade.sh':
            text = adapt_upgrade(text)
        elif relative == 'script/enable_https.sh':
            # Existing script files are still normal Python. Their independent
            # installation must now include the native PyArmor runtime too.
            old = '        install -m 644 "$SCRIPT_DIR/crl_store.py" /usr/local/lib/g3-https/crl_store.py'
            text = replace_once(text, old, old + '''
        # PyArmor build: boot/renewal tools need their matching runtime package.
        for runtime in "$SCRIPT_DIR"/pyarmor_runtime_*; do
            [ ! -d "$runtime" ] || cp -a -- "$runtime" /usr/local/lib/g3-https/
        done
        echo '[pyarmor] Independent HTTPS tools and runtime installed' >&2''')
        elif relative == 'script/generate_point_labels.py':
            # Parsing the obfuscated bootstrap cannot recover point definitions.
            # Freeze only its extracted public definitions, never plaintext code.
            text = replace_once(text, 'def extract_definitions(root):',
                                'def extract_definitions(root):\n'
                                '    # Build snapshot: source AST is unavailable after obfuscation.\n'
                                '    return ' + repr(frozen) + '\n')
        if relative.endswith('.py'):
            ast.parse(text, filename=relative)
            target.write_text(text, encoding='utf-8')
        elif relative in {'script/upgrade.sh', 'script/enable_https.sh'}:
            target.write_text(text, encoding='utf-8')
        else:
            # Shell, including inline Python, is outside the protection scope.
            shutil.copyfile(original, target)
    return app


def distribute_runtime(generated, payload, inventory):
    """Each directly executable script must find runtime BEFORE its first import.

    upgrade.py inserts the app path inside its original body, which is too late
    for PyArmor's bootstrap. Copies avoid PYTHONPATH/systemd changes and also
    support direct execution of helper scripts from arbitrary working directories.
    """
    runtimes = list(generated.glob('pyarmor_runtime_*'))
    if len(runtimes) != 1 or not runtimes[0].is_dir():
        raise ValueError('Expected one PyArmor runtime from this single build')
    runtime = runtimes[0]
    for parent in sorted({Path(r).parent for r in inventory if r.endswith('.py')}):
        shutil.copytree(runtime, payload / parent / runtime.name, symlinks=False)
    log('Matching runtime installed beside all Python entry directories')
    return runtime.name


def audit(payload, inventory, runtime_name, target_platform):
    """Check complete coverage; never fall back to shipping unprotected Python."""
    for relative in inventory:
        path = payload / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError('Missing/invalid output: ' + relative)
        if relative.endswith('.py'):
            tree = ast.parse(path.read_text(encoding='utf-8-sig'))
            # Official output imports the runtime and executes an encrypted bytes
            # payload. Reject an ordinary file even if a comment mentions PyArmor.
            imported = any(isinstance(n, ast.ImportFrom) and n.module == runtime_name
                           for n in tree.body)
            encrypted = any(isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                            and isinstance(n.value.func, ast.Name) and n.value.func.id == '__pyarmor__'
                            and any(isinstance(a, ast.Constant) and isinstance(a.value, bytes)
                                    for a in n.value.args) for n in tree.body)
            if not imported or not encrypted:
                raise ValueError('Unprotected Python output: ' + relative)
            if not (path.parent / runtime_name / '__init__.py').is_file():
                raise ValueError('Runtime not reachable from entry: ' + relative)
        else:
            if not path.read_bytes().startswith(b'#!') or not os.access(path, os.X_OK):
                raise ValueError('Shell must remain readable/executable: ' + relative)
    binaries = list(payload.rglob('pyarmor_runtime*.so'))
    if not binaries:
        raise ValueError('Missing native PyArmor runtime')
    expected = {'linux.aarch64': b'\xb7\x00', 'linux.x86_64': b'\x3e\x00'}[target_platform]
    for binary in binaries:
        with binary.open('rb') as stream:
            header = stream.read(20)
        if header[:6] != b'\x7fELF\x02\x01' or header[18:20] != expected:
            raise ValueError('Wrong runtime architecture: ' + str(binary))


def run_obfuscation(command, work, output):
    """Stream and retain diagnostics; never publish or fall back on failure."""
    logfile = output / 'pyarmor.log'
    license_error = False
    with logfile.open('x', encoding='utf-8') as saved:
        with subprocess.Popen(command, cwd=work, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                              errors='replace') as process:
            for line in process.stdout:
                print(line, end='', flush=True)
                saved.write(line)
                saved.flush()
                license_error |= 'out of license' in line.lower()
            returncode = process.wait()
    if not returncode:
        return
    reason = 'license_limit' if license_error else 'pyarmor_failed'
    (output / 'build-failure.json').write_text(json.dumps(
        dict(status='failed', reason=reason, exit_code=returncode,
             log=str(logfile), publishable=False), indent=2) + '\n')
    log('Build failed; no release bundle generated. Log: ' + str(logfile))
    if license_error:
        log('PyArmor reported out of license: check the license in this exact '
            'container/user environment. Trial big-script limits are a possible cause.')
        log('Use a license covering the required feature; files will not be skipped '
            'or published as plaintext. After registration retry with a new output directory.')
    raise SystemExit(returncode if returncode > 0 else 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'deploy/build-output/pyarmor-v001')
    parser.add_argument('--platform', choices=('linux.aarch64', 'linux.x86_64'), default='linux.aarch64')
    parser.add_argument('--plan', action='store_true', help='Prepare private source copy and commands only')
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error('Choose a new output directory; refusing to reuse: ' + str(output))
    executable = shutil.which('pyarmor')
    if not args.plan and not executable:
        parser.error('Install PyArmor 9 in the active target-version Python environment')
    inventory = sources(APP)
    output.mkdir(parents=True, mode=0o700)
    work = output / 'work'
    source = stage(APP, work, inventory)
    generated = work / 'generated'
    # Basic mode: no BCC/C compiler, private/restrict flags, renaming, bindings,
    # expiry, or executable packaging. Preserve Flask and plain Shell imports.
    command = [executable or 'pyarmor', '--home', ',config-global,config-local,',
               'gen', '-r', '--platform', args.platform,
               '-O', str(generated), str(source)]
    plan = dict(mode='pyarmor-basic', python=sys.version, platform=args.platform,
                command=command, sources=inventory,
                source_sha256={r: hashlib.sha256((APP / r).read_bytes()).hexdigest() for r in inventory})
    (output / 'build-plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n')
    log(f'PyArmor plan: {sum(r.endswith(".py") for r in inventory)} Python files; '
        'Shell remains readable; no C compilation')
    log('Command: ' + subprocess.list2cmdline(command))
    if args.plan:
        log('Plan ready: ' + str(output) + '; no obfuscation or deployment performed')
        return
    # Isolate local settings, preserve the user's global license without copying
    # it into the build tree. Do not register or purchase licenses automatically.
    run_obfuscation(command, work, output)
    payload = output / 'release/app'
    payload.mkdir(parents=True)
    for relative in inventory:
        target = payload / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if relative.endswith('.py'):
            # Input app is treated as a package by PyArmor, preserving app/.
            shutil.copyfile(generated / 'app' / relative, target)
        else:
            shutil.copyfile(source / relative, target)
            target.chmod(0o755)
    runtime_name = distribute_runtime(generated, payload, inventory)
    for relative in ('keys/ota_public_key.pem', 'script/upgrade_schema.sql', 'sbom/components.json'):
        original = APP / relative
        if original.is_file() and not original.is_symlink():
            target = payload / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)
    audit(payload, inventory, runtime_name, args.platform)
    # Executing obfuscated code requires the target CPython minor version and
    # architecture; building cross-platform does not prove target compatibility.
    native = {'aarch64': 'linux.aarch64', 'arm64': 'linux.aarch64',
              'x86_64': 'linux.x86_64'}.get(platform.machine())
    if sys.platform == 'linux' and native == args.platform:
        log('Smoke-checking offline status tool; no Flask/DB/device imports')
        subprocess.run([sys.executable, payload / 'script/watch_upgrade_status.py', '--help'],
                       check=True, cwd=work)
    else:
        log('Cross-target runtime: execute offline smoke check on the target before deployment')
    # Keep tool version, not the license/registration details printed by --version.
    version_output = subprocess.check_output([executable, '--version'], text=True)
    version_match = re.search(r'\b\d+\.\d+(?:\.\d+)?\b', version_output)
    manifest = dict(plan, runtime=runtime_name,
                    pyarmor=version_match.group(0) if version_match else 'unknown',
                    artifacts={p.relative_to(payload).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in sorted(payload.rglob('*')) if p.is_file()
                               and '__pycache__' not in p.parts})
    # A smoke test may generate bytecode. Never distribute it or original source.
    for directory in list(payload.rglob('__pycache__')):
        shutil.rmtree(directory)
    (output / 'release/manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    bundle = output / 'ems-pyarmor-app.tar.gz'
    with tarfile.open(bundle, 'w:gz') as archive:
        archive.add(output / 'release', arcname='ems-pyarmor')
    log('PyArmor bundle ready: ' + str(bundle))
    log('Publish release/ only. Keep Python + dependencies on device; do not use the Nuitka install procedure')
    log('Existing deploy/install.py rejects runtime .so files; automatic deployment is not integrated')


if __name__ == '__main__':
    main()
