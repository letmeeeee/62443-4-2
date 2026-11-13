"""11-10 联调缺陷回归：使用临时文件、SQLite 和设备替身，无实机写操作。"""
import ast
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Blueprint, Flask, g, jsonify, request

from test_security_center import security_app, post
from test_auth_session import auth_app, login


@pytest.mark.parametrize('path,body', [
    ('/permission/login-notice', {'enabled': True, 'text': 'Changed'}),
    ('/permission/lock', {}),
    ('/api/security/backups', {}),
    ('/api/security/backups/' + '0' * 32 + '/validate', {}),
    ('/api/security/factory-reset', {'dry_run': True}),
])
@pytest.mark.parametrize('token', [None, 'WRONG-TOKEN'])
def test_reported_writes_require_csrf_even_for_same_origin(security_app, path, body, token):
    client = security_app[0].test_client()
    login(client, 'admin')
    headers = {'Origin': 'http://localhost'}
    if token is not None:
        headers['X-CSRF-Token'] = token
    result = client.post(path, json=body, headers=headers)
    assert result.status_code == 403
    assert result.json['code'] == 'CSRF_INVALID'
    assert result.json['trace_id'] == result.headers['X-Trace-Id']
    assert client.get('/permission/session').json['locked'] is False


def test_notice_noop_and_concurrent_update(security_app):
    client = security_app[0].test_client()
    credentials = login(client, 'admin').json
    notice = client.get('/permission/login-notice').json
    body = {key: notice[key] for key in ('enabled', 'text')}
    assert post(client, '/permission/login-notice', credentials, body).json['version'] == notice['version']
    body.update(text='A new notice', expectedVersion=notice['version'])
    updated = post(client, '/permission/login-notice', credentials, body)
    assert updated.json['version'] == notice['version'] + 1
    conflict = post(client, '/permission/login-notice', credentials, body)
    assert conflict.status_code == 409 and conflict.json['code'] == 'NOTICE_CONFLICT'


def test_missing_backup_and_invalid_digest_have_specific_errors(security_app):
    client = security_app[0].test_client()
    credentials = login(client, 'admin').json
    missing = post(client, '/api/security/backups/' + '0' * 32 + '/validate', credentials, {})
    assert missing.status_code == 404 and missing.json['code'] == 'BACKUP_NOT_FOUND'
    backup = post(client, '/api/security/backups', credentials, {}).json
    mismatch = post(client, f"/api/security/backups/{backup['id']}/validate", credentials, {'sha256': '0' * 64})
    assert mismatch.status_code == 400 and mismatch.json['code'] == 'VALIDATED_DIGEST_REQUIRED'


def test_storage_permission_error_is_unavailable_not_empty_success(security_app, monkeypatch):
    from utils import security_backup
    monkeypatch.setattr(security_backup, 'list_backups', Mock(side_effect=PermissionError('private path')))
    client = security_app[0].test_client()
    login(client, 'admin')
    response = client.get('/api/security/backups')
    assert response.status_code == 503 and response.json['code'] == 'BACKUP_STORAGE_UNAVAILABLE'
    assert 'private path' not in response.get_data(as_text=True)


def test_factory_preview_checks_baseline_before_loading_crypto(security_app, monkeypatch):
    client = security_app[0].test_client()
    credentials = login(client, 'admin').json
    monkeypatch.setitem(sys.modules, 'utils.security_backup', None)
    response = post(client, '/api/security/factory-reset', credentials, {'dry_run': True})
    assert response.status_code == 409 and response.json['code'] == 'FACTORY_BASELINE_NOT_CONFIGURED'


@pytest.mark.parametrize('path,code', [
    ('/api/security/certificates', 'CERTIFICATE_COLLECTION_FAILED'),
    ('/api/security/keys', 'KEY_COLLECTION_FAILED'),
    ('/api/security/config-summary', 'CONFIG_SUMMARY_COLLECTION_FAILED'),
])
def test_inventory_dependency_failure_has_specific_code(security_app, monkeypatch, path, code):
    from routes import route_security
    monkeypatch.setattr(route_security, 'certificate_inventory', Mock(side_effect=ImportError('cryptography missing')))
    client = security_app[0].test_client()
    login(client, 'admin')
    response = client.get(path)
    assert response.status_code == 503 and response.json['code'] == code


def test_peer_telemetry_does_not_require_certificate_inventory(security_app, monkeypatch):
    from routes import route_security
    inventory = Mock(side_effect=RuntimeError('must not collect certificates'))
    monkeypatch.setattr(route_security, 'certificate_inventory', inventory)
    client = security_app[0].test_client()
    login(client, 'admin')
    response = client.get('/api/security/peer-status')
    assert response.status_code == 200
    assert response.json['data'] == [] and not response.json['liveAuthenticationTelemetryAvailable']
    inventory.assert_not_called()


@pytest.fixture
def query_app():
    """只加载被测查询函数，避免导入主应用时连接 MySQL 或设备。"""
    source = Path(__file__).parents[1] / 'routes/route_g3.py'
    tree = ast.parse(source.read_text())
    names = {'_query_error', '_query_positive_integer', '_query_time_range',
             'GetFault', 'GetDeviceData', 'GetRecordList', 'GetRecordDetails'}
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    blueprint = Blueprint('query_feedback', __name__)
    scope = dict(g3_bp=blueprint, g=g, request=request, jsonify=jsonify, datetime=datetime,
                 DPrint=Mock(), read_ini_all=Mock(return_value={}),
                 _ini_get_int=Mock(return_value=1), common=SimpleNamespace(TEST_MODE=False),
                 find_device=Mock(return_value={'sort': 1}),
                 REMOTE_IPS=['192.0.2.1'], REMOTE_PORTS=[22],
                 REMOTE_USERNAME='test', REMOTE_PASSWORD='test',
                 REMOTE_DB_FILE='remote.db', LOCAL_SAVE_PATH='local.db', SQL_TABLE_NAME='records',
                 check_network=Mock(return_value=False), scp_download=Mock(),
                 query_device_sqlitedata=Mock(return_value=[]),
                 subprocess=__import__('subprocess'))
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), 'exec'), scope)
    app = Flask(__name__)
    app.register_blueprint(blueprint)
    return app.test_client(), scope


@pytest.mark.parametrize('path,query', [
    ('/api/history/getFault', {'beginDt': '2026-11-10 00:00:00', 'endDt': '2026-11-10T23:59:59'}),
    ('/api/history/getFault', {'beginDt': '2026-11-10T00:00:00', 'endDt': '2026-11-10T23:59:59', 'pageNum': '0'}),
    ('/api/history/getDeviceData', {}),
    ('/api/faultRecord/getRecordList', {}),
    ('/api/faultRecord/getRecordDetails', {'recordId': 'abc'}),
])
def test_query_validation_precedes_device_access(query_app, path, query):
    client, scope = query_app
    response = client.get(path, query_string=query)
    assert response.status_code == 400 and response.json['code'] == 'INVALID_QUERY'
    assert response.json['trace_id'] == response.headers['X-Trace-Id']
    scope['read_ini_all'].assert_not_called()
    scope['find_device'].assert_not_called()


def test_offline_recording_is_not_reported_as_success(query_app):
    client, _ = query_app
    response = client.get('/api/faultRecord/getRecordList', query_string={
        'pcsId': '4', 'beginDt': '2026-11-10', 'endDt': '2026-11-11'})
    assert response.status_code == 503 and response.json['code'] == 'DEVICE_UNREACHABLE'


def test_empty_recordings_are_a_successful_empty_list(query_app):
    client, scope = query_app
    scope['check_network'].return_value = True
    response = client.get('/api/faultRecord/getRecordList', query_string={
        'pcsId': '4', 'beginDt': '2026-11-10', 'endDt': '2026-11-11'})
    assert response.status_code == 200
    assert response.json['ok'] and response.json['recordList'] == [] and response.json['total'] == 0


def test_unexpected_recording_error_does_not_leak_exception(query_app):
    client, scope = query_app
    scope['find_device'].side_effect = RuntimeError('SELECT secret FROM private_table')
    response = client.get('/api/faultRecord/getRecordList', query_string={
        'pcsId': '4', 'beginDt': '2026-11-10', 'endDt': '2026-11-11'})
    assert response.status_code == 500 and response.json['code'] == 'INTERNAL_ERROR'
    assert 'private_table' not in response.get_data(as_text=True)


def test_certificate_inventory_supports_older_cryptography_dates(security_app, monkeypatch):
    from datetime import timedelta
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    directory = Path(security_app[0].config['MODBUS_CERT_DIR'])
    directory.mkdir()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'legacy-runtime')])
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                   .public_key(key.public_key()).serial_number(2)
                   .not_valid_before(datetime.utcnow() - timedelta(days=1))
                   .not_valid_after(datetime.utcnow() + timedelta(days=10))
                   .sign(key, hashes.SHA256()))
    (directory / 'master.crt').write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    original_load = x509.load_pem_x509_certificate

    class OldCertificate:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def __getattr__(self, name):
            if name in ('not_valid_before_utc', 'not_valid_after_utc'):
                raise AttributeError(name)
            if name == 'not_valid_before':
                return self.wrapped.not_valid_before_utc.replace(tzinfo=None)
            if name == 'not_valid_after':
                return self.wrapped.not_valid_after_utc.replace(tzinfo=None)
            return getattr(self.wrapped, name)

    monkeypatch.setattr(x509, 'load_pem_x509_certificate', lambda data: OldCertificate(original_load(data)))
    client = security_app[0].test_client()
    login(client, 'admin')
    result = client.get('/api/security/certificates')
    assert result.status_code == 200 and result.json['expiringCount'] == 1
    assert result.json['data'][0]['notBefore'].endswith('+00:00')


def test_components_omit_absent_optional_executables(security_app, monkeypatch):
    from routes import route_security
    monkeypatch.setattr(route_security.shutil, 'which', lambda name: None)
    client = security_app[0].test_client()
    login(client, 'admin')
    response = client.get('/api/system/components')
    names = {item['name'] for item in response.json['components']}
    assert response.status_code == 200 and 'Python' in names
    assert 'Node.js' not in names and 'MySQL client' not in names
    assert not response.json['firmwareInventoryComplete']


def test_recording_download_failure_is_a_device_error(query_app):
    client, scope = query_app
    scope['check_network'].return_value = True
    scope['scp_download'].side_effect = RuntimeError('SCP failed: private credentials')
    response = client.get('/api/faultRecord/getRecordList', query_string={
        'pcsId': '4', 'beginDt': '2026-11-10', 'endDt': '2026-11-11'})
    assert response.status_code == 503 and response.json['code'] == 'DEVICE_UNREACHABLE'
    assert 'private credentials' not in response.get_data(as_text=True)
    scope['query_device_sqlitedata'].assert_not_called()
