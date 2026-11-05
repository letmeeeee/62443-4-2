"""Security contracts use isolated SQLite, temporary files and mocked device services."""
import hashlib
import json
import sys
import time
from pathlib import Path

import pytest
from flask import jsonify, request
from sqlalchemy import select, text
from test_auth_session import auth_app, login
from utils import security_store as store
from utils.auth import LOGIN_SESSIONS


@pytest.fixture
def security_app(auth_app, tmp_path, monkeypatch):
    from routes.route_security import security_bp
    from utils.security_audit import init_security_http, query_records
    app, engine, log = auth_app
    # Keep test hashing fast while exercising the same PBKDF2 format/verifier.
    monkeypatch.setitem(store.PASSWORD_POLICY, 'iterations', 100000)
    config = sys.modules['config']
    config.INI_PATH = tmp_path / 'device.ini'
    config.INI_PATH.write_text('[SYSTEM]\nname=original\n')
    app.config.update(SECURITY_STATE_DIR=str(tmp_path / 'security'), MODBUS_CERT_DIR=str(tmp_path / 'certs'),
                      SECURITY_DEVICE_ID='test-device', TESTING=False)
    init_security_http(app)
    app.register_blueprint(security_bp)

    @app.route('/api/history/getOperationlog')
    def audit_query():
        try:
            return jsonify(query_records(request.args))
        except ValueError:
            return jsonify(code='INVALID_QUERY'), 400

    return auth_app


def post(client, path, credentials, body):
    return client.post(path, json=body, headers={'X-CSRF-Token':credentials['csrf_token']})


def query_range():
    return dict(beginDt='2000-01-01T00:00:00', endDt='2099-01-01T00:00:00', pageSize='100')


def test_policy_and_legacy_upgrade_never_expose_hashes(security_app):
    app, engine, _ = security_app
    client = app.test_client()
    credentials = login(client, 'admin').json
    assert client.get('/api/security/password-policy').json['min_length'] == 12
    result = post(client,'/permission/all',credentials,{})
    assert result.status_code == 200
    for user in result.json['data']:
        assert 'password' not in user and 'salt' not in user
        assert user['uid'] and 'enabled' in user
    with engine.connect() as conn:
        encoded = conn.execute(text("SELECT password FROM users WHERE username='admin'")).scalar()
        assert encoded.startswith('pbkdf2_sha256$')


def test_low_roles_cannot_manage_accounts_or_audit(security_app):
    app = security_app[0]
    client = app.test_client()
    credentials = login(client).json
    for path, body in [('/permission/add',dict(username='other',permission=4,password='NewGood!12345')),
                       ('/permission/delete',dict(username='admin')),
                       ('/permission/all',{}),
                       ('/permission/update',dict(username='admin',permission=1)),
                       ('/permission/update',dict(username='alice',permission=4))]:
        assert post(client,path,credentials,body).status_code == 403
    assert client.get('/api/history/getOperationlog',query_string=query_range()).status_code == 403
    assert client.get('/api/security/status').status_code == 403


def test_lockout_is_shared_and_source_cannot_be_forged(security_app):
    app = security_app[0]
    client = app.test_client()
    for number in range(5):
        result = client.post('/permission/login',json=dict(username='missing',password='wrong'),
                             environ_overrides={'REMOTE_ADDR':'192.0.2.20'}, headers={'X-Real-IP':str(number)})
        assert result.status_code == (429 if number == 4 else 401)
    locked = client.post('/permission/login',json=dict(username='alice',password='correct'),
                          environ_overrides={'REMOTE_ADDR':'192.0.2.20'})
    assert locked.status_code == 429 and locked.json['lock_seconds'] > 0
    assert locked.json['code'] == 'AUTH_LOCKED'


def test_account_lockout_uses_database_canonical_identity(security_app,monkeypatch):
    module=sys.modules['routes.route_permission']
    original=module._account
    # Simulate the deployed MySQL case-insensitive username collation.
    monkeypatch.setattr(module,'_account',lambda conn,name: original(conn,name.casefold()))
    client=security_app[0].test_client()
    for index,name in enumerate(('ALICE','Alice','aLiCe','ALIce','alice')):
        response=client.post('/permission/login',json=dict(username=name,password='wrong'),
                             environ_overrides={'REMOTE_ADDR':'192.0.2.'+str(index+1)})
    assert response.status_code==429 and response.json['code']=='AUTH_LOCKED'


def test_verify_requires_password_not_just_live_token(security_app):
    client = security_app[0].test_client()
    credentials = login(client).json
    assert post(client,'/permission/verify',credentials,dict(password='wrong')).status_code == 401
    assert post(client,'/permission/verify',credentials,dict(password='correct')).json['ok']
    assert client.post('/permission/verify',json=dict(password='correct')).status_code == 403


def test_server_lock_cannot_be_bypassed_by_removing_frontend_mask(security_app):
    client=security_app[0].test_client()
    credentials=login(client).json
    assert post(client,'/permission/lock',credentials,{}).json['locked']
    assert client.get('/g2').status_code==403
    assert client.get('/permission/session').json['locked']
    assert post(client,'/permission/verify',credentials,dict(password='wrong')).status_code==401
    assert client.get('/g2').status_code==403
    assert post(client,'/permission/verify',credentials,dict(password='correct')).json['ok']
    assert client.get('/g2').status_code==200


def test_idle_timeout_rejects_even_before_absolute_expiry(security_app):
    app, engine, _ = security_app
    client = app.test_client()
    credentials = login(client).json
    with engine.begin() as conn:
        conn.execute(store.SESSION_STATE.update().values(last_activity=time.time()-1000))
    assert credentials['expires_at'] > time.time()
    assert client.get('/permission/session').status_code == 401


def test_http_rate_limit_is_distinct_from_login_lockout(security_app):
    app=security_app[0]
    client=app.test_client()
    login(client)
    app.config['HTTP_REQUESTS_PER_MINUTE']=1
    response=client.get('/permission/session')
    assert response.status_code==429 and response.json['code']=='RATE_LIMITED'


def test_self_password_change_rejects_reuse_and_revokes_all_sessions(security_app):
    app = security_app[0]
    first, second = app.test_client(), app.test_client()
    credentials = login(first).json
    login(second)
    missing = post(first,'/permission/update',credentials,dict(username='alice',password='NewGood!123456'))
    assert missing.status_code == 401
    result = post(first,'/permission/update',credentials,
                  dict(username='alice',password='NewGood!123456',old_password='correct'))
    assert result.status_code == 200 and result.json['sessions_revoked'] == 2
    assert second.get('/permission/session').status_code == 401
    credentials = first.post('/permission/login',json=dict(username='alice',password='NewGood!123456')).json
    first.environ_base['HTTP_AUTHORIZATION'] = 'Bearer '+credentials['session_token']
    reuse = post(first,'/permission/update',credentials,
                 dict(username='alice',password='NewGood!123456',old_password='NewGood!123456'))
    assert reuse.status_code == 400 and reuse.json['code'] == 'PASSWORD_REUSED'


def test_disable_revokes_and_enable_does_not_restore_tokens(security_app):
    app = security_app[0]
    admin, user = app.test_client(), app.test_client()
    credentials = login(admin,'admin').json
    login(user)
    result = post(admin,'/permission/update',credentials,dict(username='alice',enabled=False))
    assert result.status_code == 200
    assert user.get('/permission/session').status_code == 401
    assert user.post('/permission/login',json=dict(username='alice',password='correct')).status_code == 401
    assert post(admin,'/permission/update',credentials,dict(username='alice',enabled=True)).status_code == 200
    assert user.get('/permission/session').status_code == 401
    assert post(admin,'/permission/delete',credentials,dict(username='admin')).status_code == 409


def test_notice_public_read_admin_write_and_version(security_app):
    app = security_app[0]
    anonymous = app.test_client()
    notice = anonymous.get('/permission/login-notice')
    assert notice.status_code == 200
    assert anonymous.post('/permission/login-notice',json={}).status_code == 401
    admin = app.test_client()
    credentials = login(admin,'admin').json
    updated = post(admin,'/permission/login-notice',credentials,dict(enabled=True,text='Authorized use only'))
    assert updated.json['version'] == notice.json['version']+1
    assert anonymous.get('/permission/login-notice').json['text'] == 'Authorized use only'


def test_reset_delivers_locally_not_through_api(security_app):
    app = security_app[0]
    admin, user = app.test_client(), app.test_client()
    credentials = login(admin,'admin').json
    login(user)
    result = post(admin,'/permission/reset-password',credentials,dict(username='alice',confirm='RESET_PASSWORD'))
    assert result.status_code == 200
    assert 'password' not in result.json and 'temporary_password' not in result.json
    path = Path(app.config['SECURITY_STATE_DIR'])/'credentials'/(result.json['delivery_id']+'.json')
    assert path.stat().st_mode & 0o777 == 0o600
    password = json.loads(path.read_text())['temporary_password']
    assert password not in result.get_data(as_text=True)
    assert user.get('/permission/session').status_code == 401
    result = user.post('/permission/login',json=dict(username='alice',password=password))
    assert result.status_code == 200 and result.json['first_login'] == 1
    user.environ_base['HTTP_AUTHORIZATION'] = 'Bearer '+result.json['session_token']
    assert user.get('/g2').status_code == 403


def test_audit_captures_source_tab_changes_and_export(security_app):
    app = security_app[0]
    admin = app.test_client()
    credentials = login(admin,'admin').json
    result = admin.post('/permission/update', json=dict(username='alice',enabled=False), headers={
        'X-CSRF-Token':credentials['csrf_token'],'X-Tab-Id':'test-tab','X-Real-IP':'192.0.2.5'})
    assert result.status_code == 200
    records = admin.get('/api/history/getOperationlog',query_string=query_range()).json['operationLogList']
    record = next(row for row in records if row['operation_target']=='/permission/update')
    assert record['source_ip']=='192.0.2.5' and record['tab_id']=='test-tab'
    assert record['operator']=='admin' and record['before_summary'] and record['after_summary']
    assert not {'password','salt'} & json.loads(record['before_summary']).keys()
    export = admin.get('/api/history/export',query_string=query_range())
    assert export.status_code == 200 and export.headers['X-Audit-Id']
    status = admin.get('/api/history/status').json
    assert status['eventCount'] > 0 and status['retentionDays']==180


@pytest.mark.parametrize('used,expected', [
    (0, None), (79999, None), (80000, 'AUDIT_CAPACITY_HIGH'),
    (94999, 'AUDIT_CAPACITY_HIGH'), (95000, 'AUDIT_CAPACITY_CRITICAL'),
    (100000, 'AUDIT_CAPACITY_CRITICAL'),
])
def test_audit_storage_thresholds_preserve_response_contract(security_app, monkeypatch, tmp_path, used, expected):
    from collections import namedtuple
    from utils import security_audit as audit
    from routes import route_security
    app = security_app[0]
    client = app.test_client()
    login(client, 'admin')
    disk_path = str(tmp_path / 'database')
    app.config.update(SECURITY_DISK_PATH=disk_path, AUDIT_CAPACITY_BYTES=1)
    # An obsolete nominal quota must not influence the result.
    usage = namedtuple('Usage', 'total used free')(100000, used, 100000-used)
    paths = []
    def disk_usage(path):
        paths.append(path)
        return usage
    monkeypatch.setattr(audit.shutil, 'disk_usage', disk_usage)
    monkeypatch.setattr(audit, '_failed', False)
    monkeypatch.setattr(route_security, '_command', lambda args: None)
    result = client.get('/api/history/status')
    assert result.status_code == 200
    state = result.json
    assert set(state) == {'ok', 'usagePercent', 'retentionDays', 'totalBytes', 'usedBytes',
                          'writeFailed', 'eventCount', 'retentionScope', 'legacyRetentionManaged',
                          'capacityExceeded', 'writeFailureScope'}
    assert state['totalBytes'] == 100000 and state['usedBytes'] == used
    assert state['usagePercent'] == round(used/1000, 2)
    assert state['capacityExceeded'] == (used == 100000)
    assert not state['writeFailed']
    response = client.get('/api/security/status')
    assert response.status_code == 200
    alerts = [item for item in response.json['alerts'] if item['source'] == 'audit']
    assert alerts == ([dict(code=expected, source='audit')] if expected else [])
    assert paths and all(path == disk_path for path in paths)


def test_audit_write_fault_is_independent_and_not_cleared_by_reads(security_app, monkeypatch):
    from collections import namedtuple
    from utils import security_audit as audit
    from routes import route_security
    app = security_app[0]
    client = app.test_client()
    login(client, 'admin')
    usage_type = namedtuple('Usage', 'total used free')
    monkeypatch.setattr(audit, '_failed', False)
    monkeypatch.setattr(route_security, '_command', lambda args: None)
    original_engine = audit.engine
    def unavailable():
        raise RuntimeError('Simulated audit database failure')
    monkeypatch.setattr(audit, 'engine', unavailable)
    with app.test_request_context('/audit-test'):
        assert audit.record_event('test', 'test', True) is None
    monkeypatch.setattr(audit, 'engine', original_engine)
    assert audit._failure_marker.exists()
    # A restarted worker still observes the persistent latch after DB recovery.
    monkeypatch.setattr(audit, '_failed', False)
    for used, capacity_code in ((20000, None), (80000, 'AUDIT_CAPACITY_HIGH'),
                                (95000, 'AUDIT_CAPACITY_CRITICAL')):
        monkeypatch.setattr(audit.shutil, 'disk_usage', lambda path: usage_type(100000, used, 100000-used))
        state = client.get('/api/history/status').json
        assert state['writeFailed']
        alerts = client.get('/api/security/status').json['alerts']
        audit_codes = {item['code'] for item in alerts if item['source'] == 'audit'}
        assert audit_codes == {'AUDIT_WRITE_FAILED'} | ({capacity_code} if capacity_code else set())
    assert audit._failure_marker.exists()


def test_audit_storage_read_failure_is_not_reported_as_empty_disk(security_app, monkeypatch):
    from utils import security_audit as audit
    from routes import route_security
    client = security_app[0].test_client()
    login(client, 'admin')
    def unavailable(path):
        raise OSError('Storage unavailable')
    monkeypatch.setattr(audit.shutil, 'disk_usage', unavailable)
    monkeypatch.setattr(route_security, '_command', lambda args: None)
    assert client.get('/api/history/status').status_code == 500
    status = client.get('/api/security/status').json
    assert status['checks']['audit'] == dict(available=False, reason='COLLECTION_FAILED')
    monkeypatch.setattr(audit, '_failed', True)
    status = client.get('/api/security/status').json
    assert dict(code='AUDIT_WRITE_FAILED', source='audit') in status['alerts']


def test_backup_tamper_compatibility_and_default_no_destructive_execution(security_app):
    app = security_app[0]
    admin = app.test_client()
    credentials = login(admin,'admin').json
    backup = post(admin,'/api/security/backups',credentials,{}).json
    identifier = backup['id']
    path = Path(app.config['SECURITY_STATE_DIR'])/'backups'/(identifier+'.lcb')
    assert b'correct' not in path.read_bytes() and b'users' not in path.read_bytes()
    validation = post(admin,f'/api/security/backups/{identifier}/validate',credentials,dict(sha256=backup['sha256']))
    assert validation.status_code==200 and validation.json['compatible']
    preview = post(admin,f'/api/security/backups/{identifier}/restore',credentials,{})
    assert preview.json['dry_run'] and not preview.json['executionEnabled']
    execute = post(admin,f'/api/security/backups/{identifier}/restore',credentials,
        dict(dry_run=False,confirm='RESTORE_BACKUP',password='correct',sha256=backup['sha256']))
    assert execute.status_code==400
    original = path.read_bytes()
    path.write_bytes(original[:-1]+bytes([original[-1]^1]))
    assert post(admin,f'/api/security/backups/{identifier}/validate',credentials,{}).status_code==400


def test_enabled_restore_restores_data_and_revokes_tokens(security_app):
    app, engine, _ = security_app
    admin = app.test_client()
    credentials = login(admin,'admin').json
    backup = post(admin,'/api/security/backups',credentials,{}).json
    sys.modules['config'].INI_PATH.write_text('[SYSTEM]\nname=changed\n')
    app.config['SECURITY_ALLOW_DESTRUCTIVE']=True
    entered=post(admin,'/api/security/maintenance',credentials,
        dict(enabled=True,seconds=900,confirm='ENTER_MAINTENANCE',password='correct'))
    assert entered.status_code==200 and entered.json['active']
    restored = post(admin,f"/api/security/backups/{backup['id']}/restore",credentials,
        dict(dry_run=False,confirm='RESTORE_BACKUP',password='correct',sha256=backup['sha256']))
    assert restored.status_code==200
    assert 'original' in sys.modules['config'].INI_PATH.read_text()
    assert admin.get('/permission/session').status_code==401
    assert not (Path(app.config['SECURITY_STATE_DIR'])/'recovery'/'pending.json').exists()


def test_factory_requires_provisioned_baseline_and_decommission_preview_is_explicit(security_app):
    client = security_app[0].test_client()
    credentials = login(client,'admin').json
    factory = post(client,'/api/security/factory-reset',credentials,{})
    assert factory.status_code==409 and factory.json['code']=='FACTORY_BASELINE_NOT_CONFIGURED'
    plan = post(client,'/api/security/decommission',credentials,{})
    assert plan.json['dry_run'] and not plan.json['plan']['completeDeviceErasure']
    assert client.get('/permission/session').status_code==200


def test_legacy_sql_is_disabled_and_protocol_input_is_bounded(security_app):
    app = security_app[0]
    app.add_url_rule('/api','legacy',lambda: jsonify(ok=True),methods=['GET','POST'])
    client = app.test_client()
    credentials = login(client).json
    assert client.get('/api?sql=SELECT+1&params=root').status_code==410
    assert post(client,'/api',credentials,dict(deviceid='1',functioncode='6',Address='1',Quantity='1',value='5')).status_code==403
    assert post(client,'/api',credentials,dict(deviceid='1',functioncode='06',Address='1',Quantity='1',value='5')).status_code==403
    assert post(client,'/api',credentials,dict(deviceid='1,2',functioncode='3',Address='1',Quantity='1')).status_code==400


def test_errors_do_not_leak_internal_details(security_app):
    app = security_app[0]
    @app.route('/failure')
    def failure():
        raise RuntimeError('SELECT secret FROM /private/path')
    client = app.test_client()
    login(client)
    response=client.get('/failure')
    assert response.status_code==500 and response.json['trace_id']
    assert '/private/path' not in response.get_data(as_text=True)


def test_legacy_audit_records_remain_readable(security_app):
    app,engine,_=security_app
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE operation_log (log_id INTEGER, operation_time DATETIME, '
            'operator TEXT, operation_type TEXT, operation_target TEXT, sort INTEGER, result INTEGER, remark TEXT)'))
        conn.execute(text("INSERT INTO operation_log VALUES (1,'2026-11-03 10:00:00','legacy',"
            "'system.control','LC',1,1,'historical record')"))
    client=app.test_client()
    login(client,'admin')
    result=client.get('/api/history/getOperationlog',query_string=query_range())
    assert result.status_code==200
    old=next(row for row in result.json['operationLogList'] if row['operator']=='legacy')
    assert old['remark']=='historical record' and old['source_ip'] is None


def test_restore_commit_failure_rolls_back_database_and_configuration(security_app):
    from sqlalchemy import event
    app,engine,_=security_app
    client=app.test_client()
    credentials=login(client,'admin').json
    backup=post(client,'/api/security/backups',credentials,{}).json
    ini=sys.modules['config'].INI_PATH
    ini.write_text('[SYSTEM]\nname=current\n')
    app.config['SECURITY_ALLOW_DESTRUCTIVE']=True
    post(client,'/api/security/maintenance',credentials,
         dict(enabled=True,confirm='ENTER_MAINTENANCE',password='correct'))
    state=dict(armed=False,fired=False)
    def arm(connection,cursor,statement,parameters,context,executemany):
        if statement.startswith('INSERT INTO users'):
            state['armed']=True
    def fail_commit(connection):
        if state['armed'] and not state['fired']:
            state['fired']=True
            raise RuntimeError('simulated commit failure')
    event.listen(engine,'before_cursor_execute',arm)
    event.listen(engine,'commit',fail_commit)
    try:
        response=post(client,f"/api/security/backups/{backup['id']}/restore",credentials,
            dict(dry_run=False,confirm='RESTORE_BACKUP',password='correct',sha256=backup['sha256']))
    finally:
        event.remove(engine,'before_cursor_execute',arm)
        event.remove(engine,'commit',fail_commit)
    assert state['fired'] and response.status_code==500
    assert 'current' in ini.read_text()
    with engine.connect() as conn:
        assert conn.execute(text('SELECT COUNT(*) FROM users')).scalar()==2
    assert client.get('/permission/session').status_code==200


def test_config_rejects_invalid_values_and_unfinished_restore(tmp_path,monkeypatch):
    from script.security_config import configure_security
    from flask import Flask
    app=Flask(__name__)
    path=tmp_path/'security.json'
    monkeypatch.setenv('SECURITY_CONFIG_FILE',str(path))
    path.write_text(json.dumps(dict(SECURITY_ALLOW_DESTRUCTIVE='true')))
    with pytest.raises(ValueError):
        configure_security(app)
    root=tmp_path/'security'
    (root/'recovery').mkdir(parents=True)
    (root/'recovery'/'pending.json').write_text('{}')
    path.write_text(json.dumps(dict(SECURITY_STATE_DIR=str(root))))
    with pytest.raises(RuntimeError,match='Pending security restore'):
        configure_security(app)


def test_admin_force_logout_revokes_all_target_sessions(security_app):
    app=security_app[0]
    admin,first,second=(app.test_client() for _ in range(3))
    credentials=login(admin,'admin').json
    login(first)
    login(second)
    result=post(admin,'/permission/logout',credentials,dict(force=True,username='alice'))
    assert result.status_code==200 and result.json['sessions_revoked']==2
    assert first.get('/permission/session').status_code==401
    assert second.get('/permission/session').status_code==401
    assert admin.get('/permission/session').status_code==200


def test_structured_certificate_list_and_backup_download(security_app,tmp_path):
    from datetime import datetime,timedelta
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    app=security_app[0]
    directory=Path(app.config['MODBUS_CERT_DIR'])
    directory.mkdir()
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'test')])
    certificate=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(1).not_valid_before(datetime.utcnow()-timedelta(days=1))
        .not_valid_after(datetime.utcnow()+timedelta(days=10)).sign(key,hashes.SHA256()))
    (directory/'master.crt').write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    client=app.test_client()
    credentials=login(client,'admin').json
    result=client.get('/api/security/certificates')
    assert result.status_code==200 and result.json['expiringCount']==1
    assert not result.json['data'][0]['validityOnly']
    assert not result.json['data'][0]['chainVerified']  # Unissued legacy identity is not trusted.
    assert len(result.json['data'][0]['keyId'])==64
    backup=post(client,'/api/security/backups',credentials,{}).json
    downloaded=client.get(f"/api/security/backups/{backup['id']}/download")
    assert downloaded.status_code==200
    assert hashlib.sha256(downloaded.data).hexdigest()==backup['sha256']
    assert b'PRIVATE KEY' not in downloaded.data


def test_runtime_manifest_does_not_export_arbitrary_secrets(security_app,tmp_path):
    app=security_app[0]
    manifest=tmp_path/'components.json'
    manifest.write_text(json.dumps([dict(name='controller',version='1',password='do-not-export')]))
    app.config['COMPONENT_MANIFEST']=str(manifest)
    client=app.test_client()
    login(client)
    result=client.get('/api/system/components')
    assert result.status_code==200 and 'do-not-export' not in result.get_data(as_text=True)


def test_application_decommission_preserves_business_data_and_audit(security_app):
    from utils.security_audit import EVENTS
    app,engine,_=security_app
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE business_history (value INTEGER)'))
        conn.execute(text('INSERT INTO business_history VALUES (42)'))
    client=app.test_client()
    credentials=login(client,'admin').json
    backup=post(client,'/api/security/backups',credentials,{}).json
    app.config['SECURITY_ALLOW_DESTRUCTIVE']=True
    entered=post(client,'/api/security/maintenance',credentials,
        dict(enabled=True,confirm='ENTER_MAINTENANCE',password='correct'))
    assert entered.status_code==200
    result=post(client,'/api/security/decommission',credentials,
        dict(dry_run=False,scope='application-identities',confirm='DECOMMISSION_APPLICATION',password='correct'))
    assert result.status_code==200 and result.json['ok']
    assert not result.json['plan']['completeDeviceErasure']
    assert sys.modules['config'].INI_PATH.exists()
    assert not (Path(app.config['SECURITY_STATE_DIR'])/'backups'/(backup['id']+'.lcb')).exists()
    with engine.connect() as conn:
        assert conn.execute(text('SELECT COUNT(*) FROM users')).scalar()==0
        assert conn.execute(text('SELECT value FROM business_history')).scalar()==42
        assert conn.execute(select(EVENTS)).first() is not None
    assert client.get('/permission/session').status_code==401
