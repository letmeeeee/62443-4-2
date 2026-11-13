"""Certificate list self-tests use temporary keys and a mocked Modbus device CLI."""
import subprocess
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from test_auth_session import auth_app, login
from test_security_center import security_app


@pytest.fixture
def identity(security_app, tmp_path):
    app = security_app[0]
    directory = tmp_path / 'identities'
    directory.mkdir()
    app.config.update(HTTPS_CERT_DIR=str(directory), MODBUS_CERT_DIR=str(directory))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'test')])
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                   .public_key(key.public_key()).serial_number(1)
                   .not_valid_before(datetime.utcnow() - timedelta(days=2))
                   .not_valid_after(datetime.utcnow() - timedelta(days=1))
                   .sign(key, hashes.SHA256()))
    data = certificate.public_bytes(serialization.Encoding.PEM)
    for name in ('g3.crt', 'master.crt', 'slave.crt'):
        (directory / name).write_bytes(data)
    private = directory / 'g3.key'
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    private.chmod(0o600)
    item = dict(role='https', sha256=certificate.fingerprint(hashes.SHA256()).hex(),
                status='expired', chainVerified=False, privateKeyVerified=None)
    return app, directory, item


def test_https_checks_signing_even_when_certificate_expired(identity):
    from routes.route_security import _certificate_private_key_check
    app, _, item = identity
    with app.app_context():
        assert _certificate_private_key_check(item) == (True, 'VERIFIED')


@pytest.mark.parametrize('condition,reason', [
    ('missing', 'PRIVATE_KEY_NOT_FOUND'),
    ('permissions', 'INVALID_PRIVATE_KEY_PERMISSIONS'),
    ('invalid', 'PRIVATE_KEY_SELF_TEST_FAILED'),
    ('mismatch', 'PRIVATE_KEY_MISMATCH'),
])
def test_https_private_key_failures(identity, condition, reason):
    from routes.route_security import _certificate_private_key_check
    app, directory, item = identity
    private = directory / 'g3.key'
    if condition == 'missing':
        private.unlink()
    elif condition == 'permissions':
        private.chmod(0o644)
    elif condition == 'invalid':
        private.write_bytes(b'invalid key')
    else:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    with app.app_context():
        assert _certificate_private_key_check(item) == (False, reason)


@pytest.mark.parametrize('outcome,expected', [
    (0, (True, 'VERIFIED')),
    (1, (False, 'PRIVATE_KEY_SELF_TEST_FAILED')),
    ('missing', (None, 'PRIVATE_KEY_CHECK_UNAVAILABLE')),
    ('timeout', (None, 'PRIVATE_KEY_CHECK_TIMEOUT')),
])
def test_modbus_uses_only_existing_key_check(identity, monkeypatch, outcome, expected):
    from routes import route_security as module
    app, directory, item = identity
    item['role'] = 'master'
    def run(arguments, **kwargs):
        assert arguments[1:5] == ['--dir', str(directory), 'check', 'master']
        assert kwargs['timeout'] == 15
        assert kwargs['env']['MODBUS_KEY_BACKEND'] == 'tee'
        assert open(arguments[5], 'rb').read() == (directory / 'master.crt').read_bytes()
        if outcome == 'missing':
            raise FileNotFoundError()
        if outcome == 'timeout':
            raise subprocess.TimeoutExpired(arguments, 15)
        return SimpleNamespace(returncode=outcome)
    monkeypatch.setenv('MODBUS_KEY_BACKEND', 'tee')
    monkeypatch.setattr(module.subprocess, 'run', run)
    with app.app_context():
        assert module._certificate_private_key_check(item) == expected


@pytest.mark.parametrize('endpoint', [
    '/api/security/certificates', '/api/security/status', '/api/security/config-summary',
])
def test_list_checks_every_request_and_preserves_certificate_status(identity, monkeypatch, endpoint):
    from routes import route_security as module
    app, directory, item = identity
    monkeypatch.setattr(module, '_command', lambda *args, **kwargs: None)
    from utils import system_usage, ini_integrity
    monkeypatch.setattr(system_usage, 'cpu_usage', lambda: dict(usedPercent=0))
    monkeypatch.setattr(ini_integrity, 'verify_ini_checksum', lambda: (True, 'verified'))
    monkeypatch.setattr(module, 'certificate_inventory', lambda: [dict(item), dict(role='ca-root', status='valid')])
    client = app.test_client()
    login(client, 'admin')
    def entries(response):
        if endpoint.endswith('/status'):
            assert response.json['checks']['certificates']['available'] is True
            return response.json['checks']['certificates']['data']
        if endpoint.endswith('/config-summary'):
            return response.json['certificates']
        return response.json['data']
    first = client.get(endpoint)
    assert first.status_code == 200
    assert entries(first)[0]['privateKeyVerified'] is True
    assert entries(first)[0]['status'] == 'expired'
    assert entries(first)[0]['chainVerified'] is False
    assert entries(first)[1]['privateKeyVerified'] is None
    assert entries(first)[1]['privateKeyCheckReason'] == 'NOT_APPLICABLE'
    (directory / 'g3.key').unlink()
    second = client.get(endpoint)
    assert second.status_code == 200
    assert entries(second)[0]['privateKeyVerified'] is False
    assert entries(second)[0]['privateKeyCheckReason'] == 'PRIVATE_KEY_NOT_FOUND'


def test_changed_certificate_is_not_reported_as_verified(identity, monkeypatch):
    from routes import route_security as module
    app, directory, item = identity
    original = module._https_private_key_check
    def changing(certificate, location):
        result = original(certificate, location)
        (directory / 'g3.crt').write_bytes(b'changed')
        return result
    monkeypatch.setattr(module, '_https_private_key_check', changing)
    with app.app_context():
        assert module._certificate_private_key_check(item) == (None, 'CERTIFICATE_CHANGED_DURING_CHECK')
