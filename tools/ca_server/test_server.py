import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
import zipfile

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from .app import create_app, initialize_admin
from . import pki


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / 'data'
        initialize_admin(self.directory, 'admin-password-123')
        self.app = create_app(self.directory)
        self.app.testing = True
        self.client = self.app.test_client()
        self.token = self.client.get('/api/session').json['csrf_token']
        result = self.post('/api/login', dict(password='admin-password-123'))
        self.assertEqual(result.status_code, 200)
        self.token = result.json['csrf_token']

    def post(self, url, data=None, extra=None):
        return self.client.post(url, json=data or {}, headers=dict({'X-CSRF-Token': self.token}, **(extra or {})))

    def ca(self, algorithm='P-256'):
        response = self.post('/api/ca', dict(cn='Test CA', algorithm=algorithm, rsa_bits=2048, password='ca-password-1234'))
        self.assertEqual(response.status_code, 201, response.json)
        self.assertEqual(self.post('/api/ca/unlock', dict(password='ca-password-1234')).status_code, 200)

    def issue(self, algorithm='P-256', profile='goose', request_id=None, **options):
        data = dict(device_id='LC400-001', cn='LC400-001-'+profile, profile=profile, algorithm=algorithm, rsa_bits=2048)
        data.update(options)
        return self.post('/api/devices', data, {'Idempotency-Key': request_id or str(uuid.uuid4())})

    def export(self, identity, **options):
        response = self.post('/api/devices/'+identity+'/export', dict(key_format='plain', confirm_plaintext=True, **options))
        self.assertEqual(response.status_code, 200, response.json)
        archive = zipfile.ZipFile(io.BytesIO(response.data))
        return {name:archive.read(name) for name in archive.namelist()}

    def test_auth_csrf_html_and_session_invalidation(self):
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.get('/api/ca').status_code, 401)
        self.assertEqual(anonymous.post('/api/ca', json={}).status_code, 403)
        self.assertEqual(self.client.post('/api/ca', json={}).status_code, 403)
        page = self.client.get('/')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'/static/app.js', page.data)
        self.assertIn("script-src 'self'", page.headers['Content-Security-Policy'])
        cookie = self.client.get_cookie('lc400_ca_session').value
        self.post('/api/logout')
        anonymous.set_cookie('lc400_ca_session', cookie)
        self.assertEqual(anonymous.get('/api/ca').status_code, 401)

    def test_create_ca_no_overwrite_and_encrypted_storage(self):
        self.ca()
        self.assertEqual(self.post('/api/ca', dict(password='ca-password-1234')).status_code, 409)
        with sqlite3.connect(self.directory/'ca.sqlite3') as conn:
            stored = conn.execute('SELECT encrypted_key FROM ca').fetchone()[0]
        self.assertIn(b'ENCRYPTED PRIVATE KEY', stored)
        with self.assertRaises(TypeError):
            serialization.load_pem_private_key(stored, None)
        with self.assertRaises(ValueError):
            initialize_admin(self.directory, 'different-password')

    def test_algorithms_and_certificate_csr_private_key_match(self):
        self.ca('RSA')
        for algorithm, profile in [('P-256','goose'), ('P-256','tls_server'), ('RSA','tls_client'), ('RSA','tls_server')]:
            with self.subTest(algorithm=algorithm, profile=profile):
                kwargs = {'dns_names':['ems.example.com'], 'ip_addresses':['192.168.3.100']} if profile == 'tls_server' else {}
                response = self.issue(algorithm, profile, **kwargs)
                self.assertEqual(response.status_code, 201, response.json)
                bundle = self.export(response.json['id'])
                key = serialization.load_pem_private_key(bundle['enc.key'], None)
                cert = x509.load_pem_x509_certificate(bundle['enc.crt'])
                csr = x509.load_pem_x509_csr(bundle['device.csr.pem'])
                self.assertTrue(csr.is_signature_valid)
                def pub(value):
                    return value.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
                self.assertEqual(pub(key), pub(csr))
                self.assertEqual(pub(key), pub(cert))
                self.assertIsInstance(key, rsa.RSAPrivateKey if algorithm == 'RSA' else ec.EllipticCurvePrivateKey)
                self.assertFalse(cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca)
                self.verify(bundle)

    def verify(self, bundle, valid=True):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            for name, content in bundle.items():
                (folder/name).write_bytes(content)
            result = subprocess.run(['openssl', 'verify', '-x509_strict', '-crl_check_all', '-CAfile', str(folder/'ca-roots.crt'),
                                     '-CRLfile', str(folder/'crls.pem'), str(folder/'enc.crt')], capture_output=True)
            self.assertEqual(result.returncode == 0, valid, result.stdout+result.stderr)

    def test_goose_backend_accepts_four_exported_files(self):
        self.ca()
        response = self.issue()
        self.assertEqual(response.status_code, 201, response.json)
        bundle = self.export(response.json['id'])
        self.verify(bundle)
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'exec/app'))
        try:
            from script.goose_pki import GoosePKI
            manager = GoosePKI(self.directory/'device-import')
            batch = None
            for part, name in [('identity','enc.crt'), ('key','enc.key'), ('ca','ca-roots.crt'), ('crl','crls.pem')]:
                batch = manager.upload(part, bundle[name], batch)['batch_id']
            calls = []
            self.assertEqual(manager.apply(batch, calls.append)['status'], 'applied')
            self.assertEqual(calls, ['goose'])
        finally:
            sys.path.pop(0)

    def test_idempotency_and_parameter_reuse_conflict(self):
        self.ca()
        key = str(uuid.uuid4())
        first, second = self.issue(request_id=key), self.issue(request_id=key)
        self.assertEqual(first.status_code, 201, first.json)
        self.assertEqual(second.status_code, 200, second.json)
        self.assertEqual(first.json['id'], second.json['id'])
        self.assertEqual(self.issue(request_id=key, cn='other').status_code, 409)
        self.assertEqual(self.client.get('/api/devices').json['total'], 1)

    def test_profile_validation_and_lock_expiration(self):
        self.ca()
        for options in [dict(algorithm='RSA'), dict(algorithm='bad'), dict(days=0), dict(days=826),
                        dict(profile='tls_server'), dict(profile='tls_server', dns_names=['bad host']), dict(rsa_bits=True, algorithm='RSA', profile='tls_client')]:
            self.assertEqual(self.issue(**options).status_code, 422, options)
        self.app.extensions['ca_vault']['deadline'] = time.monotonic()-1
        self.assertEqual(self.issue().status_code, 423)
        self.assertIsNone(self.app.extensions['ca_vault']['password'])
        self.assertEqual(self.post('/api/ca/unlock', dict(password='wrong-password-123')).status_code, 422)

    def test_private_export_reencrypts_without_exposing_ca_password(self):
        self.ca()
        response = self.issue()
        identity = response.json['id']
        uri = '/api/devices/'+identity+'/export'
        self.assertEqual(self.post(uri, dict(key_format='plain')).status_code, 422)
        self.assertEqual(self.post(uri, dict(export_password='ca-password-1234')).status_code, 422)
        response = self.post(uri, dict(export_password='export-password-123'))
        self.assertEqual(response.status_code, 200, response.json)
        data = zipfile.ZipFile(io.BytesIO(response.data)).read('enc.key')
        serialization.load_pem_private_key(data, b'export-password-123')
        with self.assertRaises(ValueError):
            serialization.load_pem_private_key(data, b'ca-password-1234')
        public = self.client.get('/api/devices').data + self.client.get('/api/events').data
        for secret in (b'PRIVATE KEY', b'ca-password-1234', b'export-password-123'):
            self.assertNotIn(secret, public)
        self.post('/api/ca/lock')
        self.assertEqual(self.post(uri, dict(key_format='plain', confirm_plaintext=True)).status_code, 423)

    def test_revoke_refresh_crl_and_block_private_export(self):
        self.ca()
        item = self.issue().json
        bundle = self.export(item['id'])
        response = self.post('/api/devices/'+item['id']+'/revoke', dict(reason='key_compromise'))
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['crl_number'], 2)
        bundle['crls.pem'] = self.client.get('/api/ca/crl').data
        self.verify(bundle, valid=False)
        self.assertEqual(self.post('/api/devices/'+item['id']+'/export', dict(key_format='plain', confirm_plaintext=True)).status_code, 422)
        self.assertEqual(self.post('/api/ca/crl/refresh').json['crl_number'], 3)
        crl = x509.load_pem_x509_crl(self.client.get('/api/ca/crl').data)
        self.assertEqual(crl.get_revoked_certificate_by_serial_number(int(item['serial'],16)).serial_number, int(item['serial'],16))

    def test_restart_preserves_records_and_starts_locked(self):
        self.ca()
        identity = self.issue().json['id']
        restarted = create_app(self.directory)
        client = restarted.test_client()
        csrf = client.get('/api/session').json['csrf_token']
        response = client.post('/api/login', json=dict(password='admin-password-123'), headers={'X-CSRF-Token':csrf})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(client.get('/api/ca').json['unlocked'])
        self.assertEqual(client.get('/api/devices').json['items'][0]['id'], identity)
        self.assertEqual(client.get('/api/devices/'+identity+'/csr').status_code, 200)

    def test_failed_persistence_does_not_publish_unrecorded_certificate(self):
        self.ca()
        with sqlite3.connect(self.directory/'ca.sqlite3') as conn:
            conn.execute("CREATE TRIGGER reject_issue BEFORE INSERT ON certificates BEGIN SELECT RAISE(ABORT,'test'); END")
        self.assertEqual(self.issue().status_code, 500)
        self.assertEqual(self.client.get('/api/devices').json['total'], 0)


if __name__ == '__main__':
    unittest.main()
