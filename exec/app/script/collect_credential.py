#!/usr/bin/env python3
"""Retrieve and remove a temporary password through the device-local admin terminal."""
import argparse
import json
import os
import re
import time
from pathlib import Path


def collect(directory, identifier):
    if not re.fullmatch(r'[0-9a-f]{32}', identifier):
        raise ValueError('Invalid delivery ID')
    path = Path(directory) / 'credentials' / (identifier + '.json')
    fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'r', encoding='utf-8') as stream:
        info = os.fstat(stream.fileno())
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError('Credential file must be owned by this user and restricted to mode 0600')
        if info.st_size > 4096:
            raise ValueError('Invalid credential file')
        value = json.load(stream)
    path.unlink()
    if value['expires_at'] <= time.time():
        raise ValueError('Credential delivery expired; request a new reset')
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('delivery_id')
    parser.add_argument('--directory', type=Path,
        default=Path(__file__).resolve().parents[2] / 'instance' / 'security')
    args = parser.parse_args()
    try:
        value = collect(args.directory, args.delivery_id)
        print('Username:', value['username'])
        print('Temporary password:', value['temporary_password'])
        print('Delivery file removed. Change the password on first login.')
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, str(exc)+'\n')
