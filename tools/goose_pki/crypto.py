"""GOOSE certificate operations, independent of TLS CA policies."""
from datetime import datetime, timedelta
import os
from pathlib import Path
import re

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID

BACKEND = default_backend()


def pem(value):
    return value.public_bytes(serialization.Encoding.PEM)


def public(key):
    return key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


def export_new(path, data, private=False):
    """Never overwrite an existing identity or follow an existing symlink."""
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600 if private else 0o644)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        Path(path).unlink()
        raise


def name(cn):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_. -]{0,63}', cn):
        raise ValueError('CN 须为 1–64 位字母、数字、空格或 _.-，并以字母或数字开头')
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def require_p256(key):
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError('GOOSE 身份必须使用 prime256v1（P-256）公钥')


def usage(ca=False):
    return x509.KeyUsage(True, False, False, False, False, ca, ca, False, False)


def generate_identity(cn):
    subject = name(cn)
    key = ec.generate_private_key(ec.SECP256R1(), BACKEND)
    csr = x509.CertificateSigningRequestBuilder().subject_name(subject).sign(key, hashes.SHA256(), BACKEND)
    return key, csr


def load_csr(data):
    if not re.fullmatch(rb'\s*-----BEGIN CERTIFICATE REQUEST-----[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE REQUEST-----\s*', data):
        raise ValueError('请选择一份 PEM CSR')
    csr = x509.load_pem_x509_csr(data, BACKEND)
    require_p256(csr.public_key())
    if not csr.is_signature_valid or csr.signature_hash_algorithm.name != 'sha256':
        raise ValueError('CSR 必须具有有效的 ECDSA/SHA-256 签名')
    cn = csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    if len(cn) != 1 or len(csr.subject) != 1:
        raise ValueError('CSR 主题须仅含一个 CN')
    name(cn[0].value)
    if len(csr.extensions):
        raise ValueError('此工具仅签发不含请求扩展的 GOOSE CSR；证书用途由工具固定设置')
    return csr


def check_ca(cert):
    current = datetime.utcnow()
    if not cert.not_valid_before <= current < cert.not_valid_after:
        raise ValueError('签发 CA 尚未生效或已经过期')
    if not cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
        raise ValueError('签发证书不具有 CA 权限')
    if not cert.extensions.get_extension_for_class(x509.KeyUsage).value.key_cert_sign:
        raise ValueError('CA 不具有证书签发用途')


def load_ca(cert_data, key_data, password=''):
    if cert_data.count(b'-----BEGIN CERTIFICATE-----') != 1:
        raise ValueError('请选择单张签发 CA 证书；中间 CA 的上级链需另外保留')
    cert = x509.load_pem_x509_certificate(cert_data, BACKEND)
    key = serialization.load_pem_private_key(key_data, password.encode('utf-8') if password else None, BACKEND)
    if not isinstance(key, (ec.EllipticCurvePrivateKey, rsa.RSAPrivateKey)):
        raise ValueError('仅支持 EC 或 RSA 签发 CA')
    if isinstance(key, rsa.RSAPrivateKey) and key.key_size < 2048:
        raise ValueError('RSA CA 至少需要 2048 位')
    if public(cert.public_key()) != public(key.public_key()):
        raise ValueError('CA 私钥与证书不匹配')
    check_ca(cert)
    return cert, key


def issue(csr, ca, key, days=365):
    csr = load_csr(pem(csr))
    check_ca(ca)
    if public(ca.public_key()) != public(key.public_key()):
        raise ValueError('CA 私钥与证书不匹配')
    if not 1 <= days <= 825:
        raise ValueError('证书有效期须为 1–825 天')
    current = datetime.utcnow()
    end = current + timedelta(days=days)
    if end > ca.not_valid_after:
        raise ValueError('设备证书有效期超出 CA 有效期，请缩短天数')
    cert = (x509.CertificateBuilder().subject_name(csr.subject).issuer_name(ca.subject)
            .public_key(csr.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(max(current - timedelta(minutes=5), ca.not_valid_before)).not_valid_after(end)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
            .add_extension(usage(), True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(csr.public_key()), False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), False)
            .sign(key, hashes.SHA256(), BACKEND))
    if len(cert.public_bytes(serialization.Encoding.DER)) + 198 > 1024:
        raise ValueError('证书超过 GSEC1 握手长度限制，请使用更短 CA 名称或 EC CA')
    return cert


def create_ca(cn, password):
    if len(password) < 12:
        raise ValueError('新 CA 私钥保护口令至少 12 位')
    key = ec.generate_private_key(ec.SECP256R1(), BACKEND)
    subject = name(cn)
    current = datetime.utcnow()
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(current - timedelta(minutes=5)).not_valid_after(current + timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
            .add_extension(usage(True), True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), False)
            .sign(key, hashes.SHA256(), BACKEND))
    crl = (x509.CertificateRevocationListBuilder().issuer_name(subject)
           .last_update(current - timedelta(minutes=5)).next_update(current + timedelta(days=30))
           .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), False)
           .add_extension(x509.CRLNumber(1), False).sign(key, hashes.SHA256(), BACKEND))
    encrypted = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                 serialization.BestAvailableEncryption(password.encode('utf-8')))
    return cert, key, encrypted, crl


def private_pem(key):
    # Device importer requires unencrypted PKCS#8 PEM; CA keys use encryption.
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def describe(cert):
    return dict(subject=cert.subject.rfc4514_string(), issuer=cert.issuer.rfc4514_string(),
                public_key='EC prime256v1 / P-256', serial=format(cert.serial_number, 'X'),
                expires_utc=str(cert.not_valid_after), sha256=cert.fingerprint(hashes.SHA256()).hex())
