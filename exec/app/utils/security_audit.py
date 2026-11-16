"""Security audit records, queried separately from business operation logs."""
import csv
import hashlib
import io
import json
import re
import shutil
import threading
import time
import traceback
import uuid
from datetime import datetime, timedelta

from flask import g, request, jsonify, current_app, Response, abort
from sqlalchemy import (Column, DateTime, Integer, MetaData, String, Table, Text,
                        select, func, inspect, literal, false)
from werkzeug.exceptions import HTTPException
from utils.utils import DPrint

metadata = MetaData()
EVENTS = Table('security_audit', metadata,
    Column('log_id', String(36), primary_key=True),
    Column('operation_time', DateTime, nullable=False, index=True),
    Column('operator', String(64), nullable=False), Column('uid', String(36)),
    Column('operation_type', String(64), nullable=False),
    Column('operation_target', String(160), nullable=False),
    Column('sort', Integer, nullable=False), Column('result', Integer, nullable=False),
    Column('remark', Text, nullable=False), Column('source_ip', String(64)),
    Column('session_id', String(64)), Column('tab_id', String(64)),
    Column('before_summary', Text), Column('after_summary', Text),
    Column('trace_id', String(36)), mysql_engine='InnoDB', mysql_charset='utf8mb4')
_failed = False
_failure_lock = threading.Lock()
_failure_marker = None


def mark_write_failed():
    """Latch failures across threads/workers and restarts when local storage permits."""
    global _failed
    with _failure_lock:
        _failed = True
    if _failure_marker is not None:
        try:
            from utils.security_files import private_write
            private_write(_failure_marker, b'Audit write failure; investigate before clearing locally.\n')
        except (OSError, ValueError):
            pass


def engine():
    import config
    return config.engine


def record_event(kind, target, result, remark='', before=None, after=None):
    global _failed
    from utils.auth import validated_tab_id
    from utils.security_store import source_ip
    user = getattr(g, 'current_user', {})
    token = getattr(g, 'session_id', '')
    identifier = str(uuid.uuid4())
    g.audit_target = target
    # Keep route diagnostics in the remark, never use a route as the business object.
    # Deliberately exclude query strings and request bodies (passwords/tokens).
    detail = request.method + ' ' + request.path
    if remark:
        detail += '; ' + remark
    values = dict(log_id=identifier, operation_time=datetime.now(),
        operator=user.get('username', '-'), uid=user.get('uid'), operation_type=kind,
        operation_target=target[:160], sort=1, result=int(bool(result)), remark=detail[:4096],
        source_ip=source_ip(), session_id=hashlib.sha256(token.encode()).hexdigest() if token else None,
        tab_id=validated_tab_id(), before_summary=json.dumps(before, ensure_ascii=False) if before else None,
        after_summary=json.dumps(after, ensure_ascii=False) if after else None,
        trace_id=getattr(g, 'trace_id', None))
    try:
        with engine().begin() as conn:
            conn.execute(EVENTS.insert().values(**values))
            # Separate policy applies to this new journal; legacy data is never silently deleted.
            conn.execute(EVENTS.delete().where(EVENTS.c.operation_time < datetime.now() -
                timedelta(days=current_app.config.get('AUDIT_RETENTION_DAYS', 180))))
        return identifier
    except Exception:
        mark_write_failed()
        current_app.logger.exception('Security audit write failed')
        DPrint(
            f'Security audit write failed; trace_id={getattr(g, "trace_id", None)}\n'
            f'{traceback.format_exc()}',
            level='ERROR',
        )
        return None


def _records(conn, business=False):
    if not business:
        return select(EVENTS).subquery()
    if inspect(conn).has_table('operation_log'):
        old = Table('operation_log', MetaData(), autoload_with=conn)
        return select(old).subquery()
    names = ('log_id', 'operation_time', 'operator', 'operation_type',
             'operation_target', 'sort', 'result', 'remark')
    return select(*[literal(None).label(name) for name in names]).where(false()).subquery()


def query_records(args, export=False, *, business=False):
    if not business:
        from utils.access import allowed
        if not allowed('audit:read'):
            abort(403)
    begin = datetime.fromisoformat(args.get('beginDt', '').replace('T', ' '))
    end = datetime.fromisoformat(args.get('endDt', '').replace('T', ' '))
    if begin.tzinfo or end.tzinfo or begin > end:
        raise ValueError('INVALID_TIME_RANGE')
    page = int(args.get('pageNum', 1))
    size = int(args.get('pageSize', 20))
    if page < 1 or not 1 <= size <= 500:
        raise ValueError('INVALID_PAGINATION')
    with engine().connect() as conn:
        rows = _records(conn, business=business)
        filters = [rows.c.operation_time >= begin, rows.c.operation_time <= end]
        if args.get('operator'):
            filters.append(rows.c.operator == args['operator'])
        if args.get('result') not in (None, ''):
            result = int(args['result'])
            if result not in (0, 1):
                raise ValueError('INVALID_RESULT')
            filters.append(rows.c.result == result)
        if args.get('operationType'):
            value = args['operationType']
            if business or value.isdigit():
                # Numeric selectors retain their meaning for legacy records.
                from utils.operationLog import OP_NUM_MAP
                kind = OP_NUM_MAP.get(int(value))
                if kind is None:
                    raise ValueError('INVALID_OPERATION_TYPE')
                value = kind.value
            elif not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_.-]{0,63}', value):
                raise ValueError('INVALID_OPERATION_TYPE')
            filters.append(rows.c.operation_type == value)
        if args.get('operationTarget'):
            if business:
                # Only the business log retains the legacy device-id selector.
                from utils.ini import find_device
                device = find_device(int(args['operationTarget']))
                if not device:
                    raise ValueError('INVALID_DEVICE')
                filters += [rows.c.operation_target == device['name'], rows.c.sort == device['sort']]
            else:
                target = args['operationTarget']
                if len(target) > 160:
                    raise ValueError('INVALID_OPERATION_TARGET')
                filters.append(rows.c.operation_target == target)
        count = conn.execute(select(func.count()).select_from(rows).where(*filters)).scalar_one()
        if export and count > 10000:
            raise ValueError('EXPORT_LIMIT_EXCEEDED')
        result = conn.execute(select(rows).where(*filters).order_by(
            rows.c.operation_time.desc(), rows.c.log_id.desc()).offset(0 if export else (page-1)*size)
            .limit(10000 if export else size)).mappings().all()
    data = []
    for row in result:
        item = dict(row)
        item['operation_time'] = item['operation_time'].isoformat(sep=' ')
        item['log_id'] = str(item['log_id'])
        data.append(item)
    return dict(total=count, pageNum=page, pageSize=size, operationLogList=data)


def export_records():
    from utils.access import allowed
    if not allowed('audit:export'):
        abort(403)
    result = query_records(request.args, export=True)
    # Persist export audit before releasing records; do not export if recording fails.
    fields = ('beginDt', 'endDt', 'operator', 'result', 'operationType', 'operationTarget')
    event = record_event('audit.export', '安全审计记录', True,
        json.dumps(dict(filters={key: request.args[key] for key in fields if key in request.args},
                        rows=len(result['operationLogList'])), ensure_ascii=False))
    if not event:
        return jsonify(ok=False, code='AUDIT_UNAVAILABLE', message='Audit service unavailable'), 503
    g.audit_export_recorded = True
    output = io.StringIO()
    fields = [c.name for c in EVENTS.columns]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in result['operationLogList']:
        # Prevent spreadsheet formula execution in downloaded CSV.
        safe = {key: ("'"+value if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')) else value)
                for key, value in row.items()}
        writer.writerow(safe)
    return Response('\ufeff'+output.getvalue(), mimetype='text/csv', headers={
        'Content-Disposition':'attachment; filename="audit.csv"', 'X-Audit-Id':event})


def write_failed():
    return _failed or bool(_failure_marker and _failure_marker.exists())


def status():
    # Monitor the filesystem that stores the database, not a nominal table quota.
    usage = shutil.disk_usage(current_app.config.get('SECURITY_DISK_PATH', '/'))
    if usage.total <= 0:
        raise ValueError('Storage capacity unavailable')
    with engine().connect() as conn:
        count = conn.execute(select(func.count()).select_from(EVENTS)).scalar_one()
    return dict(usagePercent=round(usage.used*100/usage.total, 2), retentionDays=current_app.config.get('AUDIT_RETENTION_DAYS',180),
        totalBytes=usage.total, usedBytes=usage.used, writeFailed=write_failed(), eventCount=count,
        retentionScope='security_audit', legacyRetentionManaged=False,
        capacityExceeded=usage.used >= usage.total, writeFailureScope='process-and-local-persistent-latch')


def capacity_alert(state):
    """Use byte counts so display rounding cannot trigger an early warning."""
    if state['usedBytes'] * 100 >= state['totalBytes'] * 95:
        return 'AUDIT_CAPACITY_CRITICAL'
    if state['usedBytes'] * 100 >= state['totalBytes'] * 80:
        return 'AUDIT_CAPACITY_HIGH'
    return None


# These describe server-side resources, not client-supplied display labels.
REQUEST_EVENTS = {
    '/permission/login': ('authentication.login', '待核验账号'),
    '/permission/verify': ('session.unlock', '当前登录会话'),
    '/permission/lock': ('session.lock', '当前登录会话'),
    '/permission/logout': ('session.logout', '当前登录会话'),
    '/permission/add': ('account.create', '未确认的目标账号'),
    '/permission/update': ('account.update', '未确认的目标账号'),
    '/permission/delete': ('account.delete', '未确认的目标账号'),
    '/permission/reset-password': ('account.password.reset', '未确认的目标账号'),
    '/permission/all': ('account.query', 'Web账号列表'),
    '/permission/sessions/revoke': ('session.revoke', '未确认的目标会话'),
    '/permission/login-notice': ('security.notice.update', '登录使用提示'),
    '/api/security/maintenance': ('security.maintenance.update', '应用维护模式'),
    '/api/security/roles': ('security.roles.query', 'Web角色权限'),
    '/api/system/ssh': ('system.ssh.update', 'SSH服务'),
    '/api/system/ssh/status': ('system.ssh.query', 'SSH服务'),
    '/ini/update': ('configuration.update', '设备INI配置'),
    '/ini/all': ('configuration.query', '设备INI配置'),
    '/ini/system_counts': ('configuration.update', '设备数量配置'),
    '/network/set_ip': ('network.address.update', '设备网络地址配置'),
    '/system/reboot': ('system.reboot', '本机设备'),
    '/status/update': ('device.control', '设备控制状态'),
    '/api': ('device.protocol.request', '设备寄存器（目标未确认）'),
    '/api/paraConfig/modifyParams': ('parameter.update', '设备参数（目标未确认）'),
    '/api/data/testMode': ('system.test-mode.update', '业务数据测试模式'),
    '/api/security/backups': ('backup.create', '应用安全备份'),
    '/api/security/factory-reset': ('factory.reset', '应用安全配置'),
    '/api/security/decommission': ('decommission', 'application-identities'),
    '/api/cert/ca/import': ('certificate.trust.import', 'CA根信任'),
    '/api/cert/https/csr': ('certificate.csr.create', 'HTTPS设备身份'),
    '/api/cert/https/identity/import': ('certificate.identity.import', 'HTTPS设备身份'),
    '/api/cert/https/apply': ('certificate.identity.apply', '证书及CRL关联服务'),
    '/api/cert/crls/import': ('certificate.crl.import', 'CA证书吊销列表'),
    '/api/cert/csr': ('certificate.csr.create', 'Modbus设备身份（角色未确认）'),
    '/api/cert/identity/import': ('certificate.identity.import', 'Modbus设备身份（角色未确认）'),
    '/api/security/certificates/import': ('certificate.identity.import', 'Modbus设备身份（角色未确认）'),
    '/api/security/certificates/verify': ('certificate.verify', 'Modbus设备身份（角色未确认）'),
    '/api/upgrade/file': ('upgrade.upload', '应用升级包'),
    '/api/upgrade/start': ('upgrade.start', '应用升级任务'),
    '/api/upgrade/startRollback': ('upgrade.rollback', '应用版本回退任务'),
    '/api/history/getSecurityAudit': ('audit.query', '安全审计记录'),
    '/api/history/export': ('audit.export', '安全审计记录'),
    '/api/history/status': ('audit.status', '安全审计状态'),
    '/api/history/getOperationlog': ('business-log.query', '业务操作日志'),
}


def request_event():
    kind, target = REQUEST_EVENTS.get(request.path, ('http.request', '未确认的业务对象'))
    if request.endpoint is None:
        return 'http.request', '未确认的业务对象'
    if request.method in ('GET', 'HEAD'):
        kind = {
            '/api/security/backups': 'backup.query',
            '/api/security/maintenance': 'security.maintenance.query',
            '/permission/login-notice': 'security.notice.query',
            '/ini/system_counts': 'configuration.query',
        }.get(request.path, kind)
    # The route converter validates the identifier shape; file validity is checked by the handler.
    if request.endpoint and request.endpoint.startswith('security.backup_'):
        action = request.endpoint.split('security.backup_', 1)[1]
        if action in ('download', 'validate', 'restore'):
            kind = 'backup.' + action
            if not getattr(g, 'audit_target', None):
                identifier = (request.view_args or {}).get('identifier', '')
                if re.fullmatch(r'[0-9a-f]{32}', identifier):
                    target = '备份编号（待核验）:' + identifier
    if request.path == '/permission/login' and getattr(g, 'current_user', None):
        target = g.current_user['username']
    return getattr(g, 'audit_event_type', kind), getattr(g, 'audit_target', target)


def init_security_http(app):
    global _failure_marker
    from utils.security_files import private_directory
    with app.app_context():
        _failure_marker = private_directory('health') / 'audit-write-failed'
    with engine().begin() as conn:
        metadata.create_all(conn)

    @app.before_request
    def trace_request():
        g.trace_id = str(uuid.uuid4())

    @app.errorhandler(Exception)
    def handle_error(exc):
        if isinstance(exc, HTTPException):
            return jsonify(ok=False, code='HTTP_'+str(exc.code), message=exc.name), exc.code
        app.logger.exception('Request failed')
        DPrint(
            f'Request failed; trace_id={getattr(g, "trace_id", None)}\n{traceback.format_exc()}',
            level='ERROR',
        )
        return jsonify(ok=False, code='INTERNAL_ERROR', message='Service temporarily unavailable'), 500

    @app.after_request
    def normalize_and_audit(response):
        if request.endpoint in ('static','serve_spa'):
            return response
        trace = getattr(g, 'trace_id', None) or str(uuid.uuid4())
        g.trace_id = trace
        response.headers['X-Trace-Id'] = trace
        if response.status_code >= 400:
            data = response.get_json(silent=True)
            data = data if isinstance(data, dict) else {}
            code = data.get('code')
            if not isinstance(code, str):
                code = {400:'INVALID_REQUEST',401:'SESSION_INVALID',403:'FORBIDDEN',404:'NOT_FOUND',
                        409:'CONFLICT',429:'RATE_LIMITED',503:'SERVICE_UNAVAILABLE'}.get(response.status_code,'INTERNAL_ERROR')
            safe = dict(ok=False, code=code, trace_id=trace,
                        message=code if response.status_code < 500 else 'Service temporarily unavailable')
            for key in ('lock_seconds','attempts_remaining','loginSessions'):
                if key in data:
                    safe[key] = data[key]
            response.set_data(app.json.dumps(safe))
            response.content_type = 'application/json'
        if request.method not in ('GET','HEAD','OPTIONS') or response.status_code >= 400:
            if not getattr(g, 'audit_export_recorded', False):
                kind, target = request_event()
                detail = 'HTTP ' + str(response.status_code)
                if response.status_code >= 400:
                    detail += '; ' + safe['code']
                event = record_event(kind, target, response.status_code < 400,
                    detail, getattr(g,'audit_before',None), getattr(g,'audit_after',None))
                if event:
                    response.headers['X-Audit-Id'] = event
                else:
                    response.headers['X-Audit-Write-Failed'] = 'true'
        return response
