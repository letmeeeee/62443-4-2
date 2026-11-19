import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from . import crypto as c


class CertificateTests(unittest.TestCase):
    def setUp(self):
        self.ca, self.ca_key, self.encrypted, self.crl = c.create_ca('GOOSE Test CA', 'test-password-123')
        self.key, self.csr = c.generate_identity('LC400-001-goose')

    def test_p256_roundtrip_and_strict_crl_verification(self):
        cert = c.issue(self.csr, self.ca, self.ca_key)
        self.assertEqual(c.public(cert.public_key()), c.public(self.key.public_key()))
        self.assertIsInstance(cert.public_key().curve, ec.SECP256R1)
        self.assertFalse(cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca)
        ku = cert.extensions.get_extension_for_class(x509.KeyUsage).value
        self.assertTrue(ku.digital_signature)
        self.assertFalse(ku.key_cert_sign)
        loaded = c.load_ca(c.pem(self.ca), self.encrypted, 'test-password-123')
        self.assertEqual(c.public(loaded[1].public_key()), c.public(self.ca_key.public_key()))
        self.assertEqual(c.public(c.load_csr(c.pem(self.csr)).public_key()), c.public(self.key.public_key()))
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for filename, value in [('ca.pem', self.ca), ('crl.pem', self.crl), ('cert.pem', cert)]:
                c.export_new(folder / filename, c.pem(value))
            result = subprocess.run(['openssl', 'verify', '-x509_strict', '-crl_check_all', '-CAfile', str(folder/'ca.pem'),
                                     '-CRLfile', str(folder/'crl.pem'), str(folder/'cert.pem')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_rsa_ca_can_issue_p256_identity(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=c.BACKEND)
        now = datetime.utcnow()
        ca = (x509.CertificateBuilder().subject_name(c.name('SCADA CA')).issuer_name(c.name('SCADA CA'))
              .public_key(key.public_key()).serial_number(123).not_valid_before(now-timedelta(days=1))
              .not_valid_after(now+timedelta(days=1000))
              .add_extension(x509.BasicConstraints(True, None), True).add_extension(c.usage(True), True)
              .sign(key, hashes.SHA256(), c.BACKEND))
        c.load_ca(c.pem(ca), c.private_pem(key))
        cert = c.issue(self.csr, ca, key)
        self.assertIsInstance(cert.public_key(), ec.EllipticCurvePublicKey)
        from cryptography.hazmat.primitives.asymmetric import padding
        key.public_key().verify(cert.signature, cert.tbs_certificate_bytes, padding.PKCS1v15(), hashes.SHA256())

    def test_reject_wrong_ca_key_password_or_non_ca(self):
        with self.assertRaises(ValueError):
            c.load_ca(c.pem(self.ca), self.encrypted, 'wrong-password')
        with self.assertRaises(ValueError):
            c.load_ca(c.pem(self.ca), c.private_pem(self.key))
        cert = c.issue(self.csr, self.ca, self.ca_key)
        with self.assertRaises(ValueError):
            c.load_ca(c.pem(cert), c.private_pem(self.key))

    def test_reject_rsa_and_wrong_curve_csr(self):
        for key in [rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=c.BACKEND),
                    ec.generate_private_key(ec.SECP384R1(), c.BACKEND)]:
            csr = x509.CertificateSigningRequestBuilder().subject_name(c.name('device')).sign(key, hashes.SHA256(), c.BACKEND)
            with self.assertRaises(ValueError):
                c.load_csr(c.pem(csr))

    def test_reject_privilege_extensions_and_bad_signature(self):
        csr = (x509.CertificateSigningRequestBuilder().subject_name(c.name('device'))
               .add_extension(x509.BasicConstraints(True, None), True).sign(self.key, hashes.SHA256(), c.BACKEND))
        with self.assertRaises(ValueError):
            c.load_csr(c.pem(csr))
        der = bytearray(self.csr.public_bytes(serialization.Encoding.DER))
        der[-1] ^= 1
        altered = x509.load_der_x509_csr(bytes(der), c.BACKEND)
        with self.assertRaises(ValueError):
            c.load_csr(c.pem(altered))

    def test_expiry_and_input_bounds(self):
        for days in (0, 826, 4000):
            with self.assertRaises(ValueError):
                c.issue(self.csr, self.ca, self.ca_key, days)
        for cn in ('', 'a\nb', 'a'*65):
            with self.assertRaises(ValueError):
                c.generate_identity(cn)
        with self.assertRaises(ValueError):
            c.create_ca('CA', 'short')

    def test_exports_permissions_no_overwrite_and_no_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'enc.key'
            c.export_new(target, c.private_pem(self.key), private=True)
            self.assertEqual(c.public(serialization.load_pem_private_key(target.read_bytes(), None, c.BACKEND).public_key()),
                             c.public(self.key.public_key()))
            if os.name == 'posix':
                self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            original = target.read_bytes()
            with self.assertRaises(FileExistsError):
                c.export_new(target, b'overwrite', private=True)
            link = Path(tmp) / 'link'
            if os.name == 'posix':
                link.symlink_to(target)
                with self.assertRaises(FileExistsError):
                    c.export_new(link, b'overwrite')
            self.assertEqual(target.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
