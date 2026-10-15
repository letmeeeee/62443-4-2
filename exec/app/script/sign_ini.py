"""Explicitly generate a SHA-256 baseline; no keys are required."""
import argparse
import os
from pathlib import Path
import hashlib
import tempfile


def generate_checksum(ini_path, output):
    if Path(ini_path).resolve() == Path(output).resolve():
        raise ValueError('Output must not overwrite the INI file')
    contents = Path(ini_path).read_bytes()
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=str(output.parent), prefix='.ini-sign-', delete=False) as stream:
            temporary = Path(stream.name)
        temporary.write_text(hashlib.sha256(contents).hexdigest() + '\n', encoding='ascii')
        if Path(ini_path).read_bytes() != contents:
            raise RuntimeError('Configuration changed while hashing; baseline not published')
        os.replace(str(temporary), str(output))
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ini', default='/home/zlg/lc_data_set.ini')
    parser.add_argument('--output', default='/home/zlg/signature/lc_data_set.ini.sha256')
    args = parser.parse_args()
    generate_checksum(args.ini, args.output)
    print(f'SHA-256 baseline saved: {args.output}', flush=True)
