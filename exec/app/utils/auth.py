"""Explicit per-tab bearer credentials + persistent, revocable login sessions."""
import hashlib
import hmac
import os
import secrets
import time
from contextlib import contextmanager
from datetime import timedelta
from urllib.parse import urlsplit

from flask import current_app, g, jsonify, request
from sqlalchemy import Column, Float, MetaData, String, Table, Integer, select, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable
from utils import security_store as security


LOGIN_SESSIONS = Table(
    "login_sessions", MetaData(),
    Column("sid", String(64), primary_key=True),
    Column("username", String(64), nullable=False),
    Column("credential", String(64), nullable=False),
    Column("expires_at", Float(precision=53), nullable=False),
    Column("csrf_token", String(64), nullable=False),
    mysql_engine="InnoDB", mysql_charset="utf8mb4",
)

MAX_LOGIN_SESSIONS = 20
_HTTP_TOKEN = object()
LOGIN_CAPACITY_LOCK = Table(
    'login_capacity_lock', MetaData(), Column('id', Integer, primary_key=True),
    mysql_engine='InnoDB',
)


class LoginCapacityExceeded(Exception):
    pass


def login_capacity():
    with _store() as connection:
        active = connection.execute(select(func.count()).select_from(LOGIN_SESSIONS.join(
            security.SESSION_STATE, LOGIN_SESSIONS.c.sid == security.SESSION_STATE.c.sid)).where(
            LOGIN_SESSIONS.c.expires_at > time.time(), security.SESSION_STATE.c.last_activity >
            time.time()-current_app.config['AUTH_IDLE_SECONDS'])).scalar_one()
    return {'limit': MAX_LOGIN_SESSIONS, 'active': active,
            'remaining': max(0, MAX_LOGIN_SESSIONS - active)}


@contextmanager
def _store():
    # Reuse the same MySQL engine/pool as the account table.
    import config

    with config.engine.begin() as connection:
        yield connection


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def init_developer_accounts(app):
    """Load explicit account policy and revoke their existing sessions at startup."""
    enabled = app.config.get("DISABLE_DEVELOPER_ACCOUNTS", False)
    accounts = app.config.get("DEVELOPER_ACCOUNTS", [])
    if type(enabled) is not bool or not isinstance(accounts, list) or any(
        not isinstance(name, str) or not name.strip() for name in accounts
    ):
        raise ValueError("Invalid developer account configuration")
    if enabled and not accounts:
        raise ValueError("DEVELOPER_ACCOUNTS cannot be empty when disabling developer accounts")
    blocked = frozenset(name.strip().casefold() for name in accounts) if enabled else frozenset()
    app.extensions["disabled_developer_accounts"] = blocked
    if blocked:
        with app.app_context(), _store() as connection:
            # Normalize in Python, consistently with the checks below.
            names = connection.execute(LOGIN_SESSIONS.select()).mappings().all()
            sids = [row["sid"] for row in names if row["username"].casefold() in blocked]
            if sids:
                connection.execute(LOGIN_SESSIONS.delete().where(LOGIN_SESSIONS.c.sid.in_(sids)))


def is_developer_account_disabled(username):
    return username.casefold() in current_app.extensions.get("disabled_developer_accounts", ())


def load_user(username):
    # Lazy imports keep authentication infrastructure independent of device startup.
    from sqlalchemy import text
    import config

    with config.engine.connect() as connection:
        row = connection.execute(text(
            f"SELECT username, password, salt, permission, first_login, password_expire_at FROM `{config.PERM_TABLE}` "
            "WHERE username=:username"
        ), {"username": username}).fetchone()
        state = security.read_account_state(connection, row[0]) if row else None
    if row is None:
        return None
    return {
        "username": row[0], "permission": int(row[3]),
        "credential": _digest(row[1] + ":" + row[2]),
        "disabled": is_developer_account_disabled(row[0]) or bool(state and not state['enabled']),
        "uid": state['uid'] if state else None,
        "password_change_required": bool(row[4]) or _password_expired(row[5]),
    }


def _password_expired(value):
    from datetime import datetime
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value is not None and value < datetime.now()


def revoke_user_sessions(connection, username):
    ids = connection.execute(select(LOGIN_SESSIONS.c.sid).where(
        LOGIN_SESSIONS.c.username == username)).scalars().all()
    connection.execute(LOGIN_SESSIONS.delete().where(LOGIN_SESSIONS.c.username == username))
    if ids:
        connection.execute(security.SESSION_STATE.delete().where(security.SESSION_STATE.c.sid.in_(ids)))
        connection.execute(security.SESSION_LOCKS.delete().where(security.SESSION_LOCKS.c.sid.in_(ids)))
    return ids


def disconnect_revoked(ids):
    for sid in ids:
        _disconnect_session(sid, hashed=True)


def request_session_token():
    """Never fall back to shared cookies or accept credentials in URLs."""
    parts = request.headers.get("Authorization", "").split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


def _disconnect_session(sid, *, hashed=False):
    extension = "disconnect_session_connections_by_id" if hashed else "disconnect_session_connections"
    disconnect = current_app.extensions.get(extension)
    if sid and disconnect:
        try:
            disconnect(sid)
        except Exception:
            # The DB transaction has committed; a socket failure must not hide
            # a successful login/logout or leave a new credential undelivered.
            current_app.logger.exception("Failed to disconnect revoked session connections")


def revoke_session(sid=None):
    if sid is None:
        sid = request_session_token()
    if isinstance(sid, str) and sid:
        with _store() as connection:
            connection.execute(LOGIN_SESSIONS.delete().where(LOGIN_SESSIONS.c.sid == _digest(sid)))
            connection.execute(security.SESSION_STATE.delete().where(security.SESSION_STATE.c.sid == _digest(sid)))
            connection.execute(security.SESSION_LOCKS.delete().where(security.SESSION_LOCKS.c.sid == _digest(sid)))
        _disconnect_session(sid)


def list_login_sessions(current_token):
    """Expose management identifiers, never bearer/CSRF tokens or credentials."""
    now = time.time()
    with _store() as connection:
        rows = connection.execute(select(
            LOGIN_SESSIONS.c.sid, LOGIN_SESSIONS.c.username, LOGIN_SESSIONS.c.expires_at,
            security.SESSION_STATE.c.last_activity, security.SESSION_STATE.c.tab_id
        ).select_from(LOGIN_SESSIONS.outerjoin(security.SESSION_STATE,
            LOGIN_SESSIONS.c.sid == security.SESSION_STATE.c.sid)).order_by(LOGIN_SESSIONS.c.username, LOGIN_SESSIONS.c.expires_at,
                   LOGIN_SESSIONS.c.sid)).mappings().all()
    current_id = _digest(current_token)
    return [{"session_id": row["sid"], "username": row["username"],
             "expires_at": row["expires_at"], "last_activity": row['last_activity'], "tab_id": row['tab_id'],
             "expired": row["expires_at"] <= now or row['last_activity'] is None or
                        row['last_activity'] + current_app.config['AUTH_IDLE_SECONDS'] <= now,
             "current": row["sid"] == current_id} for row in rows]


def revoke_session_by_id(session_id):
    """Delete exactly one stored digest; disconnect only after commit."""
    with _store() as connection:
        row = connection.execute(select(
            LOGIN_SESSIONS.c.username
        ).where(LOGIN_SESSIONS.c.sid == session_id).with_for_update()).mappings().first()
        if row is None:
            return None
        connection.execute(LOGIN_SESSIONS.delete().where(LOGIN_SESSIONS.c.sid == session_id))
        connection.execute(security.SESSION_STATE.delete().where(security.SESSION_STATE.c.sid == session_id))
        connection.execute(security.SESSION_LOCKS.delete().where(security.SESSION_LOCKS.c.sid == session_id))
        username = row["username"]
    _disconnect_session(session_id, hashed=True)
    return {"session_id": session_id, "username": username}


def establish_session(username, password_hash, salt):
    """Rotate only the credential explicitly supplied by the logging-in tab."""
    previous_sid = request_session_token()
    sid = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    expires_at = time.time() + current_app.permanent_session_lifetime.total_seconds()
    with _store() as connection:
        # Serialize admission across workers using an InnoDB row lock (also works on SQLite).
        connection.execute(LOGIN_CAPACITY_LOCK.update().where(
            LOGIN_CAPACITY_LOCK.c.id == 1).values(id=1))
        connection.execute(LOGIN_SESSIONS.delete().where(or_(LOGIN_SESSIONS.c.expires_at <= time.time(),
            ~LOGIN_SESSIONS.c.sid.in_(select(security.SESSION_STATE.c.sid).where(
                security.SESSION_STATE.c.last_activity > time.time()-current_app.config['AUTH_IDLE_SECONDS'])))))
        if isinstance(previous_sid, str):
            connection.execute(LOGIN_SESSIONS.delete().where(
                LOGIN_SESSIONS.c.sid == _digest(previous_sid)))
        active = connection.execute(select(func.count()).select_from(LOGIN_SESSIONS)).scalar_one()
        if active >= MAX_LOGIN_SESSIONS:
            # Transaction rollback preserves any previous session on rejection.
            raise LoginCapacityExceeded()
        connection.execute(LOGIN_SESSIONS.insert().values(
            sid=_digest(sid), username=username,
            credential=_digest(password_hash + ":" + salt),
            expires_at=expires_at, csrf_token=csrf_token,
        ))
        connection.execute(security.SESSION_STATE.insert().values(
            sid=_digest(sid), last_activity=time.time(), tab_id=validated_tab_id()))
        connection.execute(security.SESSION_STATE.delete().where(
            ~security.SESSION_STATE.c.sid.in_(select(LOGIN_SESSIONS.c.sid))))
        connection.execute(security.SESSION_LOCKS.delete().where(
            ~security.SESSION_LOCKS.c.sid.in_(select(LOGIN_SESSIONS.c.sid))))
    _disconnect_session(previous_sid)
    return {"session_token": sid, "csrf_token": csrf_token, "expires_at": expires_at,
            "idle_timeout_minutes": current_app.config['AUTH_IDLE_SECONDS'] / 60}


def validated_tab_id():
    import re
    value = request.headers.get('X-Tab-Id', '')
    return value if re.fullmatch(r'[A-Za-z0-9_-]{0,64}', value) else ''


def authenticate_session(token=_HTTP_TOKEN):
    # Socket.IO supplies its auth payload explicitly; HTTP uses Authorization.
    sid = request_session_token() if token is _HTTP_TOKEN else token
    if not isinstance(sid, str) or not sid:
        return False
    with _store() as connection:
        security.lock_security(connection)
        row = connection.execute(
            LOGIN_SESSIONS.select().where(LOGIN_SESSIONS.c.sid == _digest(sid))
        ).mappings().first()
        activity = connection.execute(select(security.SESSION_STATE).where(
            security.SESSION_STATE.c.sid == _digest(sid))).mappings().first()
        locked = connection.execute(select(security.SESSION_LOCKS.c.sid).where(
            security.SESSION_LOCKS.c.sid == _digest(sid))).first() is not None
        # Pre-migration sessions have no activity baseline; require reauthentication.
        idle_expired = activity is None or activity['last_activity'] + current_app.config['AUTH_IDLE_SECONDS'] <= time.time()
        if row and not idle_expired:
            connection.execute(security.SESSION_STATE.update().where(
                security.SESSION_STATE.c.sid == _digest(sid)).values(
                    last_activity=time.time(), tab_id=validated_tab_id() or activity['tab_id']))
    if row is None or row["expires_at"] <= time.time() or idle_expired:
        revoke_session(sid)
        return False
    user = current_app.config["AUTH_USER_LOADER"](row["username"])
    if (user is None or user.get("disabled", False)
            or not hmac.compare_digest(user["credential"], row["credential"])):
        revoke_session(sid)
        return False
    if token is not _HTTP_TOKEN and (locked or user.get('password_change_required')):
        return False
    g.current_user = user
    g.csrf_token = row["csrf_token"]
    g.session_id = sid
    g.session_locked = locked
    return True


def _same_origin():
    origin = request.headers.get("Origin") or request.headers.get("Referer")
    if origin:
        try:
            parsed = urlsplit(origin)
        except ValueError:
            return False
        scheme = "https" if current_app.config["SESSION_COOKIE_SECURE"] else request.scheme
        return (parsed.scheme, parsed.netloc) == (scheme, request.host)
    return request.headers.get("Sec-Fetch-Site") == "same-origin"


def init_auth(app):
    secret = app.config.get("SECRET_KEY") or os.environ.get("FLASK_SECRET_KEY")
    if not secret or len(secret) < 32:
        raise RuntimeError("Set FLASK_SECRET_KEY to a persistent random secret of at least 32 characters")
    app.config.update(
        SECRET_KEY=secret,
        SESSION_COOKIE_NAME="lc_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=app.config.get(
            "AUTH_COOKIE_SECURE", os.environ.get("SESSION_COOKIE_SECURE", "1") != "0"),
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_REFRESH_EACH_REQUEST=False,
        PERMANENT_SESSION_LIFETIME=timedelta(seconds=int(
            app.config.get("AUTH_SESSION_SECONDS", os.environ.get("AUTH_SESSION_SECONDS", "1800")))),
    )
    if app.permanent_session_lifetime.total_seconds() <= 0:
        raise ValueError("AUTH_SESSION_SECONDS must be positive")
    app.config.setdefault("AUTH_USER_LOADER", load_user)
    app.config.setdefault('AUTH_IDLE_SECONDS', 900)
    if not isinstance(app.config['AUTH_IDLE_SECONDS'], int) or app.config['AUTH_IDLE_SECONDS'] <= 0:
        raise ValueError('AUTH_IDLE_SECONDS must be a positive integer')
    # IF NOT EXISTS also permits simultaneous worker startup. DDL errors abort startup.
    with app.app_context(), _store() as connection:
        connection.execute(CreateTable(LOGIN_SESSIONS, if_not_exists=True))
        connection.execute(CreateTable(LOGIN_CAPACITY_LOCK, if_not_exists=True))
    try:
        with app.app_context(), _store() as connection:
            connection.execute(LOGIN_CAPACITY_LOCK.insert().values(id=1))
    except IntegrityError:
        # Another startup (or previous run) already initialized the singleton row.
        pass
    init_developer_accounts(app)
    with app.app_context(), _store() as connection:
        security.metadata.create_all(connection)

    @app.before_request
    def check_session():
        # Only the SPA, static assets, and login are public. New routes are protected by default.
        if request.endpoint in (None, "static", "serve_spa"):
            return None
        if request.method == "OPTIONS":
            return app.make_default_options_response()
        try:
            with _store() as connection:
                if not security.admit_request(connection, security.source_ip(),
                        app.config.get('HTTP_REQUESTS_PER_MINUTE',3000)):
                    return jsonify(ok=False,code='RATE_LIMITED',message='Request rate exceeded'),429
        except Exception:
            app.logger.exception('Request admission failed')
            return jsonify(ok=False,code='SERVICE_UNAVAILABLE'),503
        if request.path == '/permission/login-notice' and request.method == 'GET':
            return None
        if request.endpoint == "permission.permission_login":
            if (request.headers.get("Origin") or request.headers.get("Referer")
                    or request.headers.get("Sec-Fetch-Site")) and not _same_origin():
                return jsonify(ok=False, error="Cross-origin login denied"), 403
            return None
        try:
            if not authenticate_session():
                return jsonify(ok=False, error="Authentication required", code="SESSION_INVALID"), 401
        except Exception:
            app.logger.exception("Session verification failed")
            return jsonify(ok=False, error="Authentication service unavailable"), 503
        if request.method not in ("GET", "HEAD") and not _same_origin():
            token = request.headers.get("X-CSRF-Token", "")
            if not hmac.compare_digest(token.encode("utf-8"), g.csrf_token.encode("utf-8")):
                return jsonify(ok=False, error="CSRF validation failed"), 403
        from utils.access import request_ability, allowed
        if request.path == '/export_csv_stream':
            import re
            table = request.args.get('table','')
            if not re.fullmatch(r'(?:bms|fault|meter|mv|pcsgroup|pcsmodel|rack|system)[0-9]{8}',table):
                return jsonify(ok=False,code='EXPORT_TABLE_NOT_ALLOWED'),400
        if g.session_locked and request.path not in ('/permission/session','/permission/verify',
                '/permission/logout','/permission/lock'):
            return jsonify(ok=False, code='SESSION_LOCKED', message='Unlock session before continuing'), 403
        if request.path == '/api':
            if request.method == 'GET':
                return jsonify(ok=False, code='SQL_ENDPOINT_DISABLED'), 410
            from utils.access import validate_protocol_request
            error = validate_protocol_request()
            if error:
                return jsonify(ok=False, code=error), 400
        ability = request_ability()
        if ability and not allowed(ability):
            from utils import operationLog
            operationLog.enqueue_operation_log(g.current_user['username'],
                operationLog.OperationType.USER, request.path, 1, False, 'Permission denied')
            return jsonify(ok=False, code='FORBIDDEN', message='Permission denied'), 403
        if request.method not in ('GET','HEAD'):
            with _store() as connection:
                maintenance = security.maintenance_state(connection)
            maintenance_allowed = (request.path.startswith(('/api/security/backups','/api/cert/','/api/security/certificates')) or request.path in (
                '/api/security/maintenance','/api/security/factory-reset','/api/security/decommission',
                '/permission/logout','/permission/lock','/permission/verify','/permission/sessions/revoke','/permission/all'))
            if maintenance['active'] and not maintenance_allowed:
                return jsonify(ok=False,code='MAINTENANCE_IN_PROGRESS',message='Maintenance mode is active'),409
        if (g.current_user.get('password_change_required') and request.path not in
                ('/permission/session', '/permission/logout', '/permission/update',
                 '/permission/verify', '/permission/lock', '/api/security/password-policy')):
            return jsonify(ok=False, code='PASSWORD_CHANGE_REQUIRED', message='Change password before continuing'), 403

    @app.after_request
    def prevent_auth_caching(response):
        if request.endpoint not in (None, "static", "serve_spa"):
            response.headers["Cache-Control"] = "no-store"
        return response
