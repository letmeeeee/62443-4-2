"""Authenticated, device-bound application-security backups, never arbitrary paths."""
import base64
import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from flask import current_app
from sqlalchemy import MetaData, Table, select
from utils import security_store as store
from utils.security_files import private_directory, private_write

MAX_BACKUP_BYTES = 16 * 1024 * 1024
USER_FIELDS = {'username','password','salt','permission','first_login',
               'password_created_at','password_expire_at','last_notify_at'}


def _engine():
    import config
    return config.engine


def _identity():
    configured = current_app.config.get('SECURITY_DEVICE_ID')
    value = configured or Path('/etc/machine-id').read_text().strip()
    if not value:
        raise ValueError('DEVICE_ID_UNAVAILABLE')
    return hashlib.sha256(value.encode()).hexdigest()


def _key():
    # Dedicated purpose derivation; persistent Flask secret is already device-protected.
    return hashlib.sha256(('lc400-security-backup-v1:' + current_app.secret_key).encode()).digest()


def _ini_path():
    import config
    path = Path(config.INI_PATH)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError('INVALID_CONFIGURATION_PATH')
    return path


def _users(conn):
    import config
    table = Table(config.PERM_TABLE, MetaData(), autoload_with=conn)
    return table


def _json(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError('Unsupported backup value')


def _path(identifier):
    if not isinstance(identifier, str) or not re.fullmatch(r'[0-9a-f]{32}', identifier):
        raise ValueError('INVALID_BACKUP_ID')
    return private_directory('backups') / (identifier + '.lcb')


def create_backup():
    from routes.route_security import certificate_inventory
    directory = private_directory('backups')
    files = list(directory.glob('*.lcb'))
    if len(files) >= 20 or sum(f.stat().st_size for f in files) >= 128*1024*1024:
        raise ValueError('BACKUP_QUOTA_REACHED')
    ini = _ini_path().read_bytes()
    if len(ini) > 1024*1024:
        raise ValueError('CONFIGURATION_TOO_LARGE')
    with _engine().begin() as conn:
        store.lock_security(conn)
        users = [dict(row) for row in conn.execute(select(_users(conn))).mappings()]
        for user in users:
            store.account_state(conn, user['username'])
        accounts = [dict(row) for row in conn.execute(select(store.ACCOUNT_STATE)).mappings()]
        settings = [dict(row) for row in conn.execute(select(store.SETTINGS)).mappings() if row['name'] != 'maintenance']
    payload = dict(schemaVersion=1, product='LC400', device=_identity(),
        createdAt=datetime.now(timezone.utc).isoformat(),
        scope=['application-accounts','security-settings','device-ini','certificate-references'],
        users=users, accounts=accounts, settings=settings, ini=base64.b64encode(ini).decode(),
        certificateIds=sorted(item['sha256'] for item in certificate_inventory() if 'sha256' in item))
    plaintext = json.dumps(payload, default=_json, ensure_ascii=False).encode()
    if len(plaintext) > MAX_BACKUP_BYTES:
        raise ValueError('BACKUP_TOO_LARGE')
    nonce = os.urandom(12)
    blob = b'LCB1'+nonce+AESGCM(_key()).encrypt(nonce, plaintext, b'LC400/application-security/v1')
    identifier = secrets.token_hex(16)
    private_write(_path(identifier), blob)
    return dict(id=identifier, sha256=hashlib.sha256(blob).hexdigest(), bytes=len(blob),
                createdAt=payload['createdAt'], scope=payload['scope'], encrypted=True)


def read_backup(identifier, expected_sha256=None):
    from cryptography.exceptions import InvalidTag
    path = _path(identifier)
    if path.is_symlink() or path.stat().st_size > MAX_BACKUP_BYTES+64:
        raise ValueError('INVALID_BACKUP_FILE')
    blob = path.read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    if expected_sha256 and digest != expected_sha256:
        raise ValueError('BACKUP_DIGEST_MISMATCH')
    if not blob.startswith(b'LCB1'):
        raise ValueError('BACKUP_FORMAT_INVALID')
    try:
        payload = json.loads(AESGCM(_key()).decrypt(blob[4:16], blob[16:], b'LC400/application-security/v1'))
    except (InvalidTag, ValueError):
        raise ValueError('BACKUP_AUTHENTICATION_FAILED') from None
    if payload.get('schemaVersion') != 1 or payload.get('product') != 'LC400' or payload.get('device') != _identity():
        raise ValueError('BACKUP_INCOMPATIBLE')
    from routes.route_security import certificate_inventory
    current = sorted(item['sha256'] for item in certificate_inventory() if 'sha256' in item)
    if current != payload['certificateIds']:
        raise ValueError('CERTIFICATE_REFERENCES_CHANGED')
    if any(set(user) != USER_FIELDS for user in payload['users']):
        raise ValueError('ACCOUNT_SCHEMA_INCOMPATIBLE')
    from utils.auth import is_developer_account_disabled
    active = {row['username'] for row in payload['accounts'] if row['enabled']}
    if not any(row['permission']==4 and row['username'] in active and
               not is_developer_account_disabled(row['username']) for row in payload['users']):
        raise ValueError('BACKUP_HAS_NO_ACTIVE_ADMIN')
    ini = base64.b64decode(payload['ini'], validate=True)
    if len(ini) > 1024*1024:
        raise ValueError('INVALID_CONFIGURATION')
    import configparser
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(ini.decode('utf-8'))
    with _engine().connect() as conn:
        if set(_users(conn).c.keys()) != USER_FIELDS:
            raise ValueError('ACCOUNT_SCHEMA_INCOMPATIBLE')
    return payload, dict(id=identifier, ok=True, sha256=digest, compatible=True,
                         scope=payload['scope'], createdAt=payload['createdAt'])


def restore_backup(identifier, digest, force_password_change=False):
    """Explicitly enabled maintenance operation. Crash marker requires local recovery."""
    from utils.auth import LOGIN_SESSIONS, disconnect_revoked
    payload, result = read_backup(identifier, digest)
    ini_path = _ini_path()
    original = ini_path.read_bytes()
    marker = private_directory('recovery') / 'pending.json'
    if marker.exists():
        raise ValueError('LOCAL_RECOVERY_REQUIRED')
    # Preserve recovery material before changing either resource; startup will fail closed
    # if the process loses power between filesystem replacement and SQL commit.
    checkpoint = create_backup()
    private_write(marker, json.dumps(dict(checkpoint=checkpoint['id'], restore=identifier)).encode())
    staged = ini_path.with_name(ini_path.name+'.restore-'+secrets.token_hex(8))
    changed = False
    committed = False
    try:
        private_write(staged, base64.b64decode(payload['ini'], validate=True))
        with _engine().begin() as conn:
            store.lock_security(conn)
            users = _users(conn)
            ids = conn.execute(select(LOGIN_SESSIONS.c.sid)).scalars().all()
            conn.execute(LOGIN_SESSIONS.delete())
            conn.execute(store.SESSION_STATE.delete())
            conn.execute(store.SESSION_LOCKS.delete())
            for table, records in ((users,payload['users']), (store.ACCOUNT_STATE,payload['accounts']),
                                    (store.SETTINGS,payload['settings'])):
                conn.execute(table.delete())
                for row in records:
                    row = dict(row)
                    if table is users:
                        if force_password_change:
                            row['first_login'] = 1
                        for name in ('password_created_at','password_expire_at','last_notify_at'):
                            if row[name]:
                                row[name] = datetime.fromisoformat(row[name])
                    conn.execute(table.insert().values(**row))
            os.replace(staged, ini_path)
            changed = True
        committed = True
        marker.unlink()
        disconnect_revoked(ids)
        return dict(ok=True, checkpoint=checkpoint['id'], restart_required=True,
                    sessions_revoked=len(ids), healthCheck='requires-restart-and-device-check')
    except Exception:
        if changed and not committed:
            private_write(staged, original)
            os.replace(staged, ini_path)
        if not committed:
            marker.unlink(missing_ok=True)
        raise
    finally:
        staged.unlink(missing_ok=True)


def list_backups():
    return [dict(id=path.stem, bytes=path.stat().st_size,
                 createdAt=datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat())
            for path in sorted(private_directory('backups').glob('*.lcb')) if not path.is_symlink()]
