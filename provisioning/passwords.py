"""CA password generation and a portable, independently encrypted password vault."""
import json
import os
from pathlib import Path
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .common import json_bytes

MAGIC = b'LC4VLT01'
HEADER_SIZE = len(MAGIC) + 16 + 12
MAX_VAULT = 16384


def generate_password():
    """256 random bits; no hardcoded or device-dependent default."""
    return secrets.token_urlsafe(32)


def validate_password(value, label):
    if not isinstance(value, str) or not 12 <= len(value) <= 1024:
        raise ValueError(label + '长度必须为 12–1024 个字符')


def derive_key(protection_password, salt):
    validate_password(protection_password, '保护口令')
    # Fixed parameters: an untrusted file cannot request unlimited KDF resources.
    return Scrypt(salt=salt, length=32, n=2**17, r=8, p=1).derive(protection_password.encode('utf-8'))


def save_password(path, ca_password, protection_password, ca_directory):
    """Create a new encrypted file. Never overwrite an existing file or CA data."""
    validate_password(ca_password, 'CA 口令')
    validate_password(protection_password, '保护口令')
    if secrets.compare_digest(ca_password.encode(), protection_password.encode()):
        raise ValueError('保护口令必须与 CA 口令不同')
    path = Path(path).absolute()
    ca_directory = Path(ca_directory).resolve()
    resolved = path.resolve()
    if resolved == ca_directory or ca_directory in resolved.parents:
        raise ValueError('口令文件须保存在 CA 数据目录之外')
    if path.exists() or path.is_symlink():
        raise ValueError('口令文件已存在，请选择新文件，避免覆盖已有备份')
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    header = MAGIC + salt + nonce
    payload = json_bytes(dict(version=1, ca_directory=str(ca_directory), password=ca_password))
    ciphertext = AESGCM(derive_key(protection_password, salt)).encrypt(nonce, payload, header)
    data = header + ciphertext
    if len(data) > MAX_VAULT:
        raise ValueError('口令文件数据过大')
    # O_EXCL prevents races/accidental clobbering; encrypted data is mode 0600 from creation.
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name == 'posix':
            directory_fd = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(directory_fd)
            finally: os.close(directory_fd)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return dict(saved=True, file=str(path), encrypted=True, format='LC4VLT01')


def load_password(path, protection_password):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('口令文件不存在或为符号链接')
    with path.open('rb') as stream:
        data = stream.read(MAX_VAULT+1)
    if len(data) > MAX_VAULT or len(data) < HEADER_SIZE+16 or not data.startswith(MAGIC):
        raise ValueError('口令文件格式错误或内容不完整')
    header = data[:HEADER_SIZE]
    salt, nonce = header[len(MAGIC):len(MAGIC)+16], header[-12:]
    try:
        plain = AESGCM(derive_key(protection_password, salt)).decrypt(nonce, data[HEADER_SIZE:], header)
    except InvalidTag:
        raise ValueError('保护口令错误或口令文件已损坏') from None
    try:
        payload = json.loads(plain)
        if not isinstance(payload, dict) or payload.get('version') != 1 or not isinstance(payload.get('ca_directory'), str):
            raise ValueError()
        validate_password(payload.get('password'), 'CA 口令')
    except (ValueError, TypeError, UnicodeError):
        raise ValueError('口令文件内容无效') from None
    return payload


def load_for_ca(path, protection_password, ca):
    payload = load_password(path, protection_password)
    if ca.database.is_file():
        # Also permits a verified CA backup moved to a new directory.
        ca.unlock(payload['password'])
    elif Path(payload['ca_directory']).resolve() != ca.directory.resolve():
        raise ValueError('此口令文件属于另一 CA 目录，请选择正确目录')
    return payload['password']
