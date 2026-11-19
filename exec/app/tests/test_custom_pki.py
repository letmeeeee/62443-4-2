"""Real OpenSSL custom PKI, with service operations replaced by callbacks."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import types

import pytest
from flask import Blueprint

from pki_test_helpers import make_ca, openssl, sign_csr
from test_ca_provisioning import authority, device, identity_binary
from test_auth_session import auth_app, login
from script import custom_pki as custom, pki_common as pki


@pytest.fixture
def manager(device):
    return custom.CustomPKI(device['config'], device['modbus'], device['https'])


@pytest.fixture
def material(tmp_path, authority):
    counter = [0]

    def create(role, bits=2048, days=365, purpose=None, cn=None, ips=None):
        counter[0] += 1
        folder = tmp_path / ('external-' + str(counter[0]))
        folder.mkdir()
        key, csr = folder / 'device.key', folder / 'request.csr'
        cn = cn if cn is not None else ('LC400-001-server' if role == 'https' else 'external-' + role)
        openssl('req', '-new', '-newkey', 'rsa:' + str(bits), '-nodes', '-subj', '/CN=' + cn,
                '-keyout', key, '-out', csr)
        cert = sign_csr(csr, folder / 'leaf.crt', authority,
                        role=purpose or ('client' if role == 'master' else 'server'),
                        ips=ips if ips is not None else (['127.0.0.1'] if role != 'master' else []), days=days)
        return dict(key=key.read_bytes(), identity=cert.read_bytes(),
                    chain=authority['intermediate'].read_bytes())
    return create


def stage(manager, material, role, identifier=None):
    for part in ('key', 'chain', 'identity'):
        state = manager.upload(part, material[part], role, identifier)
        identifier = state['batch_id']
    return identifier


def test_independent_batches_require_explicit_identifier(manager, material):
    files = material('master')
    first = stage(manager, files, 'master')
    second = manager.upload('key', files['key'], 'master')['batch_id']
    assert first != second
    assert manager.status(first)['roles']['master'] == ['chain', 'identity', 'key']
    assert manager.status(second)['roles'] == {'master': ['key']}
    with pytest.raises(ValueError, match='valid batch_id'):
        manager.status(None)
    with pytest.raises(ValueError, match='valid batch_id'):
        manager.apply(None, lambda service: None)


@pytest.mark.parametrize('role', ['master', 'slave', 'https'])
@pytest.mark.parametrize('bits', [2048, 3072])
def test_external_identities_apply_without_csr(manager, material, authority, device, role, bits):
    files = material(role, bits)
    identifier = stage(manager, files, role)
    manager.upload('ca', authority['root'].read_bytes(), batch_id=identifier,
                   expected=[pki.fingerprint(authority['root'].read_bytes())])
    paths = manager.paths(role)
    assert not paths['key'].exists() and not paths['identity'].exists()
    calls = []
    state = manager.apply(identifier, calls.append)
    assert state['status'] == 'applied'
    assert calls == ['nginx' if role == 'https' else 'tems']
    assert not paths['csr'].exists()
    assert pki.is_external_identity(paths['key'].parent, role)
    assert paths['key'].stat().st_mode & 0o777 == 0o600
    assert paths['identity'].stat().st_mode & 0o777 == 0o644
    assert pki.public_key(paths['identity'].read_bytes().split(b'-----END CERTIFICATE-----')[0]
                          + b'-----END CERTIFICATE-----\n') == custom.private_key(paths['key'].read_bytes())[1]
    if role == 'https':
        assert json.loads(device['tool']('https', 'check').stdout)['pki_mode'] == 'trina'
    else:
        device['tool']('modbus', 'check', '--role', role)
    calls.clear()
    assert manager.apply(identifier, calls.append)['status'] == 'applied'
    assert not calls


@pytest.mark.parametrize('cn', ['LC400-001-server', 'LC400-site-A', 'logger', 'lc400-001', 'XLC400-001', 'LC400'])
def test_https_cn_prefix(manager, material, device, cn):
    identifier = stage(manager, material('https', cn=cn), 'https')
    if cn.startswith('LC400-'):
        assert manager.apply(identifier, lambda service: None)['status'] == 'applied'
        assert json.loads(device['tool']('https', 'check').stdout)['valid']
    else:
        with pytest.raises(ValueError, match='HTTPS CN/SAN'):
            manager.apply(identifier, lambda service: pytest.fail('must not restart'))
        assert not manager.paths('https')['identity'].exists()


def test_https_prefix_still_requires_all_device_ips(manager, material):
    files = material('https', cn='LC400-001-server', ips=['192.168.2.136'])
    identifier = stage(manager, files, 'https')
    with pytest.raises(ValueError, match='HTTPS CN/SAN'):
        manager.apply(identifier, lambda service: pytest.fail('must not restart'))
    assert not manager.paths('https')['identity'].exists()


def test_stale_csr_is_not_a_prerequisite(manager, material):
    paths = manager.paths('master')
    paths['csr'].write_bytes(b'not a CSR')
    identifier = stage(manager, material('master'), 'master')
    manager.apply(identifier, lambda service: None)
    assert not paths['csr'].exists()
    backup = manager.home / 'backups' / manager.status(identifier)['backup_id']
    assert (backup / 'master.csr').read_bytes() == b'not a CSR'


@pytest.mark.parametrize('fault', ['key', 'chain', 'expired', 'purpose'])
def test_invalid_batch_never_installs_live_files(manager, material, fault):
    files = material('master', days=-1 if fault == 'expired' else 365,
                     purpose='server' if fault == 'purpose' else None)
    if fault == 'key':
        files['key'] = material('master')['key']
    if fault == 'chain':
        files['chain'] = b''
    identifier = stage(manager, files, 'master')
    with pytest.raises(ValueError):
        manager.apply(identifier, lambda service: pytest.fail('must not restart'))
    assert not manager.paths('master')['key'].exists()
    assert not manager.paths('master')['identity'].exists()
    assert not manager.guard.exists()


def test_reject_invalid_uploads_and_wrong_root_pins(manager, material, authority):
    files = material('master')
    for data in (b'not a key', files['key'] + files['identity'], material('master', bits=1024)['key']):
        with pytest.raises(ValueError):
            manager.upload('key', data, 'master')
    with pytest.raises(ValueError):
        manager.upload('ca', authority['root'].read_bytes(), expected=['0' * 64])
    with pytest.raises(ValueError):
        manager.upload('chain', authority['root'].read_bytes(), 'master')
    with pytest.raises(ValueError):
        manager.upload('identity', files['identity'] + files['chain'], 'master')


def test_service_failure_keeps_installed_batch_retryable(manager, material):
    identifier = stage(manager, material('master'), 'master')
    def fail(service):
        raise OSError('simulated service failure')
    failed = manager.apply(identifier, fail)
    key = manager.paths('master')['key'].read_bytes()
    assert failed['status'] == 'installed' and failed['pending'] == ['tems']
    assert pki.pending_path(manager.settings, 'tems').exists()
    with pytest.raises(custom.Conflict):
        manager.upload('key', material('master')['key'], 'master', identifier)
    applied = manager.apply(identifier, lambda service: None)
    assert applied['backup_id'] == failed['backup_id'] and applied['status'] == 'applied'
    assert manager.paths('master')['key'].read_bytes() == key
    assert not pki.pending_path(manager.settings, 'tems').exists()


def test_shared_root_replacement_checks_unselected_active_identity(manager, material, tmp_path):
    identifier = stage(manager, material('master'), 'master')
    manager.apply(identifier, lambda service: None)
    original = manager.settings['ca_file'].read_bytes()
    other = make_ca(tmp_path / 'other-authority')
    state = manager.upload('ca', other['root'].read_bytes(), expected=[pki.fingerprint(other['root'].read_bytes())])
    with pytest.raises(ValueError):
        manager.apply(state['batch_id'], lambda service: pytest.fail('must not restart'))
    assert manager.settings['ca_file'].read_bytes() == original


def test_old_interface_changes_prevent_stale_apply_retry(manager, material):
    identifier = stage(manager, material('master'), 'master')
    manager.apply(identifier, lambda service: None)
    manager.paths('master')['identity'].write_bytes(material('master')['identity'])
    with pytest.raises(custom.Conflict):
        manager.apply(identifier, lambda service: pytest.fail('must not restart'))


def test_leaf_replacement_reuses_existing_chain(manager, material):
    identifier = stage(manager, material('master'), 'master')
    manager.apply(identifier, lambda service: None)
    replacement = material('master')
    state = manager.upload('key', replacement['key'], 'master')
    manager.upload('identity', replacement['identity'], 'master', state['batch_id'])
    applied = manager.apply(state['batch_id'], lambda service: None)
    assert applied['status'] == 'applied'
    assert manager.paths('master')['identity'].read_bytes() == replacement['identity'] + replacement['chain']


def test_changed_shared_roots_prevent_stale_service_retry(manager, material, tmp_path):
    identifier = stage(manager, material('master'), 'master')
    def fail(service):
        raise OSError('service unavailable')
    manager.apply(identifier, fail)
    other = make_ca(tmp_path / 'other-retry-authority')
    manager.settings['ca_file'].write_bytes(other['root'].read_bytes())
    with pytest.raises(custom.Conflict):
        manager.apply(identifier, lambda service: pytest.fail('must not restart'))


def test_custom_apply_still_rejects_revoked_leaf(manager, material, authority):
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding
    from script import crl_store
    from test_crl_management import signed_crl

    files = material('master')
    serial = x509.load_pem_x509_certificate(files['identity']).serial_number
    crl_store.import_crls(manager.settings, signed_crl(authority, revoked=[serial]).public_bytes(Encoding.PEM),
                          authority['intermediate'].read_bytes())
    identifier = stage(manager, files, 'master')
    with pytest.raises(ValueError, match='revocation'):
        manager.apply(identifier, lambda service: pytest.fail('must not restart'))
    assert not manager.paths('master')['key'].exists()


@pytest.mark.parametrize('failed_recovery', [False, True])
def test_install_failure_restores_files_or_leaves_recovery_journal(manager, material, monkeypatch, failed_recovery):
    identifier = stage(manager, material('master'), 'master')
    manager.apply(identifier, lambda service: None)
    original = {part: path.read_bytes() for part, path in manager.paths('master').items() if path.exists()}
    second = stage(manager, material('master'), 'master')
    real = pki.atomic_write
    failures = [0]
    def interrupted(path, data, mode=0o600):
        if Path(path) == manager.paths('master')['identity'] and (failed_recovery or failures[0] == 0):
            failures[0] += 1
            raise OSError('simulated publication error')
        return real(path, data, mode)
    with monkeypatch.context() as patch:
        patch.setattr(pki, 'atomic_write', interrupted)
        with pytest.raises(OSError):
            manager.apply(second, lambda service: pytest.fail('must not restart'))
    if failed_recovery:
        assert manager.guard.exists()
        with pytest.raises(custom.Conflict):
            manager.apply(second, lambda service: None)
        assert manager.recover()['recovered']
    assert not manager.guard.exists()
    for part, data in original.items():
        assert manager.paths('master')[part].read_bytes() == data
    assert manager.status(second)['status'] == 'staged'


@pytest.mark.parametrize('failure', ['expiring', 'invalid', 'missing-key', 'missing-cert'])
def test_external_https_maintenance_only_reports(manager, material, device, failure):
    identifier = stage(manager, material('https', days=1 if failure == 'expiring' else 365), 'https')
    manager.apply(identifier, lambda service: None)
    paths = manager.paths('https')
    if failure == 'invalid':
        paths['identity'].write_bytes(b'invalid certificate')
    elif failure == 'missing-key':
        paths['key'].unlink()
    elif failure == 'missing-cert':
        paths['identity'].unlink()
    before = custom.read(paths['key'], optional=True)
    device['tool']('https', 'reconcile', success=failure == 'expiring')
    state = json.loads((device['https'] / 'renewal-status.json').read_text())
    assert state['pki_mode'] == 'trina' and state['renewal_required']
    assert state['external_issuance_required'] and state['csr_generated'] is False
    assert not paths['csr'].exists()
    assert custom.read(paths['key'], optional=True) == before


def test_explicit_old_csr_import_returns_to_general_flow(manager, material, authority, device, tmp_path):
    identifier = stage(manager, material('https'), 'https')
    manager.apply(identifier, lambda service: None)
    device['tool']('https', 'csr')
    leaf = sign_csr(device['https'] / 'g3.csr', tmp_path / 'general.crt', authority, ips=['127.0.0.1'])
    device['tool']('https', 'identity-import', '--cert', leaf, '--chain', authority['intermediate'])
    assert not pki.is_external_identity(device['https'], 'https')


@pytest.fixture
def custom_http(auth_app, device, monkeypatch):
    app = auth_app[0]
    config = sys.modules['config']
    config.INI_PATH = device['config']
    config.STATE_DONE, config.STATE_ERROR = 3, -1
    monkeypatch.setenv('MODBUS_KEY_BACKEND', 'file')
    monkeypatch.setenv('MODBUS_TEE_IDENTITY', device['env']['MODBUS_TEE_IDENTITY'])
    app.config.update(MODBUS_CERT_DIR=str(device['modbus']), HTTPS_CERT_DIR=str(device['https']))
    module = types.ModuleType('routes.route_g3')
    module.g3_bp = Blueprint('custom-http', __name__)
    monkeypatch.setitem(sys.modules, 'routes.route_g3', module)
    spec = importlib.util.spec_from_file_location('custom_test_routes', Path(__file__).parents[1] / 'routes/route_cert.py')
    routes = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(routes)
    routes.CERT_SCRIPT = Path(__file__).parents[1] / 'script/modbus_certs.py'
    app.register_blueprint(module.g3_bp)
    calls = []
    monkeypatch.setattr(routes, '_custom_service_apply', calls.append)
    return app, routes, calls


def test_http_staging_apply_status_and_auth(custom_http, material, authority):
    app, routes, calls = custom_http
    visitor = app.test_client()
    assert visitor.post('/api/cert/custom/key/import').status_code == 401
    credentials = login(visitor).json
    assert visitor.post('/api/cert/custom/key/import', headers={'X-CSRF-Token': credentials['csrf_token']}).status_code == 403
    client = app.test_client()
    credentials = login(client, 'admin').json
    headers = {'X-CSRF-Token': credentials['csrf_token']}
    assert client.post('/api/cert/custom/key/import', headers=headers,
                       data={'pki_mode': 'general'}).status_code == 400
    files = material('master')
    identifier = None
    for part in ('key', 'ca', 'chain', 'identity'):
        data = dict(pki_mode='trina', role='master')
        if identifier:
            data['batch_id'] = identifier
        content = authority['root'].read_bytes() if part == 'ca' else files[part]
        data['file'] = (io.BytesIO(content), 'material.pem')
        if part == 'ca':
            data['fingerprint'] = pki.fingerprint(content)
        response = client.post('/api/cert/custom/' + part + '/import', headers=headers, data=data)
        assert response.status_code == 200, response.json
        identifier = response.json['data']['batch_id']
        assert 'PRIVATE KEY' not in response.get_data(as_text=True)
    assert not calls
    response = client.post('/api/cert/custom/apply', headers=headers,
                           json={'pki_mode': 'trina', 'batch_id': identifier})
    assert response.status_code == 200 and calls == ['tems']
    assert response.json['data']['status'] == 'applied'
    assert 'active_hashes' not in response.json['data']
    response = client.get('/api/cert/custom/status', query_string=dict(pki_mode='trina', batch_id=identifier))
    assert response.status_code == 200 and response.json['data']['status'] == 'applied'


def test_old_http_accepts_general_and_omitted_mode(custom_http):
    app, _, _ = custom_http
    client = app.test_client()
    credentials = login(client, 'admin').json
    headers = {'X-CSRF-Token': credentials['csrf_token']}
    for role, mode in [('master', None), ('slave', 'general'), ('master', 'trina')]:
        data = dict(role=role, name='old-' + role, ip=['127.0.0.1'])
        if mode:
            data['pki_mode'] = mode
        response = client.post('/api/cert/csr', json=data, headers=headers)
        assert response.status_code == 200
        assert client.get('/api/cert/check', query_string=dict(role=role, pki_mode='custom')).status_code == 400
    assert client.get('/api/cert/mode?pki_mode=general').status_code == 200
    assert client.get('/api/cert/mode').status_code == 200
    assert client.post('/api/cert/ca/import', headers=headers,
                       data={'pki_mode': 'custom'}).status_code == 400


def test_security_aliases_accept_general_without_affecting_legacy_calls(custom_http, authority, device, tmp_path, monkeypatch):
    app, routes, _ = custom_http
    from routes.route_security import security_bp
    app.register_blueprint(security_bp)
    monkeypatch.setitem(sys.modules, 'routes.route_cert', routes)
    client = app.test_client()
    credentials = login(client, 'admin').json
    headers = {'X-CSRF-Token': credentials['csrf_token']}
    assert client.post('/api/cert/csr', headers=headers,
                       json=dict(pki_mode='general', role='master', name='alias-master')).status_code == 200
    leaf = sign_csr(device['modbus'] / 'master.csr', tmp_path / 'alias.crt', authority, role='client')
    response = client.post('/api/security/certificates/import', headers=headers, data={
        'pki_mode': 'general', 'role': 'master',
        'file': (io.BytesIO(leaf.read_bytes()), 'leaf.pem'),
        'chain': (io.BytesIO(authority['intermediate'].read_bytes()), 'chain.pem'),
    })
    assert response.status_code == 200
    for body in ({'role': 'master'}, {'role': 'master', 'pki_mode': 'general'},
                 {'role': 'master', 'pki_mode': 'trina'}):
        response = client.post('/api/security/certificates/verify', json=body, headers=headers)
        assert response.status_code == 200 and response.json['valid']
    assert client.post('/api/security/certificates/verify', headers=headers,
                       json=dict(role='master', pki_mode='custom')).status_code == 400
    assert client.post('/api/security/certificates/import', headers=headers,
                       data=dict(role='master', pki_mode='custom')).status_code == 400


def test_staged_batch_detects_another_batch_install(manager, material):
    first = stage(manager, material('master'), 'master')
    second = stage(manager, material('slave'), 'slave')
    manager.apply(first, lambda service: None)
    with pytest.raises(custom.Conflict, match='live PKI changed'):
        manager.apply(second, lambda service: pytest.fail('must not restart'))
    assert not manager.paths('slave')['identity'].exists()


def test_legacy_service_apply_is_reflected_in_batch_status(manager, material):
    identifier = stage(manager, material('master'), 'master')
    def fail(service):
        raise OSError('service failure')
    assert manager.apply(identifier, fail)['status'] == 'installed'
    pki.pending_path(manager.settings, 'tems').unlink()
    assert manager.status(identifier)['status'] == 'applied'
    assert manager.status(identifier)['services'] == {'tems': 'success'}
    manager.apply(identifier, lambda service: pytest.fail('already applied'))


@pytest.mark.parametrize('revoked', [False, True])
def test_existing_crl_endpoint_defers_new_ca_crl_into_pinned_batch(manager, authority, tmp_path, revoked):
    from script import crl_store
    from test_crl_management import signed_crl
    from cryptography.hazmat.primitives import serialization
    other = make_ca(tmp_path / 'new-ca', name='new-ca')
    key, csr = tmp_path / 'new.key', tmp_path / 'new.csr'
    openssl('req', '-new', '-newkey', 'rsa:2048', '-nodes', '-subj', '/CN=new-master',
            '-keyout', key, '-out', csr)
    leaf = sign_csr(csr, tmp_path / 'new.crt', other, role='client')
    identifier = stage(manager, dict(key=key.read_bytes(), identity=leaf.read_bytes(),
                                    chain=other['intermediate'].read_bytes()), 'master')
    manager.upload('ca', other['root'].read_bytes(), batch_id=identifier,
                   expected=[pki.fingerprint(other['root'].read_bytes())])
    # Preserve the old live CRL; no new trust or CRL is activated by this upload.
    old = signed_crl(authority).public_bytes(serialization.Encoding.PEM)
    crl_store.import_crls(manager.settings, old, authority['intermediate'].read_bytes())
    live_crl = manager.settings['crl_file'].read_bytes()
    from cryptography import x509
    serial = x509.load_pem_x509_certificate(leaf.read_bytes()).serial_number
    result = crl_store.import_crls(manager.settings,
        signed_crl(other, revoked=[serial] if revoked else []).public_bytes(serialization.Encoding.PEM),
        other['intermediate'].read_bytes())
    assert result['staged'] and result['batch_ids'] == [identifier]
    assert manager.settings['crl_file'].read_bytes() == live_crl
    assert manager.settings['ca_file'].read_bytes() == authority['root'].read_bytes()
    # A newer live CRL must not be overwritten by the older retained staged copy.
    crl_store.import_crls(manager.settings,
        signed_crl(authority, number=2, revoked=[999]).public_bytes(serialization.Encoding.PEM),
        authority['intermediate'].read_bytes())
    if revoked:
        with pytest.raises(ValueError, match='CERTIFICATE_REVOKED'):
            manager.apply(identifier, lambda service: pytest.fail('must not activate'))
        return
    assert manager.apply(identifier, lambda service: None)['status'] == 'applied'
    crls, _ = crl_store._read_store(manager.settings['crl_file'])
    old_key = crl_store._key(signed_crl(authority))
    retained = next(crl for crl in crls if crl_store._key(crl) == old_key)
    assert retained.get_revoked_certificate_by_serial_number(999) is not None
    assert crl_store.certificate_status(manager.paths('master')['identity'].read_bytes(),
        manager.settings['ca_file'], manager.settings['crl_file'])['revocationStatus'] == 'good'


def test_general_root_import_cannot_break_other_active_roles(manager, material, tmp_path):
    identifier = stage(manager, material('https'), 'https')
    manager.apply(identifier, lambda service: None)
    previous = manager.settings['ca_file'].read_bytes()
    other = make_ca(tmp_path / 'foreign-root', name='foreign-root')
    with pytest.raises(ValueError, match='invalidates role=https'):
        pki.import_roots(manager.settings['ca_file'], other['root'].read_bytes(),
                         identity_dirs=(manager.modbus, manager.https))
    assert manager.settings['ca_file'].read_bytes() == previous


def test_direct_root_leaf_does_not_inherit_old_intermediate(manager, material, authority, tmp_path):
    original = stage(manager, material('master'), 'master')
    manager.apply(original, lambda service: None)
    direct_ca = dict(authority, intermediate=authority['root'], intermediate_key=authority['root_key'])
    key, csr = tmp_path / 'direct.key', tmp_path / 'direct.csr'
    openssl('req', '-new', '-newkey', 'rsa:2048', '-nodes', '-subj', '/CN=direct-master',
            '-keyout', key, '-out', csr)
    leaf = sign_csr(csr, tmp_path / 'direct.crt', direct_ca, role='client')
    state = manager.upload('key', key.read_bytes(), 'master')
    identifier = state['batch_id']
    manager.upload('identity', leaf.read_bytes(), 'master', identifier)
    manager.apply(identifier, lambda service: None)
    assert manager.paths('master')['chain'].read_bytes() == b''


def test_https_status_reports_invalid_identity_without_generating_key(device):
    response = device['tool']('https', 'status')
    status = json.loads(response.stdout)
    assert status['valid'] is False and status['reason'] == 'HTTPS_IDENTITY_INVALID_OR_MISSING'
    assert not (device['https'] / 'g3.key').exists()


def test_expired_crl_blocks_new_install_but_remains_available_for_revocation(manager, material, authority):
    from script import crl_store
    from test_crl_management import signed_crl
    from cryptography.hazmat.primitives import serialization
    identifier = stage(manager, material('master'), 'master')
    crl_store.import_crls(manager.settings,
        signed_crl(authority, expired=True).public_bytes(serialization.Encoding.PEM),
        authority['intermediate'].read_bytes())
    with pytest.raises(ValueError, match='CRL_EXPIRED'):
        manager.apply(identifier, lambda service: pytest.fail('must not activate'))
    assert not manager.paths('master')['identity'].exists()


def test_legacy_apply_synchronizes_batch_without_extra_frontend_call(custom_http, manager, material, monkeypatch):
    app, routes, _ = custom_http
    assert not any(rule.rule == '/api/cert/reset' for rule in app.url_map.iter_rules())
    identifier = stage(manager, material('master'), 'master')
    def fail(service):
        raise OSError('simulated failure')
    assert manager.apply(identifier, fail)['status'] == 'installed'
    client = app.test_client()
    credentials = login(client, 'admin').json
    monkeypatch.setattr(routes.subprocess, 'run', lambda *args, **kwargs:
                        types.SimpleNamespace(returncode=0, stdout='', stderr=''))
    response = client.post('/api/cert/https/apply', json={'pki_mode': 'general'},
                           headers={'X-CSRF-Token': credentials['csrf_token']})
    assert response.status_code == 200
    raw = json.loads((manager.home / 'batches' / identifier / 'state.json').read_text())
    assert raw['status'] == 'applied' and raw['pending'] == []


@pytest.mark.parametrize('role', ['master', 'slave', 'https'])
@pytest.mark.parametrize('bits', [2048, 3072])
def test_rsa_pss_upload_rejected_without_changing_batch(manager, material, tmp_path, role, bits):
    identifier = stage(manager, material(role), role)
    directory = manager.home / 'batches' / identifier
    before = {path.name: path.read_bytes() for path in directory.iterdir()}
    key = tmp_path / 'pss.key'
    openssl('genpkey', '-algorithm', 'RSA-PSS', '-pkeyopt', 'rsa_keygen_bits:' + str(bits), '-out', key)
    with pytest.raises(ValueError, match='RSA-PSS private key rejected'):
        manager.upload('key', key.read_bytes(), role, identifier)
    assert before == {path.name: path.read_bytes() for path in directory.iterdir()}
    batches = set((manager.home / 'batches').iterdir())
    with pytest.raises(ValueError, match='RSA-PSS private key rejected'):
        manager.upload('key', key.read_bytes(), role)
    assert set((manager.home / 'batches').iterdir()) == batches
    assert not manager.paths(role)['key'].exists()


@pytest.mark.parametrize('bits', [2048, 3072])
@pytest.mark.parametrize('traditional', [False, True])
def test_ordinary_rsa_pkcs8_and_pkcs1_remain_supported(tmp_path, bits, traditional):
    from cryptography.hazmat.primitives import serialization
    key = tmp_path / 'ordinary.key'
    openssl('genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:' + str(bits), '-out', key)
    data = key.read_bytes()
    if traditional:
        data = serialization.load_pem_private_key(data, password=None).private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption())
    normalized, public = custom.private_key(data)
    assert normalized.startswith(b'-----BEGIN PRIVATE KEY-----')
    assert public == openssl('pkey', '-in', key, '-pubout', '-outform', 'DER')


def test_pss_key_in_existing_staged_batch_cannot_be_applied(manager, material, authority, tmp_path):
    # Simulate a batch staged by the previous permissive implementation.
    identifier = stage(manager, material('master'), 'master')
    directory = manager.home / 'batches' / identifier
    key, csr = tmp_path / 'pss.key', tmp_path / 'pss.csr'
    openssl('genpkey', '-algorithm', 'RSA-PSS', '-pkeyopt', 'rsa_keygen_bits:2048', '-out', key)
    openssl('req', '-new', '-key', key, '-subj', '/CN=pss-master', '-out', csr)
    leaf = sign_csr(csr, tmp_path / 'pss.crt', authority, role='client')
    pki.atomic_write(directory / 'master.key', key.read_bytes())
    pki.atomic_write(directory / 'master.identity', leaf.read_bytes())
    with pytest.raises(ValueError, match='RSA-PSS private key rejected'):
        manager.apply(identifier, lambda service: pytest.fail('must not restart'))
    assert not manager.paths('master')['key'].exists()
    assert manager.status(identifier)['status'] == 'staged'


def test_pss_http_rejection_logs_context_without_private_data(custom_http, tmp_path, monkeypatch):
    app, routes, _ = custom_http
    client = app.test_client()
    credentials = login(client, 'admin').json
    key = tmp_path / 'pss.key'
    openssl('genpkey', '-algorithm', 'RSA-PSS', '-pkeyopt', 'rsa_keygen_bits:2048', '-out', key)
    logs = []
    monkeypatch.setattr(routes, 'DPrint', lambda message, **kwargs: logs.append(message))
    response = client.post('/api/cert/custom/key/import',
        headers={'X-CSRF-Token': credentials['csrf_token']},
        data={'pki_mode': 'trina', 'role': 'slave', 'file': (io.BytesIO(key.read_bytes()), 'pss.pem')})
    assert response.status_code == 422
    assert response.json['code'] == 'PKI_VALIDATION_FAILED'
    diagnostic = next(message for message in logs if '私钥校验拒绝' in message)
    assert "role='slave'" in diagnostic and 'RSA-PSS' in diagnostic and "operator='admin'" in diagnostic
    assert 'BEGIN PRIVATE KEY' not in '\n'.join(logs)
    assert key.read_text().splitlines()[1] not in '\n'.join(logs)


@pytest.mark.parametrize('status', ['staged', 'installed', 'applied'])
def test_historical_custom_batch_mode_is_read_as_trina(manager, material, status):
    identifier = stage(manager, material('master'), 'master')
    def fail(service):
        raise OSError('temporary service failure')
    if status != 'staged':
        manager.apply(identifier, fail if status == 'installed' else lambda service: None)
    path = manager.home / 'batches' / identifier / 'state.json'
    state = json.loads(path.read_text())
    state['pki_mode'] = 'custom'
    pki.atomic_write(path, json.dumps(state).encode())
    assert manager.status(identifier)['pki_mode'] == 'trina'
    assert manager.apply(identifier, lambda service: None)['pki_mode'] == 'trina'
    assert manager.status(identifier)['status'] == 'applied'


def test_https_historical_source_and_renewal_mode_remain_compatible(manager, material, device):
    identifier = stage(manager, material('https'), 'https')
    manager.apply(identifier, lambda service: None)
    pki.atomic_write(manager.paths('https')['source'], b'{"pki_mode":"custom"}')
    pending = manager.https / 'renewal-status.json'
    original = b'{"pki_mode":"custom","csr_generated":false}'
    pki.atomic_write(pending, original)
    result = json.loads(device['tool']('https', 'status').stdout)
    assert result['pki_mode'] == 'trina'
    assert result['renewal']['pki_mode'] == 'trina'
    assert pending.read_bytes() == original
    assert not manager.paths('https')['csr'].exists()


def test_new_custom_endpoint_accepts_only_trina_mode(custom_http):
    app, _, _ = custom_http
    client = app.test_client()
    credentials = login(client, 'admin').json
    headers = {'X-CSRF-Token': credentials['csrf_token']}
    for mode in ('custom', 'general'):
        response = client.post('/api/cert/custom/chain/import', headers=headers,
                               data=dict(pki_mode=mode, role='master', clear='true'))
        assert response.status_code == 400
    response = client.post('/api/cert/custom/chain/import', headers=headers,
                           data=dict(pki_mode='trina', role='master', clear='true'))
    assert response.status_code == 200
    assert response.json['data']['pki_mode'] == 'trina'


def test_public_inventory_poll_reuses_openssl_and_private_self_tests(custom_http, manager, material, monkeypatch):
    from routes import route_security
    from time import perf_counter
    app, _, _ = custom_http
    identifier = stage(manager, material('master'), 'master')
    stage(manager, material('https'), 'https', identifier)
    manager.apply(identifier, lambda service: None)
    openssl_calls = []
    checks = []
    original_run = pki.run
    original_check = route_security._certificate_private_key_check
    def counted_run(*args, **kwargs):
        openssl_calls.append(args[0])
        return original_run(*args, **kwargs)
    def counted_check(item):
        checks.append(item['role'])
        return original_check(item)
    monkeypatch.setattr(pki, 'run', counted_run)
    monkeypatch.setattr(route_security, '_certificate_private_key_check', counted_check)
    with app.app_context():
        started = perf_counter()
        first = route_security._checked_certificate_inventory()
        cold_ms = (perf_counter() - started) * 1000
        count = len(openssl_calls)
        checked = len(checks)
        started = perf_counter()
        second = route_security._checked_certificate_inventory()
        warm_ms = (perf_counter() - started) * 1000
        assert first == second
        assert count > 0 and len(openssl_calls) == count
        assert checked > 0 and len(checks) == checked
        print('PKI inventory: cold_ms=%.1f warm_ms=%.1f cold_openssl=%d warm_openssl=0' %
              (cold_ms, warm_ms, count))


def test_explicit_checks_always_execute_even_with_read_cache(custom_http, manager, material, monkeypatch):
    app, routes, _ = custom_http
    identifier = stage(manager, material('master'), 'master')
    manager.apply(identifier, lambda service: None)
    calls = []
    original = routes._cert_run_script
    def counted(command):
        calls.append(command[0])
        return original(command)
    monkeypatch.setattr(routes, '_cert_run_script', counted)
    client = app.test_client()
    login(client, 'admin')
    for _ in range(2):
        assert client.get('/api/cert/check', query_string=dict(role='master')).status_code == 200
    assert calls == ['check', 'check']
