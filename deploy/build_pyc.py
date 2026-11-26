#!/usr/bin/env python3
"""Build a CPython bytecode-only device app on any compatible CPU architecture.

This is source-free distribution, not encryption or strong obfuscation. Compile
with the target CPython version; native third-party dependencies remain on device.
Only private staging copies are changed. No backend imports/device operations.
"""
import argparse
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import py_compile
import re
import shutil
import subprocess
import sys
import tarfile

from build_protected import APP, ROOT, point_definitions, replace_once, sources
from verify_pyc import verify_release


def log(message):
    print('[pyc-build] ' + message, flush=True)


def adapt_upgrade(text):
    """A .pyc is binary; preserve a file, never cat it into python -c."""
    start = text.index('PACKAGE_DB_TOOL=""')
    end = text.index('\nUPGRADE_STATUS_DIR=', start)
    text = text[:start] + '''# Bytecode build: snapshot the old helper before app replacement/rollback.
PACKAGE_DB_TOOL=""
PACKAGE_DB_SNAPSHOT=""
if [ -f "$BASE_DIR/app/script/manage_upgrade_db.pyc" ]; then
  if ! PACKAGE_DB_SNAPSHOT=$(mktemp -d /tmp/ems-pyc-db.XXXXXX); then
    echo '[pyc] Cannot create database helper snapshot; aborting upgrade' >&2
    exit 1
  fi
  if ! cp -p -- "$BASE_DIR/app/script/manage_upgrade_db.pyc" "$PACKAGE_DB_SNAPSHOT/manage_upgrade_db.pyc"; then
    echo '[pyc] Cannot preserve database helper; aborting upgrade' >&2
    rm -rf -- "$PACKAGE_DB_SNAPSHOT"
    exit 1
  fi
  PACKAGE_DB_TOOL="$PACKAGE_DB_SNAPSHOT/manage_upgrade_db.pyc"
  echo '[pyc] Upgrade database helper preserved' >&2
fi
''' + text[end:]
    text = text.replace('python3 -c "$PACKAGE_DB_TOOL"', 'python3 "$PACKAGE_DB_TOOL"')
    return replace_once(text, 'cleanup_prepared() {', '''cleanup_prepared() {
  # Only remove this process's private helper snapshot.
  if [ -n "$PACKAGE_DB_SNAPSHOT" ]; then
    "$RM" -rf -- "$PACKAGE_DB_SNAPSHOT"
  fi''')


def adapt_python(text, relative, frozen):
    """Change known subprocess paths only; module imports remain unmodified."""
    if relative == 'routes/route_cert.py':
        text = replace_once(text, "Path('/home/zlg/app/script/modbus_certs.py')",
                            "Path('/home/zlg/app/script/modbus_certs.pyc')")
        text = replace_once(text, "folder / 'https_certificates.py'",
                            "folder / 'https_certificates.pyc'")
        text = '# Bytecode build: certificate subprocesses execute .pyc files.\n' + text
    elif relative == 'script/generate_point_labels.py':
        text = replace_once(text, 'def extract_definitions(root):',
                            'def extract_definitions(root):\n'
                            '    # Build-time point definitions: published bytecode has no source AST.\n'
                            '    return ' + repr(frozen) + '\n')
    elif relative == 'script/custom_pki.py':
        # Recovery diagnostics should point at the actual installed CLI filename.
        text = text.replace('run custom_pki.py recover', 'run custom_pki.pyc recover')
    ast.parse(text, filename=relative)
    return text


def stage(source_app, work, inventory):
    app = work / 'source/app'
    app.mkdir(parents=True)
    frozen = point_definitions(source_app)
    for relative in inventory:
        original = source_app / relative
        target = app / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        text = original.read_text(encoding='utf-8-sig')
        if relative.endswith('.py'):
            text = adapt_python(text, relative, frozen)
        elif relative == 'script/upgrade.sh':
            text = adapt_upgrade(text)
        elif relative == 'script/enable_https.sh':
            # All existing explicit Python filenames in this script are paths.
            # Covers launch, installed copies and main-file existence checks.
            text = re.sub(r'\.py\b', '.pyc', text)
            text = replace_once(text, 'set -Eeuo pipefail',
                                '# Bytecode build: Python tool paths use .pyc; Shell stays readable.\n'
                                'set -Eeuo pipefail')
        else:
            # Untouched Shell, including its inline Python, remains byte-for-byte.
            shutil.copyfile(original, target)
            continue
        target.write_text(text, encoding='utf-8')
    return app


def compile_app(staged, payload, inventory):
    """Emit legacy module.pyc beside packages; __pycache__ alone is insufficient.

    optimize=0 preserves assertions/docstrings even if the builder is started
    with -O. Explicit output filenames avoid deleting or copying original .py.
    """
    for relative in inventory:
        original = staged / relative
        destination = Path(relative).with_suffix('.pyc') if relative.endswith('.py') else Path(relative)
        target = payload / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        if relative.endswith('.py'):
            py_compile.compile(str(original), cfile=str(target),
                               dfile='/home/zlg/app/' + relative,
                               doraise=True, optimize=0,
                               invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
            target.chmod(0o644)
        else:
            shutil.copyfile(original, target)
            target.chmod(0o755)
    log('Compiled all Python files with optimization level 0; Shell copied as text')


def audit(payload, inventory):
    for relative in inventory:
        destination = Path(relative).with_suffix('.pyc') if relative.endswith('.py') else Path(relative)
        path = payload / destination
        if not path.is_file() or path.is_symlink():
            raise ValueError('Missing/invalid artifact: ' + str(destination))
        if relative.endswith('.py'):
            with path.open('rb') as stream:
                header = stream.read(16)
            if len(header) != 16 or header[:4] != importlib.util.MAGIC_NUMBER:
                raise ValueError('Invalid bytecode header: ' + str(destination))
        elif not path.read_bytes().startswith(b'#!') or not os.access(path, os.X_OK):
            raise ValueError('Shell must remain readable/executable: ' + relative)
    for path in payload.rglob('*'):
        if path.is_symlink() or path.suffix in {'.py', '.pyo', '.c', '.h'} or path.name == '__pycache__':
            raise ValueError('Source/build intermediate in release: ' + str(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'deploy/build-output/pyc-v001')
    parser.add_argument('--target-python', required=True, help='Device CPython major.minor, e.g. 3.13')
    parser.add_argument('--target-magic', help='Device importlib.util.MAGIC_NUMBER.hex(), e.g. f30d0d0a')
    parser.add_argument('--plan', action='store_true', help='Stage adaptations only; no bytecode compilation')
    args = parser.parse_args()
    if not re.fullmatch(r'3\.\d+', args.target_python):
        parser.error('--target-python must be a CPython major.minor version')
    if args.target_magic and not re.fullmatch(r'[0-9a-fA-F]{8}', args.target_magic):
        parser.error('--target-magic must contain exactly 8 hexadecimal characters')
    actual_python = f'{sys.version_info.major}.{sys.version_info.minor}'
    actual_magic = importlib.util.MAGIC_NUMBER.hex()
    if not args.plan:
        if sys.implementation.name != 'cpython' or actual_python != args.target_python:
            parser.error(f'Run this builder with CPython {args.target_python}; current interpreter is '
                         f'{sys.implementation.name} {actual_python}. CPU architecture may differ.')
        if args.target_magic and actual_magic != args.target_magic.lower():
            parser.error('Target bytecode magic differs from this interpreter; use matching CPython')
    output = args.output.resolve()
    if output.exists():
        parser.error('Use a fresh output directory: ' + str(output))
    inventory = sources(APP)
    output.mkdir(parents=True, mode=0o700)
    staged = stage(APP, output / 'work', inventory)
    plan = dict(mode='cpython-pyc', implementation=sys.implementation.name,
                python_version=platform.python_version(), python_minor=actual_python,
                magic=actual_magic, target_python=args.target_python,
                target_magic=args.target_magic.lower() if args.target_magic else None,
                builder_arch=platform.machine(), optimize=0, sources=inventory,
                source_sha256={r: hashlib.sha256((APP / r).read_bytes()).hexdigest() for r in inventory})
    (output / 'build-plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n')
    log(f'Inventory: {sum(r.endswith(".py") for r in inventory)} Python files, '
        f'{sum(r.endswith(".sh") for r in inventory)} readable Shell scripts')
    if args.plan:
        log('Plan ready: ' + str(output) + '; no compilation or deployment performed')
        return
    if not args.target_magic:
        log('Device magic was not supplied; run verify_pyc.py with the service interpreter before installation')
    release = output / 'release'
    payload = release / 'app'
    compile_app(staged, payload, inventory)
    for relative in ('keys/ota_public_key.pem', 'script/upgrade_schema.sql', 'sbom/components.json'):
        original = APP / relative
        if original.is_file() and not original.is_symlink():
            target = payload / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)
    audit(payload, inventory)
    manifest = dict(plan, artifacts={p.relative_to(payload).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                    for p in sorted(payload.rglob('*')) if p.is_file()})
    (release / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    # This standalone deployment helper has no business code or third-party deps.
    shutil.copyfile(Path(__file__).with_name('verify_pyc.py'), release / 'verify_pyc.py')
    verify_release(release)
    # Offline utilities only; never import/start the service for a build check.
    subprocess.run([sys.executable, payload / 'script/watch_upgrade_status.pyc', '--help'],
                   check=True, cwd=output / 'work', stdout=subprocess.DEVNULL)
    subprocess.run([sys.executable, payload / 'script/manage_upgrade_db.pyc', '--help'],
                   check=True, cwd=output / 'work', stdout=subprocess.DEVNULL)
    bundle = output / 'ems-pyc-app.tar.gz'
    with tarfile.open(bundle, 'w:gz') as archive:
        archive.add(release, arcname='ems-pyc')
    log('Bytecode bundle ready: ' + str(bundle))
    log('Publish release/ only; work/ contains plaintext. Bytecode is NOT strong obfuscation.')
    log('Existing deploy/install.py does not accept .pyc yet; automatic installation is not integrated')


if __name__ == '__main__':
    main()
