"""Authenticated single-process CA service with encrypted persistent identities."""
from datetime import timedelta
from contextlib import contextmanager
from functools import wraps
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
import uuid
import zipfile

from flask import Flask, jsonify, render_template, request, send_file, session
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from werkzeug.exceptions import HTTPException

from . import pki


SCHEMA = '''
CREATE TABLE IF NOT EXISTS settings(name TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ca(id INTEGER PRIMARY KEY CHECK(id=1), cert BLOB NOT NULL, encrypted_key BLOB NOT NULL,
 algorithm TEXT NOT NULL, rsa_bits INTEGER, crl BLOB NOT NULL, crl_number INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS certificates(id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, request_hash TEXT NOT NULL,
 device_id TEXT NOT NULL, profile TEXT NOT NULL, algorithm TEXT NOT NULL, rsa_bits INTEGER,
 serial TEXT UNIQUE NOT NULL, cn TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
 cert BLOB NOT NULL, csr BLOB NOT NULL, encrypted_key BLOB NOT NULL, revoked_at TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT NOT NULL, action TEXT NOT NULL,
 target TEXT NOT NULL, ip TEXT NOT NULL);
'''
PUBLIC_COLUMNS = 'id,device_id,profile,algorithm,rsa_bits,serial,cn,created_at,expires_at,revoked_at,reason'


def database(directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == 'posix' and (directory.stat().st_uid != os.geteuid() or directory.stat().st_mode & 0o077):
        raise ValueError('CA 数据目录必须归当前用户所有，权限为 0700')
    path = directory / 'ca.sqlite3'
    if path.is_symlink():
        raise ValueError('CA 数据库不能是符号链接')
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o600)
    os.close(fd)
    if os.name == 'posix' and (path.stat().st_uid != os.geteuid() or path.stat().st_mode & 0o077):
        raise ValueError('CA 数据库须归当前用户所有，权限为 0600')
    return path


@contextmanager
def connect(path):
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def check_password(value):
    if not isinstance(value, str) or not 12 <= len(value) <= 1024:
        raise ValueError('口令须为 12–1024 个字符')
    return value


def password_digest(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()


def initialize_admin(directory, password):
    check_password(password)
    path = database(directory)
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute("SELECT 1 FROM settings WHERE name='admin'").fetchone():
            raise ValueError('管理员已初始化，拒绝覆盖')
        salt = secrets.token_hex(16)
        conn.execute('INSERT INTO settings VALUES(?,?)', ('admin', json.dumps(dict(salt=salt, digest=password_digest(password, salt)))))
        conn.execute('INSERT INTO settings VALUES(?,?)', ('session_secret', secrets.token_hex(32)))


def create_app(directory, secure_cookie=False):
    app = Flask(__name__)
    path = database(directory)
    with connect(path) as conn:
        config = dict(conn.execute('SELECT name,value FROM settings').fetchall())
    if 'admin' not in config:
        raise ValueError('请先执行 ca_server.py init 初始化管理员')
    app.config.update(SECRET_KEY=config['session_secret'], MAX_CONTENT_LENGTH=32*1024,
                      SESSION_COOKIE_NAME='lc400_ca_session',
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict', SESSION_COOKIE_SECURE=secure_cookie,
                      PERMANENT_SESSION_LIFETIME=timedelta(minutes=30), SESSION_REFRESH_EACH_REQUEST=False)
    lock = threading.RLock()
    vault = dict(password=None, deadline=0)
    attempts = {}
    sessions = {}
    app.extensions['ca_vault'] = vault

    def audit(conn, action, target=''):
        conn.execute('INSERT INTO events(time,action,target,ip) VALUES(?,?,?,?)',
                     (pki.now().isoformat(), action, target, request.remote_addr or ''))

    def require_unlock():
        if time.monotonic() >= vault['deadline']:
            vault.update(password=None, deadline=0)
        if vault['password'] is None:
            from werkzeug.exceptions import Locked
            raise Locked('CA 未解锁或解锁已超时')
        with connect(path) as conn:
            row = conn.execute('SELECT * FROM ca WHERE id=1').fetchone()
        if row is None:
            raise ValueError('请先初始化 CA')
        cert = x509.load_pem_x509_certificate(row['cert'])
        key = serialization.load_pem_private_key(row['encrypted_key'], vault['password'].encode())
        public = lambda item: item.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        if public(cert) != public(key):
            raise ValueError('存储中的 CA 证书与私钥不匹配')
        cert.verify_directly_issued_by(cert)
        return row, cert, key, vault['password']

    def protected(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            if not authenticated():
                return jsonify(error='UNAUTHENTICATED', message='请先登录'), 401
            return function(*args, **kwargs)
        return wrapped

    def authenticated():
        sid = session.get('sid')
        with lock:
            if sid and sessions.get(sid, 0) > time.monotonic():
                return True
            if sid:
                sessions.pop(sid, None)
        return False

    def payload():
        data = request.get_json()
        if not isinstance(data, dict):
            raise ValueError('请求体须为 JSON 对象')
        return data

    def throttle(operation):
        identity = (operation, request.remote_addr)
        current = time.monotonic()
        recent = [item for item in attempts.get(identity, []) if current-item < 60]
        if len(recent) >= 5:
            from werkzeug.exceptions import TooManyRequests
            raise TooManyRequests('尝试过于频繁，请 60 秒后重试')
        # Bounded per-process cache; passwords themselves are never retained here.
        if len(attempts) > 2048:
            attempts.clear()
        attempts[identity] = recent + [current]

    @app.before_request
    def csrf():
        if request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
            expected = session.get('csrf')
            actual = request.headers.get('X-CSRF-Token', '')
            if not expected or not hmac.compare_digest(expected, actual):
                return jsonify(error='CSRF_FAILED', message='CSRF 校验失败，请刷新页面'), 403

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @app.errorhandler(ValueError)
    def validation(exc):
        return jsonify(error='VALIDATION_FAILED', message=str(exc)), 422

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return jsonify(error=exc.name.upper().replace(' ', '_'), message=exc.description), exc.code

    @app.errorhandler(Exception)
    def internal_error(exc):
        # Do not log request bodies, key objects, passwords or download bytes.
        app.logger.error('CA request failed: %s', type(exc).__name__)
        return jsonify(error='INTERNAL_ERROR', message='服务器操作失败，请检查存储空间和服务状态'), 500

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.get('/api/session')
    def session_status():
        if 'csrf' not in session:
            session['csrf'] = secrets.token_urlsafe(32)
        return jsonify(authenticated=authenticated(), csrf_token=session['csrf'])

    @app.post('/api/login')
    def login():
        data = payload()
        password = data.get('password', '')
        if not isinstance(password, str) or len(password) > 1024:
            raise ValueError('口令格式错误')
        with lock:
            throttle('login')
            admin = json.loads(config['admin'])
            valid = hmac.compare_digest(password_digest(password, admin['salt']), admin['digest'])
            if not valid:
                with connect(path) as conn:
                    audit(conn, 'login-failed')
                return jsonify(error='LOGIN_FAILED', message='管理员口令错误'), 401
            session.clear()
            sid = secrets.token_urlsafe(32)
            # Remove expired sessions and bound active administrator sessions.
            for expired in list(sessions):
                if sessions[expired] <= time.monotonic():
                    sessions.pop(expired)
            if len(sessions) >= 100:
                sessions.pop(next(iter(sessions)))
            sessions[sid] = time.monotonic()+1800
            session.update(sid=sid, csrf=secrets.token_urlsafe(32))
            session.permanent = True
            with connect(path) as conn:
                audit(conn, 'login')
        return jsonify(authenticated=True, csrf_token=session['csrf'])

    @app.post('/api/logout')
    @protected
    def logout():
        with lock:
            vault.update(password=None, deadline=0)
            sessions.pop(session.get('sid'), None)
            session.clear()
        return jsonify(ok=True)

    @app.get('/api/ca')
    @protected
    def ca_status():
        with lock, connect(path) as conn:
            row = conn.execute('SELECT * FROM ca').fetchone()
            if time.monotonic() >= vault['deadline']:
                vault.update(password=None, deadline=0)
            if row is None:
                return jsonify(initialized=False, unlocked=False)
            cert = x509.load_pem_x509_certificate(row['cert'])
            crl = x509.load_pem_x509_crl(row['crl'])
            return jsonify(initialized=True, unlocked=vault['password'] is not None,
                           unlock_seconds_remaining=max(0, int(vault['deadline']-time.monotonic())),
                           subject=cert.subject.rfc4514_string(), algorithm=row['algorithm'], rsa_bits=row['rsa_bits'],
                           fingerprint_sha256=cert.fingerprint(pki.hashes.SHA256()).hex(),
                           expires_at=cert.not_valid_after_utc.isoformat(), crl_number=row['crl_number'],
                           crl_next_update=crl.next_update_utc.isoformat(), crl_expired=crl.next_update_utc <= pki.now())

    @app.post('/api/ca')
    @protected
    def ca_initialize():
        data = payload()
        password = check_password(data.get('password'))
        with lock, connect(path) as conn:
            conn.execute('BEGIN IMMEDIATE')
            if conn.execute('SELECT 1 FROM ca').fetchone():
                return jsonify(error='CA_EXISTS', message='CA 已初始化，不能覆盖'), 409
            cert, key, encrypted, algorithm, bits = pki.create_ca(data, password)
            crl = pki.make_crl(cert, key, 1, [])
            conn.execute('INSERT INTO ca VALUES(1,?,?,?,?,?,?)', (pki.pem(cert), encrypted, algorithm, bits, crl, 1))
            audit(conn, 'initialize-ca', cert.subject.rfc4514_string())
        return jsonify(initialized=True, unlocked=False), 201

    @app.post('/api/ca/unlock')
    @protected
    def unlock_ca():
        password = check_password(payload().get('password'))
        with lock, connect(path) as conn:
            throttle('unlock')
            row = conn.execute('SELECT * FROM ca').fetchone()
            if row is None:
                raise ValueError('请先初始化 CA')
            try:
                serialization.load_pem_private_key(row['encrypted_key'], password.encode())
            except (ValueError, TypeError):
                audit(conn, 'unlock-ca-failed')
                return jsonify(error='UNLOCK_FAILED', message='CA 保护口令错误'), 422
            vault.update(password=password, deadline=time.monotonic()+1800)
            audit(conn, 'unlock-ca')
        return jsonify(unlocked=True, valid_seconds=1800)

    @app.post('/api/ca/lock')
    @protected
    def lock_ca():
        with lock, connect(path) as conn:
            vault.update(password=None, deadline=0)
            audit(conn, 'lock-ca')
        return jsonify(unlocked=False)

    def attachment(data, filename, mime='application/x-pem-file'):
        return send_file(io.BytesIO(data), mimetype=mime, as_attachment=True, download_name=filename, max_age=0)

    @app.get('/api/ca/certificate')
    @protected
    def ca_certificate():
        with connect(path) as conn:
            row = conn.execute('SELECT cert FROM ca').fetchone()
        if row is None:
            raise ValueError('CA 尚未初始化')
        return attachment(row['cert'], 'ca-roots.crt')

    @app.get('/api/ca/crl')
    @protected
    def ca_crl():
        with connect(path) as conn:
            row = conn.execute('SELECT crl FROM ca').fetchone()
        if row is None:
            raise ValueError('CA 尚未初始化')
        return attachment(row['crl'], 'crls.pem')

    def update_crl(conn, row, cert, key):
        number = row['crl_number']+1
        revoked = conn.execute('SELECT serial,revoked_at,reason FROM certificates WHERE revoked_at IS NOT NULL').fetchall()
        crl = pki.make_crl(cert, key, number, revoked)
        conn.execute('UPDATE ca SET crl=?,crl_number=? WHERE id=1', (crl, number))
        return number

    @app.post('/api/ca/crl/refresh')
    @protected
    def refresh_crl():
        with lock:
            row, cert, key, _ = require_unlock()
            with connect(path) as conn:
                conn.execute('BEGIN IMMEDIATE')
                number = update_crl(conn, row, cert, key)
                audit(conn, 'refresh-crl', str(number))
        return jsonify(crl_number=number)

    @app.get('/api/devices')
    @protected
    def devices():
        limit = min(max(request.args.get('limit', default=100, type=int), 1), 200)
        offset = max(request.args.get('offset', default=0, type=int), 0)
        with connect(path) as conn:
            rows = conn.execute('SELECT '+PUBLIC_COLUMNS+' FROM certificates ORDER BY created_at DESC LIMIT ? OFFSET ?', (limit, offset)).fetchall()
            total = conn.execute('SELECT COUNT(*) FROM certificates').fetchone()[0]
        return jsonify(items=[dict(row) for row in rows], total=total, limit=limit, offset=offset)

    @app.post('/api/devices')
    @protected
    def issue():
        data = payload()
        request_id = request.headers.get('Idempotency-Key', '')
        if not request_id or len(request_id) > 64 or not request_id.isascii() or not request_id.replace('-', '').isalnum():
            raise ValueError('请提供最长 64 位字母、数字或连字符的 Idempotency-Key')
        digest = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        pki.device_options(data)
        with lock:
            with connect(path) as conn:
                previous = conn.execute('SELECT '+PUBLIC_COLUMNS+',request_hash FROM certificates WHERE request_id=?', (request_id,)).fetchone()
            if previous:
                if previous['request_hash'] != digest:
                    return jsonify(error='IDEMPOTENCY_CONFLICT', message='相同请求编号对应不同参数'), 409
                result = dict(previous)
                result.pop('request_hash')
                return jsonify(result)
            _, ca, key, password = require_unlock()
            issued = pki.issue_device(data, ca, key, password)
            identity = uuid.uuid4().hex
            values = dict(issued, id=identity, request_id=request_id, request_hash=digest)
            columns = list(values)
            with connect(path) as conn:
                conn.execute('INSERT INTO certificates('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')', list(values.values()))
                audit(conn, 'issue', identity)
                result = dict(conn.execute('SELECT '+PUBLIC_COLUMNS+' FROM certificates WHERE id=?', (identity,)).fetchone())
        return jsonify(result), 201

    def device_row(identity):
        with connect(path) as conn:
            row = conn.execute('SELECT * FROM certificates WHERE id=?', (identity,)).fetchone()
        if row is None:
            from werkzeug.exceptions import NotFound
            raise NotFound('未找到设备证书')
        return row

    @app.get('/api/devices/<identity>/<kind>')
    @protected
    def public_file(identity, kind):
        if kind not in ('certificate', 'csr'):
            from werkzeug.exceptions import NotFound
            raise NotFound()
        row = device_row(identity)
        return attachment(row['cert' if kind == 'certificate' else 'csr'], 'enc.crt' if kind == 'certificate' else 'device.csr.pem')

    @app.post('/api/devices/<identity>/export')
    @protected
    def export_device(identity):
        data = payload()
        mode = data.get('key_format', 'encrypted')
        if mode not in ('encrypted', 'plain'):
            raise ValueError('key_format 仅支持 encrypted 或 plain')
        if mode == 'plain' and data.get('confirm_plaintext') is not True:
            raise ValueError('导出未加密设备私钥须明确确认 confirm_plaintext=true')
        output_password = check_password(data.get('export_password')) if mode == 'encrypted' else None
        with lock:
            ca, _, _, password = require_unlock()
            row = device_row(identity)
            if row['revoked_at']:
                raise ValueError('已吊销证书不能导出私钥包')
            if pki.now() >= x509.load_pem_x509_certificate(row['cert']).not_valid_after_utc:
                raise ValueError('已过期证书不能导出私钥包')
            if output_password and hmac.compare_digest(output_password, password):
                raise ValueError('设备导出口令不能与 CA 保护口令相同')
            key = serialization.load_pem_private_key(row['encrypted_key'], password.encode())
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                for filename, content in [('enc.key', pki.key_pem(key, output_password)), ('enc.crt', row['cert']),
                                          ('device.csr.pem', row['csr']), ('ca-roots.crt', ca['cert']), ('crls.pem', ca['crl'])]:
                    info = zipfile.ZipInfo(filename)
                    info.external_attr = (0o100600 if filename == 'enc.key' else 0o100644) << 16
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info, content)
            with connect(path) as conn:
                audit(conn, 'export-device-'+mode, identity)
        return attachment(stream.getvalue(), 'device-'+identity+'.zip', 'application/zip')

    @app.post('/api/devices/<identity>/revoke')
    @protected
    def revoke(identity):
        reason = payload().get('reason', 'cessation_of_operation')
        if reason not in ('key_compromise', 'cessation_of_operation', 'superseded', 'affiliation_changed'):
            raise ValueError('吊销原因不合法')
        with lock:
            ca, cert, key, _ = require_unlock()
            row = device_row(identity)
            with connect(path) as conn:
                if row['revoked_at']:
                    return jsonify(revoked=True, crl_number=ca['crl_number'])
                conn.execute('BEGIN IMMEDIATE')
                conn.execute('UPDATE certificates SET revoked_at=?,reason=? WHERE id=?', (pki.now().isoformat(), reason, identity))
                number = update_crl(conn, ca, cert, key)
                audit(conn, 'revoke', identity)
        return jsonify(revoked=True, crl_number=number)

    @app.get('/api/events')
    @protected
    def events():
        with connect(path) as conn:
            rows = conn.execute('SELECT * FROM events ORDER BY id DESC LIMIT 200').fetchall()
        return jsonify(items=[dict(row) for row in rows])

    return app
