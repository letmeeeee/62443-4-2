"""In-process certificate backend bundled into the Windows executable."""
from datetime import datetime, timedelta
import ipaddress
from pathlib import Path
import shutil
import tempfile

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def inspect(path):
    cert = x509.load_pem_x509_certificate(Path(path).read_bytes(), default_backend())
    try:
        san = str(cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value)
    except x509.ExtensionNotFound:
        san = '(无 SAN)'
    before = getattr(cert, 'not_valid_before_utc', None)
    after = getattr(cert, 'not_valid_after_utc', None)
    if before is None:
        before, after = cert.not_valid_before, cert.not_valid_after
    return 'subject={}\nissuer={}\nnotBefore={} UTC\nnotAfter={} UTC\nSHA256={}\nSAN={}'.format(
        cert.subject.rfc4514_string(), cert.issuer.rfc4514_string(), before, after,
        cert.fingerprint(hashes.SHA256()).hex().upper(), san)


def generate(parent, host, device=True):
    # Reuse input validation without importing any OpenSSL executable.
    from .certificates import server_san
    server_san(host)
    host = host.strip()
    try:
        name = x509.IPAddress(ipaddress.ip_address(host))
    except ValueError:
        name = x509.DNSName(host)
    folder = Path(tempfile.mkdtemp(prefix='modbus-device-certs-' if device else 'modbus-certs-', dir=parent))
    folder.chmod(0o700)
    backend = default_backend()
    now = datetime.utcnow()

    def key(role):
        result = rsa.generate_private_key(public_exponent=65537, key_size=3072 if device else 2048, backend=backend)
        path = folder / (role + '.key')
        path.touch(mode=0o600)
        path.write_bytes(result.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                             serialization.NoEncryption()))
        return result

    def subject(text):
        return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, text)])

    def builder(owner, issuer, public, ca=False):
        return (x509.CertificateBuilder().subject_name(owner).issuer_name(issuer).public_key(public)
                .serial_number(x509.random_serial_number()).not_valid_before(now).not_valid_after(now + timedelta(days=365))
                .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
                .add_extension(x509.SubjectKeyIdentifier.from_public_key(public), critical=False))

    def save(role, certificate):
        (folder / (role + '.crt')).write_bytes(certificate.public_bytes(serialization.Encoding.PEM))

    try:
        ca_key = key('ca') if not device else None
        ca_subject = subject('Modbus-GUI-Demo-CA')
        if ca_key:
            ca = (builder(ca_subject, ca_subject, ca_key.public_key(), ca=True)
                  .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
                  .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
                  .sign(ca_key, hashes.SHA256(), backend))
            save('ca', ca)
        for role, purpose in [('server', ExtendedKeyUsageOID.SERVER_AUTH), ('client', ExtendedKeyUsageOID.CLIENT_AUTH)]:
            identity = key(role)
            owner = subject('Modbus-GUI-' + role)
            cert = builder(owner, owner if device else ca_subject, identity.public_key())
            cert = cert.add_extension(x509.ExtendedKeyUsage([purpose]), critical=False)
            if not device:
                cert = (cert.add_extension(x509.KeyUsage(True, False, True, False, False, False, False, False, False), critical=True)
                        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False))
            if role == 'server':
                cert = cert.add_extension(x509.SubjectAlternativeName([name, x509.DNSName('localhost')]), critical=False)
            save(role, cert.sign(identity if device else ca_key, hashes.SHA256(), backend))
        return folder
    except BaseException:
        shutil.rmtree(folder)
        raise
