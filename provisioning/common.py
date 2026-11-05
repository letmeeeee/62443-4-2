"""Public exchange format shared by the CA workstation and device installer."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

ROLES = ('master', 'slave', 'https')
MAX_FILE = 1024 * 1024


def read_file(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE:
        raise ValueError('文件不存在、过大或为符号链接: ' + str(path))
    return path.read_bytes()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def device_name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,39}', value):
        raise ValueError('设备编号限 1–40 位字母、数字、点、下划线和连字符，以字母/数字开头')
    return value


def atomic_write(path, data, mode=0o600):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('拒绝覆盖符号链接: ' + str(path))
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            if hasattr(os, 'fchmod'):
                os.fchmod(stream.fileno(), mode)
            else:
                os.chmod(temporary, mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name == 'posix':
            directory_fd = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(directory_fd)
            finally: os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def public_package(directory, kind):
    directory = Path(directory)
    manifest = json.loads(read_file(directory / 'manifest.json'))
    if not isinstance(manifest, dict) or manifest.get('version') != 1 or manifest.get('kind') != kind:
        raise ValueError('不支持的交接包格式')
    device_name(manifest.get('device_id', ''))
    expected = {role + ('.csr' if kind == 'lc400-csr' else '-leaf.pem') for role in ROLES}
    if kind == 'lc400-certificates':
        expected.update(('roots.pem', 'intermediates.pem'))
    if not isinstance(manifest.get('files'), dict) or set(manifest['files']) != expected:
        raise ValueError('交接包文件清单不完整或含未知文件')
    for name in expected:
        if digest(read_file(directory / name)) != manifest['files'][name]:
            raise ValueError('文件摘要不匹配: ' + name)
    return manifest
