"""Shared MySQL security state; SQLite is supported only for isolated tests."""
import hashlib
import hmac
import json
import re
import secrets
import time
import uuid

from sqlalchemy import (Boolean, Column, Float, Integer, MetaData, String, Table,
                        Text, select)

metadata = MetaData()
ACCOUNT_STATE = Table('security_accounts', metadata,
    Column('username', String(64), primary_key=True),
    Column('uid', String(36), nullable=False, unique=True),
    Column('enabled', Boolean, nullable=False),
    Column('last_login', Float(precision=53)),
    Column('history', Text, nullable=False),
    mysql_engine='InnoDB', mysql_charset='utf8mb4')
SESSION_STATE = Table('security_session_activity', metadata,
    Column('sid', String(64), primary_key=True),
    Column('last_activity', Float(precision=53), nullable=False),
    Column('tab_id', String(64), nullable=False),
    mysql_engine='InnoDB', mysql_charset='utf8mb4')
SESSION_LOCKS = Table('security_session_locks', metadata,
    Column('sid', String(64), primary_key=True),
    Column('locked_at', Float(precision=53), nullable=False), mysql_engine='InnoDB')
ATTEMPTS = Table('security_auth_attempts', metadata,
    Column('key', String(64), primary_key=True),
    Column('failures', Integer, nullable=False),
    Column('locked_until', Float(precision=53), nullable=False),
    Column('updated_at', Float(precision=53), nullable=False),
    mysql_engine='InnoDB')
RATE_LIMITS = Table('security_rate_limits', metadata,
    Column('key', String(64), primary_key=True), Column('window', Integer, nullable=False),
    Column('count', Integer, nullable=False), mysql_engine='InnoDB')
SETTINGS = Table('security_settings', metadata,
    Column('name', String(64), primary_key=True),
    Column('value', Text, nullable=False), mysql_engine='InnoDB')

PASSWORD_POLICY = dict(min_length=12, max_length=128, uppercase=True,
    lowercase=True, digit=True, special=True, history_count=5,
    failure_threshold=5, lock_seconds=300, algorithm='PBKDF2-HMAC-SHA256',
    iterations=600000)


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(),
                                 PASSWORD_POLICY['iterations']).hex()
    return 'pbkdf2_sha256${}${}${}'.format(PASSWORD_POLICY['iterations'], salt, digest)


def verify_password(password, encoded, salt=''):
    if not isinstance(password, str) or len(password) > PASSWORD_POLICY['max_length']:
        return False
    if encoded.startswith('pbkdf2_sha256$'):
        try:
            _, rounds, stored_salt, digest = encoded.split('$')
            rounds = int(rounds)
            if not 100000 <= rounds <= 2000000:
                return False
            actual = hashlib.pbkdf2_hmac('sha256', password.encode(), stored_salt.encode(), rounds).hex()
        except (ValueError, TypeError):
            return False
    else:
        # Legacy account migration happens only after verifying its original hash.
        actual = hashlib.md5((password + salt).encode()).hexdigest()
        digest = encoded
    return hmac.compare_digest(actual, digest)


def validate_password(password, username, history=()):
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        raise ValueError('PASSWORD_LENGTH')
    if not all(re.search(pattern, password) for pattern in (r'[A-Z]', r'[a-z]', r'[0-9]', r'[^A-Za-z0-9\s]')):
        raise ValueError('PASSWORD_COMPLEXITY')
    if username.casefold() in password.casefold():
        raise ValueError('PASSWORD_CONTAINS_USERNAME')
    if any(verify_password(password, item['hash'], item.get('salt', '')) for item in history):
        raise ValueError('PASSWORD_REUSED')


def lock_security(connection):
    # Reuse the cross-worker admission lock; callers hold it only for short DB work.
    from utils.auth import LOGIN_CAPACITY_LOCK
    connection.execute(LOGIN_CAPACITY_LOCK.update().where(LOGIN_CAPACITY_LOCK.c.id == 1).values(id=1))


def account_state(connection, username):
    row = connection.execute(select(ACCOUNT_STATE).where(
        ACCOUNT_STATE.c.username == username)).mappings().first()
    if row is None:
        # Caller must hold lock_security when creating state.
        value = dict(username=username, uid=str(uuid.uuid4()), enabled=True,
                     last_login=None, history='[]')
        connection.execute(ACCOUNT_STATE.insert().values(**value))
        return value
    return dict(row)


def read_account_state(connection, username):
    return connection.execute(select(ACCOUNT_STATE).where(
        ACCOUNT_STATE.c.username == username)).mappings().first()


def attempt_keys(username, source_ip):
    # Track source and account separately so changing one cannot bypass the other.
    return [hashlib.sha256(value.encode()).hexdigest() for value in
            ('user:' + username.casefold(), 'ip:' + (source_ip or 'unknown'))]


def source_ip():
    from flask import request, current_app
    import ipaddress
    value = request.remote_addr
    # Nginx overwrites X-Real-IP; trust it only from the configured loopback proxy.
    if current_app.config.get('TRUST_LOOPBACK_PROXY', True) and value in ('127.0.0.1','::1'):
        candidate = request.headers.get('X-Real-IP')
        if candidate:
            try:
                return str(ipaddress.ip_address(candidate))
            except ValueError:
                pass
    return value


def record_attempt(connection, keys, success=False, check_only=False):
    now = time.time()
    rows = [connection.execute(select(ATTEMPTS).where(ATTEMPTS.c.key == key)).mappings().first()
            for key in keys]
    locked = max([row['locked_until'] - now for row in rows if row] + [0])
    if locked > 0:
        return max(1, int(locked + 0.999)), 0
    if success:
        # Clear the account counter only. An attacker with one valid account must
        # not reset the source IP counter for attacks against other users.
        connection.execute(ATTEMPTS.delete().where(ATTEMPTS.c.key == keys[0]))
        return 0, PASSWORD_POLICY['failure_threshold']
    if check_only:
        return 0, PASSWORD_POLICY['failure_threshold']
    remaining = PASSWORD_POLICY['failure_threshold']
    for key, row in zip(keys, rows):
        count = row['failures'] if row and now - row['updated_at'] < 300 and not row['locked_until'] else 0
        count += 1
        until = now + PASSWORD_POLICY['lock_seconds'] if count >= PASSWORD_POLICY['failure_threshold'] else 0
        values = dict(failures=count, locked_until=until, updated_at=now)
        if row:
            connection.execute(ATTEMPTS.update().where(ATTEMPTS.c.key == key).values(**values))
        else:
            connection.execute(ATTEMPTS.insert().values(key=key, **values))
        remaining = min(remaining, max(0, PASSWORD_POLICY['failure_threshold'] - count))
    connection.execute(ATTEMPTS.delete().where(ATTEMPTS.c.updated_at < now - 86400))
    return (PASSWORD_POLICY['lock_seconds'] if remaining == 0 else 0), remaining


def admit_request(connection, source, limit):
    window = int(time.time() // 60)
    key = hashlib.sha256((source or 'unknown').encode()).hexdigest()
    lock_security(connection)
    row = connection.execute(select(RATE_LIMITS).where(RATE_LIMITS.c.key==key)).mappings().first()
    count = row['count'] if row and row['window']==window else 0
    if count >= limit:
        return False
    values = dict(window=window, count=count+1)
    if row:
        connection.execute(RATE_LIMITS.update().where(RATE_LIMITS.c.key==key).values(**values))
    else:
        connection.execute(RATE_LIMITS.insert().values(key=key,**values))
    connection.execute(RATE_LIMITS.delete().where(RATE_LIMITS.c.window < window-1440))
    return True


def get_setting(connection, name, default):
    row = connection.execute(select(SETTINGS.c.value).where(SETTINGS.c.name == name)).first()
    return json.loads(row[0]) if row else default


def set_setting(connection, name, value):
    encoded = json.dumps(value, ensure_ascii=False)
    if connection.execute(select(SETTINGS.c.name).where(SETTINGS.c.name == name)).first():
        connection.execute(SETTINGS.update().where(SETTINGS.c.name == name).values(value=encoded))
    else:
        connection.execute(SETTINGS.insert().values(name=name, value=encoded))


def maintenance_state(connection):
    value = get_setting(connection, 'maintenance', {})
    until = value.get('until', 0)
    return dict(active=until > time.time(), available=True, until=until or None,
                operator=value.get('operator'), source='authenticated-administrator')
