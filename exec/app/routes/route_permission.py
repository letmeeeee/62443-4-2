#!/usr/bin/env python3
from flask import request, jsonify, Blueprint, g, current_app
from sqlalchemy import text, select
from utils.method import _ensure_perm_table_in_request
import config
from utils.auth import (establish_session, revoke_session, is_developer_account_disabled,
                        login_capacity, LoginCapacityExceeded, list_login_sessions, revoke_session_by_id)
import utils.operationLog as operationLog
from datetime import datetime, timedelta
import json
import secrets
import time
from utils import security_store as security
from utils.auth import revoke_user_sessions, disconnect_revoked
from utils.access import allowed

permission_bp = Blueprint("permission", __name__)


@permission_bp.after_request
def log_auth_result(response):
    """Log actual HTTP auth outcomes, independently of Socket.IO activity."""
    actions = {
        'permission.permission_login': '用户登录',
        'permission.permission_logout': '用户退出登录',
    }
    action = actions.get(request.endpoint)
    is_session_query = request.endpoint == 'permission.permission_session' and request.method == 'GET'
    if not is_session_query and (action is None or request.method != 'POST'):
        return response
    from utils.utils import DPrint

    data = response.get_json(silent=True) or {}
    succeeded = response.status_code == 200 and data.get('ok') is True
    capacity_provider = current_app.extensions.get('web_connection_capacity')
    capacity = capacity_provider() if capacity_provider else None
    try:
        logins = login_capacity()
    except Exception:
        current_app.logger.exception('Failed to read login capacity')
        logins = None
    if logins is not None and (succeeded or response.status_code == 429):
        data['loginSessions'] = logins
        response.set_data(current_app.json.dumps(data))
    if succeeded and capacity is not None:
        data['webConnections'] = capacity
        response.set_data(current_app.json.dumps(data))
    if is_session_query:
        return response
    user = getattr(g, 'current_user', None) or {}
    username = data.get('username') or user.get('username') or '-'
    result = '成功' if succeeded else '失败'
    capacity_log = (f", logins={logins['active']}/{logins['limit']}, "
                    f"remaining={logins['remaining']}" if logins is not None else ', remaining=unknown')
    DPrint(f"[Auth] {action}{result}: username={username!r}, "
           f"ip={request.remote_addr}, path={request.path}, status={response.status_code}{capacity_log}")
    return response




def _account(conn, username):
    return conn.execute(text(f'SELECT * FROM `{config.PERM_TABLE}` WHERE username=:name'),
                        {'name': username}).mappings().first()


def _body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError('INVALID_JSON')
    return data


def _name(value):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 64:
        raise ValueError('INVALID_USERNAME')
    value = value.strip()
    if any(ord(c) < 32 for c in value):
        raise ValueError('INVALID_USERNAME')
    return value


def _date(value):
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def _audit(target, success, remark=''):
    user = getattr(g, 'current_user', {})
    operationLog.enqueue_operation_log(user.get('username', '-'), operationLog.OperationType.USER,
                                      target, 1, success, remark)


def _failure(code, status=400, **extra):
    return jsonify(ok=False, code=code, message=code, **extra), status


def _credentials_check(username, password):
    """Serialize counters with credential verification to enforce retry limits across workers."""
    if not isinstance(password, str) or not 1 <= len(password) <= 128:
        return None, _failure('INVALID_CREDENTIALS', 401)
    with config.engine.begin() as conn:
        security.lock_security(conn)
        row = _account(conn, username)
        keys = security.attempt_keys(row['username'] if row else username, security.source_ip())
        locked, remaining = security.record_attempt(conn, keys, check_only=True)
        if locked:
            return None, _failure('AUTH_LOCKED', 429, lock_seconds=locked, attempts_remaining=0)
        state = security.account_state(conn, row['username']) if row else None
        valid = row is not None and security.verify_password(password, row['password'], row['salt'])
        if row is None or not row['password'].startswith('pbkdf2_sha256$'):
            # Keep legacy/unknown-user rejection costs comparable during hash migration.
            security.hash_password(password)
        valid = valid and state['enabled'] and not is_developer_account_disabled(row['username'])
        if not valid:
            locked, remaining = security.record_attempt(conn, keys)
            return None, _failure('AUTH_LOCKED' if locked else 'INVALID_CREDENTIALS',
                                  429 if locked else 401, lock_seconds=locked, attempts_remaining=remaining)
        if row['first_login'] and _date(row['password_expire_at']) is not None and _date(row['password_expire_at']) <= datetime.now():
            return None, _failure('TEMPORARY_PASSWORD_EXPIRED', 401)
        security.record_attempt(conn, keys, success=True)
        return dict(row), None


@permission_bp.route('/permission/login', methods=['POST'])
def permission_login():
    err = _ensure_perm_table_in_request()
    if err:
        return _failure('AUTH_UNAVAILABLE', 503)
    try:
        data = _body()
        username = _name(data.get('username'))
        password = data.get('password')
        if not isinstance(password, str) or not 1 <= len(password) <= 128:
            return _failure('INVALID_CREDENTIALS', 401)
        g.audit_after = dict(claimed_username=username)
        row, error = _credentials_check(username, password)
        if error:
            _audit('user login', False, 'Authentication rejected')
            return error
        username = row['username']
        if not row['password'].startswith('pbkdf2_sha256$'):
            encoded = security.hash_password(password)
            with config.engine.begin() as conn:
                security.lock_security(conn)
                result = conn.execute(text(f'UPDATE `{config.PERM_TABLE}` SET password=:new WHERE '
                    'username=:name AND password=:old'), dict(new=encoded, name=username, old=row['password']))
                if result.rowcount != 1:
                    return _failure('CREDENTIALS_CHANGED', 409)
            row['password'] = encoded
        credentials = establish_session(username, row['password'], row['salt'])
        with config.engine.begin() as conn:
            conn.execute(security.ACCOUNT_STATE.update().where(
                security.ACCOUNT_STATE.c.username == username).values(last_login=time.time()))
            state = security.read_account_state(conn, username)
            maintenance = security.maintenance_state(conn)
        g.current_user = dict(username=username, uid=state['uid'], permission=int(row['permission']))
        g.session_id = credentials['session_token']
        expire = _date(row['password_expire_at'])
        left = (expire - datetime.now()).total_seconds() if expire else None
        operationLog.enqueue_operation_log(username, operationLog.OperationType.USER, 'user login', 1, True, '')
        return jsonify(ok=True, db_status=1, **credentials, username=username,
            uid=state['uid'], permission=int(row['permission']), first_login=int(row['first_login']),
            maintenance_until=maintenance['until'] if maintenance['active'] else None,
            password_expired=left is not None and left <= 0,
            password_warning=left is not None and 0 < left <= 15 * 86400,
            password_expire_at=expire.isoformat(sep=' ') if expire else None,
            password_days_left=max(0, int(left // 86400)) if left is not None else None)
    except ValueError as exc:
        return _failure(str(exc))
    except LoginCapacityExceeded:
        return _failure('LOGIN_LIMIT_REACHED', 429)
    except Exception:
        current_app.logger.exception('Login failed')
        return _failure('AUTH_UNAVAILABLE', 503)


@permission_bp.route('/permission/verify', methods=['POST'])
def permission_verify():
    try:
        row, error = _credentials_check(g.current_user['username'], _body().get('password'))
        _audit('session unlock', error is None)
        if error:
            return error
        from utils.auth import _digest
        with config.engine.begin() as conn:
            conn.execute(security.SESSION_LOCKS.delete().where(security.SESSION_LOCKS.c.sid == _digest(g.session_id)))
        return jsonify(ok=True)
    except ValueError as exc:
        return _failure(str(exc))


def _history(row, state):
    return ([{'hash': row['password'], 'salt': row['salt']}] + json.loads(state['history']))[:5]


def _public(row, state):
    expire = _date(row.get('password_expire_at'))
    left = (expire - datetime.now()).total_seconds() if expire else None
    return dict(username=row['username'], uid=state['uid'], enabled=bool(state['enabled']) and
        not is_developer_account_disabled(row['username']), status='enabled' if state['enabled'] and
        not is_developer_account_disabled(row['username']) else 'disabled',
        last_login=state['last_login'], permission=int(row['permission']), first_login=int(row['first_login']),
        password_expired=left is not None and left <= 0,
        password_warning=left is not None and 0 < left <= 15 * 86400,
        password_expire_at=expire.isoformat(sep=' ') if expire else None,
        password_created_at=str(row.get('password_created_at') or '') or None,
        password_days_left=max(0, int(left // 86400)) if left is not None else None)


@permission_bp.route('/permission/all', methods=['POST'])
def permission_all():
    with config.engine.begin() as conn:
        security.lock_security(conn)
        rows = conn.execute(text(f'SELECT * FROM `{config.PERM_TABLE}` ORDER BY username')).mappings().all()
        data = [_public(row, security.account_state(conn, row['username'])) for row in rows]
    return jsonify(ok=True, count=len(data), data=data)


@permission_bp.route('/permission/add', methods=['POST'])
def permission_add():
    try:
        data = _body()
        username = _name(data.get('username'))
        level = data.get('permission')
        if type(level) is not int or level not in (1, 2, 3, 4):
            raise ValueError('INVALID_PERMISSION')
        password = data.get('password')
        security.validate_password(password, username)
        encoded = security.hash_password(password)
        now = datetime.now()
        with config.engine.begin() as conn:
            security.lock_security(conn)
            if _account(conn, username):
                return _failure('USER_EXISTS', 409)
            state = security.account_state(conn, username)
            # Deleted identifiers are retained as tombstones; never silently reuse an identity.
            if not state['enabled']:
                return _failure('IDENTITY_RETIRED', 409)
            conn.execute(text(f'INSERT INTO `{config.PERM_TABLE}` '
                '(username,password,salt,permission,first_login,password_created_at,password_expire_at,last_notify_at) '
                'VALUES (:name,:password,:salt,:level,1,:created,:expires,NULL)'),
                dict(name=username, password=encoded, salt=secrets.token_hex(16), level=level,
                     created=now, expires=now + timedelta(days=180)))
        _audit('user add', True, username)
        return jsonify(ok=True, username=username, uid=state['uid'], permission=level, first_login=1)
    except ValueError as exc:
        return _failure(str(exc))


@permission_bp.route('/permission/update', methods=['POST'])
def permission_update():
    try:
        data = _body()
        username = _name(data.get('username'))
        if set(data) - {'username','new_username','password','old_password','permission','first_login','enabled','status','operatorName'}:
            raise ValueError('UNKNOWN_FIELD')
        with config.engine.connect() as lookup:
            target = _account(lookup, username)
        if target is None:
            return _failure('USER_NOT_FOUND', 404)
        username = target['username']
        admin = allowed('account:manage')
        own = username == g.current_user['username']
        if not admin and (not own or set(data) - {'username','password','old_password','first_login','operatorName'}):
            return _failure('FORBIDDEN', 403)
        if g.current_user.get('password_change_required') and not own:
            return _failure('PASSWORD_CHANGE_REQUIRED', 403)
        password = data.get('password')
        # Self-service always requires current password; admin changing another user is a reset.
        verified = None
        if password is not None and own:
            verified, error = _credentials_check(g.current_user['username'], data.get('old_password'))
            if error:
                return error
        with config.engine.begin() as conn:
            security.lock_security(conn)
            row = _account(conn, username)
            if row is None:
                _audit('user lookup', False, username)
                return _failure('USER_NOT_FOUND', 404)
            username = row['username']
            if verified and row['password'] != verified['password']:
                return _failure('CREDENTIALS_CHANGED', 409)
            state = security.account_state(conn, username)
            updates = {}
            meta = {}
            before = _public(row, state)
            if 'permission' in data:
                level = data['permission']
                if type(level) is not int or level not in (1,2,3,4):
                    raise ValueError('INVALID_PERMISSION')
                updates['permission'] = level
            if 'enabled' in data or 'status' in data:
                enabled = data.get('enabled')
                if 'status' in data:
                    if data['status'] not in ('enabled', 'disabled'):
                        raise ValueError('INVALID_STATUS')
                    mapped = data['status'] == 'enabled'
                    if 'enabled' in data and enabled != mapped:
                        raise ValueError('CONFLICTING_STATUS')
                    enabled = mapped
                if type(enabled) is not bool:
                    raise ValueError('INVALID_ENABLED')
                if enabled and is_developer_account_disabled(username):
                    return _failure('DEVELOPER_ACCOUNT_DISABLED', 409)
                meta['enabled'] = enabled
            if own and (meta.get('enabled') is False or updates.get('permission', row['permission']) != row['permission']):
                return _failure('SELF_ADMIN_CHANGE_DENIED', 409)
            if 'new_username' in data and data['new_username'] != username:
                # Stable user identifiers are supported; renaming would complicate audit tombstones.
                return _failure('USERNAME_IMMUTABLE', 409)
            if password is not None:
                history = _history(row, state)
                security.validate_password(password, username, history)
                updates.update(password=security.hash_password(password), salt=secrets.token_hex(16),
                    first_login=0 if own else 1, password_created_at=datetime.now(),
                    password_expire_at=datetime.now()+timedelta(days=180), last_notify_at=None)
                meta['history'] = json.dumps(history)
            elif 'first_login' in data:
                return _failure('PASSWORD_REQUIRED', 400)
            if not updates and not meta:
                raise ValueError('NO_FIELDS')
            if row['permission'] == 4 and (meta.get('enabled') is False or updates.get('permission', 4) != 4):
                if _active_admins(conn) <= 1:
                    return _failure('LAST_ADMIN', 409)
            if updates:
                clauses = ','.join(f'`{key}`=:{key}' for key in updates)
                conn.execute(text(f'UPDATE `{config.PERM_TABLE}` SET {clauses} WHERE username=:name'),
                             dict(updates, name=username))
            if meta:
                conn.execute(security.ACCOUNT_STATE.update().where(
                    security.ACCOUNT_STATE.c.username == username).values(**meta))
            ids = revoke_user_sessions(conn, username)
            g.audit_before = before
            g.audit_after = _public(_account(conn, username), security.read_account_state(conn, username))
        disconnect_revoked(ids)
        _audit('user update', True, username)
        return jsonify(ok=True, username=username, updated_fields=list(updates)+list(meta), sessions_revoked=len(ids))
    except ValueError as exc:
        return _failure(str(exc))


def _active_admins(conn):
    users = conn.execute(text(f'SELECT username FROM `{config.PERM_TABLE}` WHERE permission=4')).scalars().all()
    return sum(security.account_state(conn, user)['enabled'] and not is_developer_account_disabled(user) for user in users)


@permission_bp.route('/permission/delete', methods=['POST'])
def permission_delete():
    try:
        username = _name(_body().get('username'))
        with config.engine.begin() as conn:
            security.lock_security(conn)
            row = _account(conn, username)
            if row is None:
                _audit('user lookup', False, username)
                return _failure('USER_NOT_FOUND', 404)
            username = row['username']
            if username == g.current_user['username']:
                return _failure('SELF_DELETE_DENIED', 409)
            if row['permission'] == 4 and _active_admins(conn) <= 1:
                return _failure('LAST_ADMIN', 409)
            security.account_state(conn, username)
            conn.execute(text(f'DELETE FROM `{config.PERM_TABLE}` WHERE username=:name'), {'name':username})
            conn.execute(security.ACCOUNT_STATE.update().where(
                security.ACCOUNT_STATE.c.username == username).values(enabled=False))
            ids = revoke_user_sessions(conn, username)
        disconnect_revoked(ids)
        _audit('user delete', True, username)
        return jsonify(ok=True, deleted=username, sessions_revoked=len(ids))
    except ValueError as exc:
        return _failure(str(exc))


@permission_bp.route("/permission/session", methods=["GET"])
def permission_session():
    with config.engine.connect() as conn:
        maintenance = security.maintenance_state(conn)
    return jsonify(ok=True, username=g.current_user["username"],
                   permission=g.current_user["permission"], csrf_token=g.csrf_token,
                   uid=g.current_user.get('uid'), locked=g.session_locked,
                   maintenance_until=maintenance['until'] if maintenance['active'] else None,
                   password_change_required=g.current_user.get('password_change_required', False),
                   idle_timeout_minutes=current_app.config['AUTH_IDLE_SECONDS']/60)


@permission_bp.route("/permission/logout", methods=["POST"])
def permission_logout():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return _failure('INVALID_JSON')
    if data.get('force') is True:
        if not allowed('account:manage'):
            return _failure('FORBIDDEN', 403)
        try:
            username = _name(data.get('username'))
        except ValueError as exc:
            return _failure(str(exc))
        with config.engine.begin() as conn:
            security.lock_security(conn)
            user = _account(conn, username)
            if user is None:
                return _failure('USER_NOT_FOUND', 404)
            ids = revoke_user_sessions(conn, user['username'])
        disconnect_revoked(ids)
        _audit('force logout user', True, user['username'])
        return jsonify(ok=True, username=user['username'], sessions_revoked=len(ids))
    revoke_session(g.session_id)
    return jsonify(ok=True)


def _session_admin_allowed():
    return g.current_user["permission"] in config.PERMISSION_TABLE.get("usermanage", [])


@permission_bp.route("/permission/sessions", methods=["GET"])
def permission_sessions():
    if not _session_admin_allowed():
        return jsonify(ok=False, error="Administrator permission required"), 403
    try:
        return jsonify(ok=True, sessions=list_login_sessions(g.session_id))
    except Exception:
        current_app.logger.exception("Failed to list login sessions")
        return jsonify(ok=False, error="Session store unavailable"), 503


@permission_bp.route("/permission/sessions/revoke", methods=["POST"])
def permission_revoke_session():
    operator = g.current_user["username"]
    result = operationLog.OperationResult.FAIL
    remark = "Permission denied"
    try:
        if not _session_admin_allowed():
            return jsonify(ok=False, error="Administrator permission required"), 403
        data = request.get_json(silent=True)
        session_id = data.get("session_id") if isinstance(data, dict) else None
        if (not isinstance(session_id, str) or len(session_id) != 64
                or any(char not in "0123456789abcdef" for char in session_id)):
            remark = "Invalid session_id"
            return jsonify(ok=False, error="session_id must be a 64-character lowercase SHA-256 hex digest"), 400
        remark = f"session_id={session_id}"
        revoked = revoke_session_by_id(session_id)
        if revoked is None:
            return jsonify(ok=False, error="Session not found"), 404
        result = operationLog.OperationResult.SUCCESS
        remark += f"; username={revoked['username']}"
        return jsonify(ok=True, **revoked)
    except Exception:
        current_app.logger.exception("Failed to revoke login session")
        return jsonify(ok=False, error="Session store unavailable"), 503
    finally:
        operationLog.enqueue_operation_log(
            operator, operationLog.OperationType.USER, "force logout session",
            1, result, remark)



@permission_bp.route('/permission/reset-password', methods=['POST'])
def permission_reset_password():
    from utils.security_files import private_directory, private_write, temporary_password
    receipt = None
    committed = False
    try:
        data = _body()
        username = _name(data.get('username'))
        if data.get('confirm') != 'RESET_PASSWORD':
            return _failure('CONFIRMATION_REQUIRED', 409)
        password = temporary_password()
        encoded = security.hash_password(password)
        receipt_id = secrets.token_hex(16)
        receipt = private_directory('credentials') / (receipt_id + '.json')
        with config.engine.begin() as conn:
            security.lock_security(conn)
            row = _account(conn, username)
            if row is None:
                _audit('user lookup', False, username)
                return _failure('USER_NOT_FOUND', 404)
            username = row['username']
            state = security.account_state(conn, username)
            if not state['enabled'] or is_developer_account_disabled(username):
                return _failure('ACCOUNT_DISABLED', 409)
            private_write(receipt, json.dumps(dict(username=username, temporary_password=password,
                expires_at=time.time()+86400), ensure_ascii=False).encode())
            conn.execute(text(f'UPDATE `{config.PERM_TABLE}` SET password=:password,salt=:salt,first_login=1,'
                'password_created_at=:created,password_expire_at=:expires WHERE username=:name'),
                dict(password=encoded,salt=secrets.token_hex(16),created=datetime.now(),
                     expires=datetime.now()+timedelta(days=1),name=username))
            conn.execute(security.ACCOUNT_STATE.update().where(security.ACCOUNT_STATE.c.username==username)
                .values(history=json.dumps(_history(row,state))))
            ids = revoke_user_sessions(conn, username)
        committed = True
        disconnect_revoked(ids)
        _audit('password reset', True, username)
        return jsonify(ok=True, username=username, delivery_id=receipt_id,
                       delivery='device-local-admin', first_login=1, expires_in=86400)
    except ValueError as exc:
        return _failure(str(exc))
    finally:
        if receipt and receipt.exists() and not committed:
            receipt.unlink()


@permission_bp.route('/permission/lock', methods=['POST'])
def permission_lock():
    from utils.auth import _digest
    with config.engine.begin() as conn:
        security.lock_security(conn)
        sid = _digest(g.session_id)
        if not conn.execute(select(security.SESSION_LOCKS.c.sid).where(security.SESSION_LOCKS.c.sid==sid)).first():
            conn.execute(security.SESSION_LOCKS.insert().values(sid=sid,locked_at=time.time()))
    return jsonify(ok=True, locked=True)
