"""Private application storage. Never accept filesystem paths from API clients."""
import os
import secrets
from pathlib import Path
from flask import current_app


def private_directory(name):
    base = Path(current_app.config.get('SECURITY_STATE_DIR',
        str(Path(__file__).resolve().parents[2] / 'instance' / 'security')))
    if not base.is_absolute() or base.is_symlink():
        raise ValueError('INVALID_SECURITY_DIRECTORY')
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    if any(parent.is_symlink() for parent in [base] + list(base.parents)):
        raise ValueError('SYMLINK_SECURITY_DIRECTORY')
    path = base / name
    path.mkdir(mode=0o700, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise ValueError('INVALID_SECURITY_DIRECTORY')
    for directory in (base, path):
        if directory.stat().st_uid != os.geteuid() or directory.stat().st_mode & 0o077:
            raise ValueError('SECURITY_DIRECTORY_REQUIRES_0700')
    return path


def private_write(path, data):
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def temporary_password():
    return 'Aa9!' + secrets.token_urlsafe(24)
