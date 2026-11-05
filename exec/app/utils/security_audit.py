"""Structured request audit, with read-only union of legacy operation records."""
import csv
import hashlib
import io
import json
import shutil
import threading
import time
import uuid
from datetime import datetime, timedelta

from flask import g, request, jsonify, current_app, Response
from sqlalchemy import (Column, DateTime, Integer, MetaData, String, Table, Text,
                        select, func, inspect, literal, union_all)
from werkzeug.exceptions import HTTPException

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
    values = dict(log_id=identifier, operation_time=datetime.now(),
        operator=user.get('username', '-'), uid=user.get('uid'), operation_type=kind,
        operation_target=target[:160], sort=1, result=int(bool(result)), remark=remark[:4096],
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
        return None


def _records(conn):
    columns = [column.name for column in EVENTS.columns]
    sources = [select(*[EVENTS.c[name] for name in columns])]
    if inspect(conn).has_table('operation_log'):
        old = Table('operation_log', MetaData(), autoload_with=conn)
        sources.append(select(*[(old.c[name] if name in old.c else literal(None)).label(name)
                                for name in columns]))
    return union_all(*sources).subquery()


def query_records(args, export=False):
    begin = datetime.fromisoformat(args.get('beginDt', '').replace('T', ' '))
    end = datetime.fromisoformat(args.get('endDt', '').replace('T', ' '))
    if begin.tzinfo or end.tzinfo or begin > end:
        raise ValueError('INVALID_TIME_RANGE')
    page = int(args.get('pageNum', 1))
    size = int(args.get('pageSize', 20))
    if page < 1 or not 1 <= size <= 500:
        raise ValueError('INVALID_PAGINATION')
    with engine().connect() as conn:
        rows = _records(conn)
        filters = [rows.c.operation_time >= begin, rows.c.operation_time <= end]
        if args.get('operator'):
            filters.append(rows.c.operator == args['operator'])
        if args.get('result') not in (None, ''):
            result = int(args['result'])
            if result not in (0, 1):
                raise ValueError('INVALID_RESULT')
            filters.append(rows.c.result == result)
        if args.get('operationType'):
            from utils.operationLog import OP_NUM_MAP
            value = OP_NUM_MAP.get(int(args['operationType']))
            if value is None:
                raise ValueError('INVALID_OPERATION_TYPE')
            filters.append(rows.c.operation_type == value.value)
        if args.get('operationTarget'):
            # Preserve the legacy device-id filter contract.
            from utils.ini import find_device
            device = find_device(int(args['operationTarget']))
            if not device:
                raise ValueError('INVALID_DEVICE')
            filters += [rows.c.operation_target == device['name'], rows.c.sort == device['sort']]
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
    result = query_records(request.args, export=True)
    # Persist export audit before releasing records; do not export if recording fails.
    event = record_event('audit.export', '/api/history/export', True,
        json.dumps(dict(filters=dict(request.args), rows=len(result['operationLogList'])), ensure_ascii=False))
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
                kind = 'systemMg.user.title' if request.path.startswith('/permission/') else 'menu.parameterSetting'
                event = record_event(kind, request.path, response.status_code < 400,
                    'HTTP '+str(response.status_code), getattr(g,'audit_before',None), getattr(g,'audit_after',None))
                if event:
                    response.headers['X-Audit-Id'] = event
                else:
                    response.headers['X-Audit-Write-Failed'] = 'true'
        return response
