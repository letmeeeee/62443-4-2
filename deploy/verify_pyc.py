#!/usr/bin/env python3
"""Check a bytecode release with the device SERVICE interpreter before installing.

No application imports, database access or device writes. The manifest verifies
file integrity, not publisher identity: use a trusted distribution channel.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import sys


def verify_release(release):
    release = Path(release)
    manifest = json.loads((release / 'manifest.json').read_text())
    minor = f'{sys.version_info.major}.{sys.version_info.minor}'
    if sys.implementation.name != 'cpython' or manifest['implementation'] != 'cpython':
        raise ValueError('This release requires CPython')
    if manifest['python_minor'] != minor or manifest['magic'] != importlib.util.MAGIC_NUMBER.hex():
        raise ValueError('Incompatible CPython/bytecode format: release requires '
                         + manifest['python_minor'] + ' magic=' + manifest['magic'])
    artifacts = manifest['artifacts']
    if not isinstance(artifacts, dict) or not artifacts:
        raise ValueError('Empty or invalid artifact manifest')
    app = release / 'app'
    actual = set()
    for path in app.rglob('*'):
        if path.is_symlink():
            raise ValueError('Release contains a symlink: ' + str(path))
        if path.is_file():
            actual.add(path.relative_to(app).as_posix())
            if path.suffix == '.py' or '__pycache__' in path.parts:
                raise ValueError('Plaintext Python or cache directory in app: ' + str(path))
    if actual != set(artifacts):
        raise ValueError('Release files do not match manifest')
    for name, digest in artifacts.items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or relative.as_posix() != name:
            raise ValueError('Invalid manifest path: ' + name)
        path = app / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Checksum mismatch: ' + name)
        if path.suffix == '.pyc':
            with path.open('rb') as stream:
                header = stream.read(16)
            if len(header) != 16 or header[:4] != importlib.util.MAGIC_NUMBER:
                raise ValueError('Invalid bytecode: ' + name)
    return len(artifacts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('release', type=Path, help='Extracted release folder containing manifest.json and app/')
    args = parser.parse_args()
    try:
        count = verify_release(args.release)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, '[pyc-verify] FAILED: ' + str(error) + '\n')
    print(f'[pyc-verify] Compatible CPython bytecode and {count} artifact checksums verified; '
          'no service was started.')


if __name__ == '__main__':
    main()
