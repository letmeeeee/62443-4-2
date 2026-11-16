"""Real signed CRLs, HTTP application policy and production C TLS verification."""
import importlib.util
import io
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from flask import Blueprint

from script import crl_store, pki_common as pki
from pki_test_helpers import sign_csr, make_ca
from test_ca_provisioning import ROOT, authority, device, identity_binary
from test_auth_session import auth_app, login
from test_security_center import security_app


def signed_crl(ca, number=1, revoked=(), expired=False, future=False):
    issuer = x509.load_pem_x509_certificate(ca['intermediate'].read_bytes())
    key = serialization.load_pem_private_key(ca['intermediate_key'].read_bytes(), None)
    now = datetime.now(timezone.utc)
    start = now + timedelta(days=1) if future else now - timedelta(days=2)
    end = now - timedelta(days=1) if expired else now + timedelta(days=7)
    builder = (x509.CertificateRevocationListBuilder().issuer_name(issuer.subject)
               .last_update(start).next_update(end)
               .add_extension(x509.CRLNumber(number), False)
               .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), False))
    for serial in revoked:
        builder = builder.add_revoked_certificate(x509.RevokedCertificateBuilder()
                    .serial_number(serial).revocation_date(now - timedelta(days=3)).build())
    return builder.sign(key, hashes.SHA256())


@pytest.fixture
def material(device, authority, tmp_path):
    for role in ('master', 'slave'):
        args = ['--ip', '127.0.0.1'] if role == 'slave' else []
        device['tool']('modbus', 'csr', '--role', role, '--name', 'test-' + role, *args)
        leaf = sign_csr(device['modbus'] / (role + '.csr'), tmp_path / (role + '.crt'), authority,
                        role='client' if role == 'master' else 'server', ips=['127.0.0.1'] if role == 'slave' else [])
        device['tool']('modbus', 'identity-import', '--role', role, '--cert', leaf,
                       '--chain', authority['intermediate'])
    settings = pki.read_config(device['config'])
    for service in pki.pending_services(settings):
        pki.pending_path(settings, service).unlink()
    device.update(settings=settings, authority=authority)
    return device


def install(material, crl):
    return crl_store.import_crls(material['settings'], crl.public_bytes(serialization.Encoding.PEM),
                                 material['authority']['intermediate'].read_bytes())


def status(material, role='master'):
    return crl_store.certificate_status((material['modbus'] / (role + '.crt')).read_bytes(),
                                        material['roots'], material['settings']['crl_file'])


def test_valid_crl_and_atomic_rollback_floor(material):
    assert status(material)['revocationStatus'] == 'unavailable'
    crl = signed_crl(material['authority'], 2)
    install(material, crl)
    assert status(material)['revocationStatus'] == 'good'
    assert pki.pending_services(material['settings']) == ['tems']
    # DER input and exact same-number retry are idempotent.
    crl_store.import_crls(material['settings'], crl.public_bytes(serialization.Encoding.DER))
    previous = material['settings']['crl_file'].read_bytes()
    with pytest.raises(ValueError, match='rollback'):
        install(material, signed_crl(material['authority'], 1))
    with pytest.raises(ValueError, match='conflicting'):
        install(material, signed_crl(material['authority'], 2, revoked=[999]))
    assert material['settings']['crl_file'].read_bytes() == previous


def test_expired_crl_allows_other_certificates_but_rejects_revoked(material):
    serial = x509.load_pem_x509_certificate((material['modbus'] / 'master.crt').read_bytes()).serial_number
    install(material, signed_crl(material['authority'], revoked=[serial], expired=True))
    assert status(material)['revocationStatus'] == 'revoked'
    assert status(material, 'slave')['revocationStatus'] == 'stale'
    material['tool']('modbus', 'check', '--role', 'master', success=False)
    material['tool']('modbus', 'check', '--role', 'slave')
    with pytest.raises(ValueError, match='removes'):
        install(material, signed_crl(material['authority'], 2))


def test_invalid_crl_does_not_replace_valid_store(material, tmp_path):
    install(material, signed_crl(material['authority']))
    previous = material['settings']['crl_file'].read_bytes()
    foreign = make_ca(tmp_path / 'foreign')
    with pytest.raises(ValueError):
        crl_store.import_crls(material['settings'], signed_crl(foreign).public_bytes(serialization.Encoding.PEM),
                             foreign['intermediate'].read_bytes())
    with pytest.raises(ValueError, match='thisUpdate'):
        install(material, signed_crl(material['authority'], 2, future=True))
    encoded = bytearray(signed_crl(material['authority'], 2).public_bytes(serialization.Encoding.DER))
    encoded[-1] ^= 1
    with pytest.raises(ValueError, match='signature'):
        crl_store.import_crls(material['settings'], bytes(encoded))
    assert material['settings']['crl_file'].read_bytes() == previous


@pytest.fixture
def http(auth_app, material, monkeypatch):
    app = auth_app[0]
    config = sys.modules['config']
    config.INI_PATH = material['config']; config.STATE_DONE = 3; config.STATE_ERROR = -1
    app.config.update(MODBUS_CERT_DIR=str(material['modbus']), HTTPS_CERT_DIR=str(material['https']))
    module = types.ModuleType('routes.route_g3'); module.g3_bp = Blueprint('crl-test', __name__)
    monkeypatch.setitem(sys.modules, 'routes.route_g3', module)
    spec = importlib.util.spec_from_file_location('crl_test_routes', ROOT / 'exec/app/routes/route_cert.py')
    routes = importlib.util.module_from_spec(spec); spec.loader.exec_module(routes)
    app.register_blueprint(module.g3_bp)
    client = app.test_client(); credentials = login(client, 'admin').json
    return client, {'X-CSRF-Token': credentials['csrf_token']}, routes


def test_http_import_and_service_application(http, material, monkeypatch):
    client, headers, routes = http
    assert client.post('/api/cert/crls/import', data={}).status_code == 403  # CSRF
    crl = signed_crl(material['authority'])
    response = client.post('/api/cert/crls/import', headers=headers, data={
        'file': (io.BytesIO(crl.public_bytes(serialization.Encoding.PEM)), 'issuer.crl'),
        'chain': (io.BytesIO(material['authority']['intermediate'].read_bytes()), 'issuer.pem')})
    assert response.status_code == 200
    assert client.get('/api/cert/crls').json['data']['pending'] == ['tems']
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return types.SimpleNamespace(returncode=0, stderr='')
    monkeypatch.setattr(routes.subprocess, 'run', run)
    applied = client.post('/api/cert/https/apply', headers=headers)
    assert applied.status_code == 200
    assert applied.json['data']['services'] == {'tems': {'action': 'restart', 'status': 'success'}}
    assert len(calls) == 2 and 'tems.service' in calls[0]
    assert client.post('/api/cert/https/apply', headers=headers).json['data']['changed'] is False
    assert len(calls) == 2


def test_apply_partial_failure_keeps_only_failed_service(http, material, monkeypatch):
    client, headers, routes = http
    for service in ('nginx', 'tems'):
        pki.mark_pending(material['settings'], service, 'test')
    monkeypatch.setattr(routes, '_https_pki', lambda *a, **kw: dict(applied=True))
    monkeypatch.setattr(routes.subprocess, 'run', lambda *a, **kw: types.SimpleNamespace(returncode=1, stderr='denied'))
    response = client.post('/api/cert/https/apply', headers=headers)
    assert response.status_code == 503
    assert response.json['data']['services']['nginx']['status'] == 'success'
    assert response.json['data']['pending'] == ['tems']


@pytest.fixture
def tls_server(material, tmp_path):
    """Use production transport/identity with a real Python TLS client."""
    source = tmp_path / 'server.c'
    source.write_text(r'''
#include "modbus_transport.h"
#include <openssl/ssl.h>
#include <stdarg.h>
#include <stdio.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <unistd.h>
static sysPara config = {1};
sysPara *SysConf_GetInfo(void) { return &config; }
void Modbus_Peers_Start(int enabled) { (void)enabled; }
void Modbus_Peers_Add(int fd, int server, SSL *ssl) { (void)fd; (void)server; (void)ssl; }
void Modbus_Peers_Remove(int fd) { (void)fd; }
void dzlog(const char *f, size_t fl, const char *fn, size_t fnl, long line, int level, const char *fmt, ...) {
    (void)f; (void)fl; (void)fn; (void)fnl; (void)line; (void)level;
    va_list args; va_start(args, fmt); vfprintf(stderr, fmt, args); va_end(args);
}
int main(void) {
    if (Modbus_Server_Init() != 0) return 2;
    int listener = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in a = {0}; a.sin_family = AF_INET; a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (bind(listener, (struct sockaddr *)&a, sizeof(a)) || listen(listener, 1)) return 3;
    socklen_t size = sizeof(a); getsockname(listener, (struct sockaddr *)&a, &size);
    printf("%d\n", ntohs(a.sin_port)); fflush(stdout);
    int peer = accept(listener, NULL, NULL); close(listener);
    int result = Modbus_Server_Attach(peer);
    printf("%s\n", result == 0 ? "accepted" : "rejected"); fflush(stdout);
    Modbus_Close(peer);
    return 0;
}
''')
    header = tmp_path / 'config.h'
    header.write_text('#define _GNU_SOURCE\n#define APPCONF_H_\n'
                      'typedef unsigned char INT8U;\ntypedef struct { INT8U modbus_tls_enabled; } sysPara;\n'
                      'sysPara *SysConf_GetInfo(void);\n')
    executable = tmp_path / 'tls-server'
    subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror', '-Wno-deprecated-declarations',
                    '-DMODBUS_WITH_TEE=0', '-I' + str(ROOT / 'logger/lib'), '-include', str(header),
                    '-DMODBUS_TLS_SERVER_CERT="' + str(material['modbus'] / 'slave.crt') + '"',
                    str(source), str(ROOT / 'logger/lib/modbus_transport.c'), str(ROOT / 'logger/lib/modbus_identity.c'),
                    '-lssl', '-lcrypto', '-lpthread', '-o', str(executable)], check=True, capture_output=True)
    return executable


@pytest.mark.parametrize('protocol', [ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_3])
@pytest.mark.parametrize('expired,revoked', [(False, False), (False, True), (True, False), (True, True)])
def test_production_tls_checks_crl_even_when_expired(material, tls_server, expired, revoked, protocol):
    cert = x509.load_pem_x509_certificate((material['modbus'] / 'master.crt').read_bytes())
    install(material, signed_crl(material['authority'], revoked=[cert.serial_number] if revoked else [], expired=expired))
    process = subprocess.Popen([str(tls_server)], env=material['env'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        port = process.stdout.readline().strip()
        assert port.isdigit(), process.stderr.read()
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.maximum_version = protocol
        ctx.load_verify_locations(str(material['roots']))
        ctx.load_cert_chain(str(material['modbus'] / 'master.crt'), str(material['modbus'] / 'master.key'))
        try:
            with socket.create_connection(('127.0.0.1', int(port)), timeout=5) as raw:
                with ctx.wrap_socket(raw, server_hostname='127.0.0.1'):
                    pass
        except ssl.SSLError:
            assert revoked
        out, err = process.communicate(timeout=10)
        assert process.returncode == 0, err
        assert ('rejected' if revoked else 'accepted') in out, err
        if revoked:
            assert 'certificate revoked' in err.lower()
        if expired:
            assert 'CRL expired' in err
    finally:
        if process.poll() is None:
            process.kill(); process.communicate()


def test_certificate_inventory_reports_revoked_stale_and_pending(security_app, material, monkeypatch):
    from routes import route_security
    app = security_app[0]
    monkeypatch.setattr(sys.modules['config'], 'INI_PATH', material['config'])
    app.config.update(MODBUS_CERT_DIR=str(material['modbus']), HTTPS_CERT_DIR=str(material['https']))
    monkeypatch.setattr(route_security, '_certificate_private_key_check', lambda item: (True, 'VERIFIED'))
    serial = x509.load_pem_x509_certificate((material['modbus'] / 'master.crt').read_bytes()).serial_number
    install(material, signed_crl(material['authority'], revoked=[serial], expired=True))
    client = app.test_client(); login(client, 'admin')
    response = client.get('/api/security/certificates')
    assert response.status_code == 200
    rows = {row['role']: row for row in response.json['data']}
    assert rows['master']['revocationStatus'] == 'revoked'
    assert rows['master']['chainVerified'] is True
    assert rows['master']['applyPending'] is True
    assert rows['master']['status'] == 'invalid'
    assert rows['slave']['revocationStatus'] == 'stale'
    assert rows['ca-root']['revocationStatus'] == 'not_applicable'


def test_crl_http_requires_admin_and_rejects_bad_upload(http, material):
    client, headers, routes = http
    response = client.post('/api/cert/crls/import', headers=headers,
                           data={'file': (io.BytesIO(b'not a CRL'), 'bad.pem')})
    assert response.status_code == 422
    assert not material['settings']['crl_file'].exists()
    visitor = client.application.test_client()
    credentials = login(visitor).json
    assert visitor.get('/api/cert/crls').status_code == 403
    assert visitor.post('/api/cert/crls/import', headers={'X-CSRF-Token': credentials['csrf_token']}).status_code == 403


def test_same_issuer_name_and_serial_from_another_ca_does_not_revoke(material, tmp_path):
    foreign = make_ca(tmp_path / 'same-name-ca')
    roots = material['roots']
    pki.import_roots(roots, roots.read_bytes() + foreign['root'].read_bytes())
    install(material, signed_crl(material['authority']))
    serial = x509.load_pem_x509_certificate((material['modbus'] / 'master.crt').read_bytes()).serial_number
    crl_store.import_crls(material['settings'], signed_crl(foreign, revoked=[serial]).public_bytes(serialization.Encoding.PEM),
                          foreign['intermediate'].read_bytes())
    assert status(material)['revocationStatus'] == 'good'


def test_optional_root_crl_rejects_revoked_intermediate(material):
    ca = material['authority']
    root = x509.load_pem_x509_certificate(ca['root'].read_bytes())
    key = serialization.load_pem_private_key(ca['root_key'].read_bytes(), None)
    issuer = x509.load_pem_x509_certificate(ca['intermediate'].read_bytes())
    now = datetime.now(timezone.utc)
    crl = (x509.CertificateRevocationListBuilder().issuer_name(root.subject)
           .last_update(now - timedelta(days=1)).next_update(now + timedelta(days=7))
           .add_extension(x509.CRLNumber(1), False)
           .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), False)
           .add_revoked_certificate(x509.RevokedCertificateBuilder().serial_number(issuer.serial_number)
                                    .revocation_date(now - timedelta(days=1)).build())
           .sign(key, hashes.SHA256()))
    install(material, signed_crl(ca))
    crl_store.import_crls(material['settings'], crl.public_bytes(serialization.Encoding.PEM))
    assert status(material)['revocationStatus'] == 'revoked'
    assert status(material, 'slave')['revocationStatus'] == 'revoked'


def test_deployment_crl_only_restart_is_not_blocked_by_local_revocation(material, monkeypatch):
    from provisioning.device import DeviceProvisioner
    tool = DeviceProvisioner(ROOT / 'exec/app', material['config'], 'file',
                             material['modbus'], material['https'], material['env']['MODBUS_TEE_IDENTITY'])
    serial = x509.load_pem_x509_certificate((material['modbus'] / 'master.crt').read_bytes()).serial_number
    install(material, signed_crl(material['authority'], revoked=[serial]))
    calls = []
    def run(args, timeout=180):
        calls.append(list(map(str, args)))
        assert args[0] == 'systemctl'
        if '--property=LoadState' in args:
            return 'loaded'
        if 'show' in args:
            return 'MODBUS_KEY_BACKEND=file LC_INI_PATH=' + str(material['config'])
        return ''
    monkeypatch.setattr(tool, 'run', run)
    response = tool.apply('tems.service')
    assert response['applied'] and not response['https_applied']
    assert ['systemctl', 'restart', 'tems.service'] in calls
    assert not pki.pending_services(material['settings'])
