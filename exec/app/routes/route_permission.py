#!/usr/bin/env python3
from flask import request, jsonify, Blueprint, g, current_app
from sqlalchemy import text, select
from utils.method import _ensure_perm_table_in_request
import config
from utils.auth import (
    establish_session,
    revoke_session,
    is_developer_account_disabled,
    login_capacity,
    LoginCapacityExceeded,
    list_login_sessions,
    revoke_session_by_id,
)
import utils.operationLog as operationLog
from datetime import datetime, timedelta
import json
import secrets
import time
from utils import security_store as security
from utils.auth import revoke_user_sessions, disconnect_revoked
from utils.access import allowed

permission_bp = Blueprint("permission", __name__)


def _permission_log(event, *, level='INFO', **details):
    """补充排障打印，不新增或替代任何业务日志、安全审计记录。

    details 仅传入明确挑选的状态和对象标识，不能传请求体、口令、哈希、盐或 Token。
    """
    try:
        from utils.utils import DPrint
        import sys

        user = getattr(g, 'current_user', None) or {}
        context = {
            'operator': user.get('username', '-'),
            'method': request.method,
            'path': request.path,
            'ip': request.remote_addr,
            'trace_id': getattr(g, 'trace_id', None),
            **details,
        }
        if sys.exc_info()[0] is not None:
            # 只补充异常类型，不展开可能携带凭据或 SQL 参数的异常文本。
            context['exception_type'] = sys.exc_info()[0].__name__
        fields = ' '.join(f'{key}={value!r}' for key, value in context.items())
        DPrint(f'[Permission] {event}: {fields}', level=level)
    except Exception:
        # 新增的排障打印失败时不改变接口、业务日志或安全审计的原有流程。
        pass


@permission_bp.after_request
def log_auth_result(response):
    """记录登录、退出的实际 HTTP 结果，并补充现有连接容量字段。

    会话查询仅补充容量字段，不打印每次轮询；不改变业务日志或安全审计的落库方式。
    """
    actions = {
        'permission.permission_login': '用户登录',
        'permission.permission_logout': '用户退出登录',
    }
    action = actions.get(request.endpoint)
    is_session_query = (
        request.endpoint == 'permission.permission_session' and request.method == 'GET'
    )
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
        _permission_log('读取登录容量失败', level='ERROR')
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
    capacity_log = (
        f", logins={logins['active']}/{logins['limit']}, " f"remaining={logins['remaining']}"
        if logins is not None
        else ', remaining=unknown'
    )
    DPrint(
        f"[Auth] {action}{result}: username={username!r}, "
        f"ip={request.remote_addr}, path={request.path}, status={response.status_code}{capacity_log}"
    )
    return response


def _account(conn, username):
    """按用户名查询原始账号记录，仅供后端校验，不将口令字段直接返回客户端。"""
    return (
        conn.execute(
            text(f'SELECT * FROM `{config.PERM_TABLE}` WHERE username=:name'), {'name': username}
        )
        .mappings()
        .first()
    )


def _body():
    """读取 JSON 对象；form-data、解析失败及非对象请求体均抛出 INVALID_JSON。"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        _permission_log(
            '请求体不是有效 JSON 对象', level='WARNING', content_type=request.content_type
        )
        raise ValueError('INVALID_JSON')
    return data


def _name(value):
    """校验用户名并去除首尾空格，拒绝空值、超长值及控制字符。"""
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 64:
        raise ValueError('INVALID_USERNAME')
    value = value.strip()
    if any(ord(c) < 32 for c in value):
        raise ValueError('INVALID_USERNAME')
    return value


def _date(value):
    """将字符串时间转换为 datetime，数据库已返回 datetime 时保持原值。"""
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def _audit(target, success, remark=''):
    """沿用原有业务日志队列，并为公共安全审计设置对象或事件类型。

    操作人始终来自当前已验证会话，不使用客户端 operatorName。
    """
    user = getattr(g, 'current_user', {})
    if success and target in (
        'user add',
        'user update',
        'user delete',
        'password reset',
        'force logout user',
    ):
        g.audit_target = remark
    elif target == 'session unlock':
        g.audit_target = user.get('username', 'unknown account')
    if success and target == 'force logout user':
        g.audit_event_type = 'account.sessions.revoke'
    operationLog.enqueue_operation_log(
        user.get('username', '-'), operationLog.OperationType.USER, target, 1, success, remark
    )


def _failure(code, status=400, **extra):
    """沿用原有错误结构和 HTTP 状态，并额外打印错误码以便排障。"""
    _permission_log(
        '请求拒绝',
        level='WARNING',
        code=code,
        status=status,
        attempts_remaining=extra.get('attempts_remaining'),
        lock_seconds=extra.get('lock_seconds'),
    )
    return jsonify(ok=False, code=code, message=code, **extra), status


def _credentials_check(username, password):
    """验证指定账号的当前口令，并在事务内串行更新失败计数。

    返回 (账号记录, None) 或 (None, 错误响应)。
    保留原有锁定、启停状态、开发账号禁用和首次登录口令过期判断。
    同时供登录、解锁及本人改密使用；日志不输出口令、哈希或盐。
    """
    _permission_log('开始验证当前口令', username=username)
    if not isinstance(password, str) or not 1 <= len(password) <= 128:
        return None, _failure('INVALID_CREDENTIALS', 401)
    with config.engine.begin() as conn:
        security.lock_security(conn)
        row = _account(conn, username)
        keys = security.attempt_keys(row['username'] if row else username, security.source_ip())
        locked, remaining = security.record_attempt(conn, keys, check_only=True)
        if locked:
            _permission_log(
                '口令验证被锁定', level='WARNING', username=username, lock_seconds=locked
            )
            return None, _failure('AUTH_LOCKED', 429, lock_seconds=locked, attempts_remaining=0)
        state = security.account_state(conn, row['username']) if row else None
        valid = row is not None and security.verify_password(password, row['password'], row['salt'])
        if row is None or not row['password'].startswith('pbkdf2_sha256$'):
            # 迁移旧哈希时，保留未知账号与旧账号的校验耗时补偿。
            security.hash_password(password)
        valid = valid and state['enabled'] and not is_developer_account_disabled(row['username'])
        if not valid:
            _permission_log('口令校验或账号可用性校验未通过', level='WARNING', username=username)
            locked, remaining = security.record_attempt(conn, keys)
            return None, _failure(
                'AUTH_LOCKED' if locked else 'INVALID_CREDENTIALS',
                429 if locked else 401,
                lock_seconds=locked,
                attempts_remaining=remaining,
            )
        if (
            row['first_login']
            and _date(row['password_expire_at']) is not None
            and _date(row['password_expire_at']) <= datetime.now()
        ):
            return None, _failure('TEMPORARY_PASSWORD_EXPIRED', 401)
        security.record_attempt(conn, keys, success=True)
        _permission_log('当前口令验证通过', username=row['username'])
        return dict(row), None


# 用户登录
@permission_bp.route('/permission/login', methods=['POST'])
def permission_login():
    """用户登录接口。

    请求示例：
      POST /permission/login
      {"username": "TEST1", "password": "<当前口令>"}

    返回：ok、session_token、csrf_token、expires_at、用户身份及口令到期信息。
    first_login=1 时前端应先进入改密流程，改密后需重新登录。
    旧口令哈希仅在校验成功后迁移；会话签发与容量限制保持原有流程。
    """
    # 1. 确认账号表可用，再解析并校验登录参数。
    err = _ensure_perm_table_in_request()
    if err:
        return _failure('AUTH_UNAVAILABLE', 503)
    try:
        data = _body()
        username = _name(data.get('username'))
        _permission_log('开始登录', username=username)
        password = data.get('password')
        if not isinstance(password, str) or not 1 <= len(password) <= 128:
            return _failure('INVALID_CREDENTIALS', 401)
        g.audit_after = dict(claimed_username=username)
        row, error = _credentials_check(username, password)
        if error:
            _audit('user login', False, 'Authentication rejected')
            return error
        username = row['username']
        # 2. 仅在原口令验证通过后迁移旧哈希，保留并发凭据变更检查。
        if not row['password'].startswith('pbkdf2_sha256$'):
            encoded = security.hash_password(password)
            with config.engine.begin() as conn:
                security.lock_security(conn)
                result = conn.execute(
                    text(
                        f'UPDATE `{config.PERM_TABLE}` SET password=:new WHERE '
                        'username=:name AND password=:old'
                    ),
                    dict(new=encoded, name=username, old=row['password']),
                )
                if result.rowcount != 1:
                    return _failure('CREDENTIALS_CHANGED', 409)
            row['password'] = encoded
        # 3. 签发会话，更新最后登录时间，并读取维护状态。
        credentials = establish_session(username, row['password'], row['salt'])
        with config.engine.begin() as conn:
            conn.execute(
                security.ACCOUNT_STATE.update()
                .where(security.ACCOUNT_STATE.c.username == username)
                .values(last_login=time.time())
            )
            state = security.read_account_state(conn, username)
            maintenance = security.maintenance_state(conn)
        g.current_user = dict(
            username=username, uid=state['uid'], permission=int(row['permission'])
        )
        g.session_id = credentials['session_token']
        expire = _date(row['password_expire_at'])
        left = (expire - datetime.now()).total_seconds() if expire else None
        operationLog.enqueue_operation_log(
            username, operationLog.OperationType.USER, 'user login', 1, True, ''
        )
        _permission_log(
            '登录凭据已签发',
            username=username,
            first_login=int(row['first_login']),
            permission=int(row['permission']),
        )
        # 4. 返回前端需要的会话及口令期限字段，不打印凭据内容。
        return jsonify(
            ok=True,
            db_status=1,
            **credentials,
            username=username,
            uid=state['uid'],
            permission=int(row['permission']),
            first_login=int(row['first_login']),
            maintenance_until=maintenance['until'] if maintenance['active'] else None,
            password_expired=left is not None and left <= 0,
            password_warning=left is not None and 0 < left <= 15 * 86400,
            password_expire_at=expire.isoformat(sep=' ') if expire else None,
            password_days_left=max(0, int(left // 86400)) if left is not None else None,
        )
    except ValueError as exc:
        return _failure(str(exc))
    except LoginCapacityExceeded:
        return _failure('LOGIN_LIMIT_REACHED', 429)
    except Exception:
        current_app.logger.exception('Login failed')
        _permission_log('登录处理异常', level='ERROR')
        return _failure('AUTH_UNAVAILABLE', 503)


# 验证口令并解锁会话
@permission_bp.route('/permission/verify', methods=['POST'])
def permission_verify():
    """验证当前用户口令并解锁当前会话。

    请求示例：POST /permission/verify，JSON：{"password": "<当前口令>"}。
    请求需携带当前会话认证信息；成功返回 {ok: true}，不签发新 Token。
    """
    try:
        _permission_log('开始解锁当前会话')
        row, error = _credentials_check(g.current_user['username'], _body().get('password'))
        _audit('session unlock', error is None)
        if error:
            return error
        from utils.auth import _digest

        with config.engine.begin() as conn:
            conn.execute(
                security.SESSION_LOCKS.delete().where(
                    security.SESSION_LOCKS.c.sid == _digest(g.session_id)
                )
            )
        _permission_log('当前会话已解锁')
        return jsonify(ok=True)
    except ValueError as exc:
        return _failure(str(exc))


def _history(row, state):
    """构造最近五次口令历史，仅用于复用检查，不写入排障日志或对外响应。"""
    return ([{'hash': row['password'], 'salt': row['salt']}] + json.loads(state['history']))[:5]


def _public(row, state):
    """构造对外账号信息，保留启用状态及口令期限字段，排除口令哈希与盐。"""
    expire = _date(row.get('password_expire_at'))
    left = (expire - datetime.now()).total_seconds() if expire else None
    return dict(
        username=row['username'],
        uid=state['uid'],
        enabled=bool(state['enabled']) and not is_developer_account_disabled(row['username']),
        status=(
            'enabled'
            if state['enabled'] and not is_developer_account_disabled(row['username'])
            else 'disabled'
        ),
        last_login=state['last_login'],
        permission=int(row['permission']),
        first_login=int(row['first_login']),
        password_expired=left is not None and left <= 0,
        password_warning=left is not None and 0 < left <= 15 * 86400,
        password_expire_at=expire.isoformat(sep=' ') if expire else None,
        password_created_at=str(row.get('password_created_at') or '') or None,
        password_days_left=max(0, int(left // 86400)) if left is not None else None,
    )


# 账号列表查询
@permission_bp.route('/permission/all', methods=['POST'])
def permission_all():
    """查询账号列表，沿用 POST 方法及管理员权限要求。

    请求示例：POST /permission/all，JSON：{}。
    返回：{ok: true, count: 数量, data: [账号公开信息]}。
    """
    _permission_log('开始查询账号列表')
    with config.engine.begin() as conn:
        security.lock_security(conn)
        rows = (
            conn.execute(text(f'SELECT * FROM `{config.PERM_TABLE}` ORDER BY username'))
            .mappings()
            .all()
        )
        data = [_public(row, security.account_state(conn, row['username'])) for row in rows]
    _permission_log('账号列表查询完成', count=len(data))
    return jsonify(ok=True, count=len(data), data=data)


# 创建账号
@permission_bp.route('/permission/add', methods=['POST'])
def permission_add():
    """创建账号接口。

    请求示例：
      POST /permission/add
      {"username": "TEST1", "password": "<初始口令>", "permission": 2}

    permission 必须为整数 1～4，口令按当前策略校验。
    成功返回用户名、uid、permission、first_login=1；首次登录后需要本人改密。
    """
    try:
        data = _body()
        username = _name(data.get('username'))
        _permission_log('开始创建账号', username=username)
        # 1. 校验角色和初始口令，随后生成存储哈希。
        level = data.get('permission')
        if type(level) is not int or level not in (1, 2, 3, 4):
            raise ValueError('INVALID_PERMISSION')
        password = data.get('password')
        security.validate_password(password, username)
        encoded = security.hash_password(password)
        now = datetime.now()
        # 2. 事务内校验重名和身份墓碑，插入首次登录状态的账号。
        with config.engine.begin() as conn:
            security.lock_security(conn)
            if _account(conn, username):
                return _failure('USER_EXISTS', 409)
            state = security.account_state(conn, username)
            # 已删除账号的身份标识保留为墓碑，禁止静默复用。
            if not state['enabled']:
                return _failure('IDENTITY_RETIRED', 409)
            conn.execute(
                text(
                    f'INSERT INTO `{config.PERM_TABLE}` '
                    '(username,password,salt,permission,first_login,password_created_at,password_expire_at,last_notify_at) '
                    'VALUES (:name,:password,:salt,:level,1,:created,:expires,NULL)'
                ),
                dict(
                    name=username,
                    password=encoded,
                    salt=secrets.token_hex(16),
                    level=level,
                    created=now,
                    expires=now + timedelta(days=180),
                ),
            )
        _audit('user add', True, username)
        _permission_log('账号创建完成', username=username, permission=level, first_login=1)
        return jsonify(
            ok=True, username=username, uid=state['uid'], permission=level, first_login=1
        )
    except ValueError as exc:
        return _failure(str(exc))


# 更新账号与本人改密
@permission_bp.route('/permission/update', methods=['POST'])
def permission_update():
    """更新账号或修改本人当前口令，沿用 JSON 请求格式。

    本人改密示例：
      POST /permission/update
      {"username": "TEST1", "old_password": "<当前口令>", "password": "<新口令>"}

    password 是新口令；普通用户仅能修改本人允许的字段，不能携带角色或启停字段。
    本人改密必须校验 old_password，成功后 first_login 自动置 0。
    管理员修改他人口令按重置处理，first_login 置 1。
    成功返回 updated_fields、sessions_revoked；目标账号的会话被撤销，需要重新登录。
    """
    try:
        data = _body()
        username = _name(data.get('username'))
        _permission_log('开始更新账号', username=username)
        # 1. 先限制字段，再查询数据库中的规范账号名。
        if set(data) - {
            'username',
            'new_username',
            'password',
            'old_password',
            'permission',
            'first_login',
            'enabled',
            'status',
            'operatorName',
        }:
            raise ValueError('UNKNOWN_FIELD')
        with config.engine.connect() as lookup:
            target = _account(lookup, username)
        if target is None:
            return _failure('USER_NOT_FOUND', 404)
        username = target['username']
        # 2. 区分管理员操作与本人操作；首次改密只允许修改本人。
        admin = allowed('account:manage')
        own = username == g.current_user['username']
        _permission_log(
            '账号更新权限上下文', username=username, administrator=admin, own_account=own
        )
        if not admin and (
            not own
            or set(data) - {'username', 'password', 'old_password', 'first_login', 'operatorName'}
        ):
            _permission_log(
                '无权修改目标账号或提交了管理字段',
                level='WARNING',
                username=username,
                own_account=own,
                management_fields=sorted(
                    set(data) & {'permission', 'enabled', 'status', 'new_username'}
                ),
            )
            return _failure('FORBIDDEN', 403)
        if g.current_user.get('password_change_required') and not own:
            return _failure('PASSWORD_CHANGE_REQUIRED', 403)
        password = data.get('password')
        # 3. 本人改密始终校验当前口令；管理员修改他人口令沿用重置语义。
        verified = None
        if password is not None and own:
            verified, error = _credentials_check(
                g.current_user['username'], data.get('old_password')
            )
            if error:
                _permission_log('本人改密的旧口令验证失败', level='WARNING', username=username)
                return error
        # 4. 事务内重新读取账号，检查并发变更并构造更新内容。
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
                if type(level) is not int or level not in (1, 2, 3, 4):
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
            if own and (
                meta.get('enabled') is False
                or updates.get('permission', row['permission']) != row['permission']
            ):
                return _failure('SELF_ADMIN_CHANGE_DENIED', 409)
            if 'new_username' in data and data['new_username'] != username:
                # 账号名保持不可变，避免改变稳定身份与审计墓碑的关联。
                return _failure('USERNAME_IMMUTABLE', 409)
            # 本人改密清除 first_login，管理员重置则要求目标用户再次改密。
            if password is not None:
                history = _history(row, state)
                security.validate_password(password, username, history)
                updates.update(
                    password=security.hash_password(password),
                    salt=secrets.token_hex(16),
                    first_login=0 if own else 1,
                    password_created_at=datetime.now(),
                    password_expire_at=datetime.now() + timedelta(days=180),
                    last_notify_at=None,
                )
                meta['history'] = json.dumps(history)
            elif 'first_login' in data:
                return _failure('PASSWORD_REQUIRED', 400)
            if not updates and not meta:
                raise ValueError('NO_FIELDS')
            if row['permission'] == 4 and (
                meta.get('enabled') is False or updates.get('permission', 4) != 4
            ):
                if _active_admins(conn) <= 1:
                    return _failure('LAST_ADMIN', 409)
            # 5. 写入业务表和账号状态，保留最后一个管理员等保护条件。
            if updates:
                clauses = ','.join(f'`{key}`=:{key}' for key in updates)
                conn.execute(
                    text(f'UPDATE `{config.PERM_TABLE}` SET {clauses} WHERE username=:name'),
                    dict(updates, name=username),
                )
            if meta:
                conn.execute(
                    security.ACCOUNT_STATE.update()
                    .where(security.ACCOUNT_STATE.c.username == username)
                    .values(**meta)
                )
            ids = revoke_user_sessions(conn, username)
            g.audit_before = before
            g.audit_after = _public(
                _account(conn, username), security.read_account_state(conn, username)
            )
        # 6. 提交后断开被撤销的会话，再沿用原有业务日志和审计事件分类。
        disconnect_revoked(ids)
        if password is not None:
            g.audit_event_type = 'account.password.change' if own else 'account.password.reset'
        elif 'enabled' in meta:
            g.audit_event_type = 'account.enable' if meta['enabled'] else 'account.disable'
        elif 'permission' in updates:
            g.audit_event_type = 'account.role.update'
        _audit('user update', True, username)
        _permission_log(
            '账号更新完成，会话已撤销',
            username=username,
            sessions_revoked=len(ids),
            password_changed=password is not None,
        )
        return jsonify(
            ok=True,
            username=username,
            updated_fields=list(updates) + list(meta),
            sessions_revoked=len(ids),
        )
    except ValueError as exc:
        return _failure(str(exc))


def _active_admins(conn):
    """统计未禁用的有效角色 4 账号，保留最后一个管理员的保护规则。"""
    users = (
        conn.execute(text(f'SELECT username FROM `{config.PERM_TABLE}` WHERE permission=4'))
        .scalars()
        .all()
    )
    return sum(
        security.account_state(conn, user)['enabled'] and not is_developer_account_disabled(user)
        for user in users
    )


# 删除账号
@permission_bp.route('/permission/delete', methods=['POST'])
def permission_delete():
    """删除账号并撤销其全部会话。

    请求示例：POST /permission/delete，JSON：{"username": "TEST1"}。
    禁止删除本人及最后一个有效管理员；账号状态保留为禁用墓碑。
    成功返回 {ok: true, deleted: 用户名, sessions_revoked: 数量}。
    """
    try:
        username = _name(_body().get('username'))
        _permission_log('开始删除账号', username=username)
        # 事务内校验本人/最后一个管理员保护，再删除并保留身份墓碑。
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
            conn.execute(
                text(f'DELETE FROM `{config.PERM_TABLE}` WHERE username=:name'), {'name': username}
            )
            conn.execute(
                security.ACCOUNT_STATE.update()
                .where(security.ACCOUNT_STATE.c.username == username)
                .values(enabled=False)
            )
            ids = revoke_user_sessions(conn, username)
        disconnect_revoked(ids)
        _audit('user delete', True, username)
        _permission_log('账号删除完成', username=username, sessions_revoked=len(ids))
        return jsonify(ok=True, deleted=username, sessions_revoked=len(ids))
    except ValueError as exc:
        return _failure(str(exc))


# 当前会话查询
@permission_bp.route("/permission/session", methods=["GET"])
def permission_session():
    """查询当前会话身份及状态，无需请求体。

    请求示例：GET /permission/session。
    返回 username、permission、uid、locked、password_change_required、csrf_token 等字段。
    前端刷新后可据 password_change_required 恢复强制改密页面。
    """
    # 高频会话查询不逐次打印 Token 或完整返回体。
    with config.engine.connect() as conn:
        maintenance = security.maintenance_state(conn)
    return jsonify(
        ok=True,
        username=g.current_user["username"],
        permission=g.current_user["permission"],
        csrf_token=g.csrf_token,
        uid=g.current_user.get('uid'),
        locked=g.session_locked,
        maintenance_until=maintenance['until'] if maintenance['active'] else None,
        password_change_required=g.current_user.get('password_change_required', False),
        idle_timeout_minutes=current_app.config['AUTH_IDLE_SECONDS'] / 60,
    )


# 退出登录与强制下线
@permission_bp.route("/permission/logout", methods=["POST"])
def permission_logout():
    """退出当前会话，或由管理员强制撤销指定账号的全部会话。

    普通退出：POST /permission/logout，JSON：{}。
    强制下线：JSON：{"force": true, "username": "TEST1"}。
    force 仅在严格为布尔 true 时进入管理员分支；其余行为保持原实现。
    """
    _permission_log('开始退出会话')
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return _failure('INVALID_JSON')
    # 管理员强制下线与本人退出保持原有的两个分支。
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
        _permission_log('指定账号已强制下线', username=user['username'], sessions_revoked=len(ids))
        return jsonify(ok=True, username=user['username'], sessions_revoked=len(ids))
    revoke_session(g.session_id)
    _permission_log('当前会话已退出')
    return jsonify(ok=True)


def _session_admin_allowed():
    """按现有 usermanage 权限表判断是否允许管理登录会话。"""
    return g.current_user["permission"] in config.PERMISSION_TABLE.get("usermanage", [])


# 登录会话列表查询
@permission_bp.route("/permission/sessions", methods=["GET"])
def permission_sessions():
    """查询当前登录会话列表，仅管理员可访问。

    请求示例：GET /permission/sessions。
    返回 {ok: true, sessions: [...]}；session_id 为管理用摘要，不是 Bearer Token。
    """
    _permission_log('开始查询登录会话列表')
    if not _session_admin_allowed():
        _permission_log('拒绝查询登录会话列表：需要管理员权限', level='WARNING')
        return jsonify(ok=False, error="Administrator permission required"), 403
    try:
        return jsonify(ok=True, sessions=list_login_sessions(g.session_id))
    except Exception:
        current_app.logger.exception("Failed to list login sessions")
        _permission_log('查询登录会话列表异常', level='ERROR')
        return jsonify(ok=False, error="Session store unavailable"), 503


# 撤销指定登录会话
@permission_bp.route("/permission/sessions/revoke", methods=["POST"])
def permission_revoke_session():
    """撤销指定登录会话，仅管理员可访问。

    请求示例：POST /permission/sessions/revoke。
    JSON：{"session_id": "<64 位小写十六进制会话摘要>"}。
    成功返回被撤销会话的信息；finally 中保留原有业务日志记录。
    """
    _permission_log('开始撤销指定登录会话')
    operator = g.current_user["username"]
    result = operationLog.OperationResult.FAIL
    remark = "Permission denied"
    try:
        if not _session_admin_allowed():
            return jsonify(ok=False, error="Administrator permission required"), 403
        data = request.get_json(silent=True)
        session_id = data.get("session_id") if isinstance(data, dict) else None
        if (
            not isinstance(session_id, str)
            or len(session_id) != 64
            or any(char not in "0123456789abcdef" for char in session_id)
        ):
            remark = "Invalid session_id"
            return (
                jsonify(
                    ok=False, error="session_id must be a 64-character lowercase SHA-256 hex digest"
                ),
                400,
            )
        remark = f"session_id={session_id}"
        # session_id 是管理用 SHA-256 摘要，不是客户端 Bearer Token。
        revoked = revoke_session_by_id(session_id)
        if revoked is None:
            return jsonify(ok=False, error="Session not found"), 404
        g.audit_target = revoked['username'] + ' / session:' + session_id
        result = operationLog.OperationResult.SUCCESS
        remark += f"; username={revoked['username']}"
        _permission_log('指定登录会话已撤销', username=revoked['username'])
        return jsonify(ok=True, **revoked)
    except Exception:
        current_app.logger.exception("Failed to revoke login session")
        _permission_log('撤销登录会话异常', level='ERROR')
        return jsonify(ok=False, error="Session store unavailable"), 503
    finally:
        # 保留原有成功/失败业务日志，不以 DPrint 替代。
        operationLog.enqueue_operation_log(
            operator, operationLog.OperationType.USER, "force logout session", 1, result, remark
        )


# 管理员重置账号口令
@permission_bp.route('/permission/reset-password', methods=['POST'])
def permission_reset_password():
    """管理员重置账号口令，临时口令通过设备本地凭据文件交付。

    请求示例：POST /permission/reset-password。
    JSON：{"username": "TEST1", "confirm": "RESET_PASSWORD"}。
    返回 delivery_id、delivery、first_login=1、expires_in=86400，不返回临时口令。
    重置后撤销目标账号会话；事务未提交时清理已创建的凭据文件。
    """
    from utils.security_files import private_directory, private_write, temporary_password

    receipt = None
    committed = False
    try:
        data = _body()
        username = _name(data.get('username'))
        _permission_log('开始重置账号口令', username=username)
        # 1. 显式确认后生成临时口令及本地交付标识。
        if data.get('confirm') != 'RESET_PASSWORD':
            return _failure('CONFIRMATION_REQUIRED', 409)
        password = temporary_password()
        encoded = security.hash_password(password)
        receipt_id = secrets.token_hex(16)
        receipt = private_directory('credentials') / (receipt_id + '.json')
        # 2. 事务内检查账号状态，将临时口令仅写入本地私有文件。
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
            private_write(
                receipt,
                json.dumps(
                    dict(
                        username=username,
                        temporary_password=password,
                        expires_at=time.time() + 86400,
                    ),
                    ensure_ascii=False,
                ).encode(),
            )
            conn.execute(
                text(
                    f'UPDATE `{config.PERM_TABLE}` SET password=:password,salt=:salt,first_login=1,'
                    'password_created_at=:created,password_expire_at=:expires WHERE username=:name'
                ),
                dict(
                    password=encoded,
                    salt=secrets.token_hex(16),
                    created=datetime.now(),
                    expires=datetime.now() + timedelta(days=1),
                    name=username,
                ),
            )
            conn.execute(
                security.ACCOUNT_STATE.update()
                .where(security.ACCOUNT_STATE.c.username == username)
                .values(history=json.dumps(_history(row, state)))
            )
            ids = revoke_user_sessions(conn, username)
        # 3. 提交成功后撤销会话，返回交付标识，不返回或打印临时口令。
        committed = True
        disconnect_revoked(ids)
        _audit('password reset', True, username)
        _permission_log(
            '口令重置完成，等待本地交付',
            username=username,
            sessions_revoked=len(ids),
            expires_in=86400,
        )
        return jsonify(
            ok=True,
            username=username,
            delivery_id=receipt_id,
            delivery='device-local-admin',
            first_login=1,
            expires_in=86400,
        )
    except ValueError as exc:
        return _failure(str(exc))
    finally:
        # 失败时沿用原有凭据文件清理条件，避免遗留未提交的交付内容。
        if receipt and receipt.exists() and not committed:
            receipt.unlink()


# 锁定当前会话
@permission_bp.route('/permission/lock', methods=['POST'])
def permission_lock():
    """锁定当前会话。

    请求示例：POST /permission/lock，JSON：{}。
    校验当前会话 CSRF Token 后写入会话锁，已锁定时不重复插入；成功返回 {ok, locked}。
    解锁使用 POST /permission/verify。
    """
    from routes.route_security import _require_write_csrf

    _permission_log('开始锁定当前会话')
    error = _require_write_csrf()
    if error:
        _permission_log('锁定会话被拒绝：CSRF 校验失败', level='WARNING')
        return error
    from utils.auth import _digest

    with config.engine.begin() as conn:
        security.lock_security(conn)
        sid = _digest(g.session_id)
        if not conn.execute(
            select(security.SESSION_LOCKS.c.sid).where(security.SESSION_LOCKS.c.sid == sid)
        ).first():
            conn.execute(security.SESSION_LOCKS.insert().values(sid=sid, locked_at=time.time()))
    _permission_log('当前会话已锁定')
    return jsonify(ok=True, locked=True)
