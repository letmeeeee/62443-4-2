"""Certificate profiles used by the standalone CA server."""
from datetime import datetime, timedelta, timezone
import ipaddress
import re

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def now():
    return datetime.now(timezone.utc)


def pem(value):
    return value.public_bytes(serialization.Encoding.PEM)


def key_pem(key, password=None):
    encryption = serialization.BestAvailableEncryption(password.encode()) if password else serialization.NoEncryption()
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, encryption)


def text(value, field, limit=64):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit or any(ord(c) < 32 for c in value):
        raise ValueError(field + ' 长度或内容不合法')
    return value.strip()


def integer(value, low, high, field):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('%s 必须为 %d–%d 的整数' % (field, low, high))
    return value


def key_options(data):
    algorithm = data.get('algorithm', 'P-256')
    if algorithm not in ('P-256', 'RSA'):
        raise ValueError('algorithm 仅支持 P-256 或 RSA')
    bits = data.get('rsa_bits', 3072) if algorithm == 'RSA' else None
    if algorithm == 'RSA' and (type(bits) is not int or bits not in (2048, 3072, 4096)):
        raise ValueError('RSA 位数仅支持 2048、3072、4096')
    return algorithm, bits


def generate_key(algorithm, bits):
    if algorithm == 'P-256':
        return ec.generate_private_key(ec.SECP256R1())
    return rsa.generate_private_key(public_exponent=65537, key_size=bits)


def subject(data):
    attributes = [x509.NameAttribute(NameOID.COMMON_NAME, text(data.get('cn'), 'CN'))]
    for field, oid in [('organization', NameOID.ORGANIZATION_NAME), ('organization_unit', NameOID.ORGANIZATIONAL_UNIT_NAME)]:
        if data.get(field):
            attributes.append(x509.NameAttribute(oid, text(data[field], field)))
    if data.get('country'):
        country = data['country']
        if not isinstance(country, str) or not re.fullmatch('[A-Z]{2}', country):
            raise ValueError('country 使用两位大写国家代码，例如 CN')
        attributes.append(x509.NameAttribute(NameOID.COUNTRY_NAME, country))
    return x509.Name(attributes)


def usage(ca=False, rsa_tls=False):
    return x509.KeyUsage(True, False, rsa_tls, False, False, ca, ca, False, False)


def create_ca(data, password):
    algorithm, bits = key_options(data)
    days = integer(data.get('days', 3650), 365, 7300, 'CA 有效天数')
    owner = subject(data)
    key = generate_key(algorithm, bits)
    current = now()
    certificate = (x509.CertificateBuilder().subject_name(owner).issuer_name(owner).public_key(key.public_key())
                   .serial_number(x509.random_serial_number()).not_valid_before(current-timedelta(minutes=5))
                   .not_valid_after(current+timedelta(days=days))
                   .add_extension(x509.BasicConstraints(True, 0), True).add_extension(usage(ca=True), True)
                   .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), False)
                   .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), False)
                   .sign(key, hashes.SHA256()))
    return certificate, key, key_pem(key, password), algorithm, bits


def device_options(data):
    algorithm, bits = key_options(data)
    owner = subject(data)
    device_id = text(data.get('device_id'), '设备编号')
    profile = data.get('profile', 'goose')
    if profile not in ('goose', 'tls_server', 'tls_client'):
        raise ValueError('profile 仅支持 goose、tls_server、tls_client')
    if profile == 'goose' and algorithm != 'P-256':
        raise ValueError('GOOSE 身份必须使用 P-256；RSA 请用于 TLS 配置')
    days = integer(data.get('days', 365), 1, 825, '设备证书有效天数')
    names = []
    for field, kind in [('dns_names', 'dns'), ('ip_addresses', 'ip')]:
        entries = data.get(field, [])
        if not isinstance(entries, list) or len(entries) > 32:
            raise ValueError(field + ' 须为不超过 32 项的数组')
        for entry in entries:
            if kind == 'dns':
                entry = text(entry, 'DNS', 253)
                if not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', part) for part in entry.split('.')):
                    raise ValueError('DNS 名称格式错误')
                names.append(x509.DNSName(entry))
            else:
                if not isinstance(entry, str):
                    raise ValueError('IP 地址须为字符串')
                address = ipaddress.ip_address(entry)
                if address.is_unspecified or address.is_multicast:
                    raise ValueError('设备 IP 不能为未指定地址或组播地址')
                names.append(x509.IPAddress(address))
    if profile == 'goose' and names:
        raise ValueError('GOOSE 配置不需要 SAN，请清空 DNS/IP')
    if profile == 'tls_server' and not names:
        raise ValueError('TLS 服务器证书至少需要一个 DNS 或 IP SAN')
    return algorithm, bits, owner, device_id, profile, days, names


def issue_device(data, ca, ca_key, password):
    algorithm, bits, owner, device_id, profile, days, names = device_options(data)
    current = now()
    if not ca.not_valid_before_utc <= current < ca.not_valid_after_utc:
        raise ValueError('CA 已过期或尚未生效')
    if current + timedelta(days=days) > ca.not_valid_after_utc:
        raise ValueError('设备证书有效期不能超出 CA 有效期')
    key = generate_key(algorithm, bits)
    extensions = [(x509.BasicConstraints(False, None), True), (usage(rsa_tls=algorithm == 'RSA' and profile != 'goose'), True)]
    if profile != 'goose':
        purpose = ExtendedKeyUsageOID.SERVER_AUTH if profile == 'tls_server' else ExtendedKeyUsageOID.CLIENT_AUTH
        extensions.append((x509.ExtendedKeyUsage([purpose]), False))
    if names:
        extensions.append((x509.SubjectAlternativeName(names), False))
    request = x509.CertificateSigningRequestBuilder().subject_name(owner)
    builder = (x509.CertificateBuilder().subject_name(owner).issuer_name(ca.subject).public_key(key.public_key())
               .serial_number(x509.random_serial_number()).not_valid_before(max(current-timedelta(minutes=5), ca.not_valid_before_utc))
               .not_valid_after(current+timedelta(days=days)))
    for extension, critical in extensions:
        request = request.add_extension(extension, critical)
        builder = builder.add_extension(extension, critical)
    csr = request.sign(key, hashes.SHA256())
    if not csr.is_signature_valid:
        raise ValueError('自动生成 CSR 的签名校验失败')
    cert = (builder.add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), False)
            .sign(ca_key, hashes.SHA256()))
    if profile == 'goose' and len(cert.public_bytes(serialization.Encoding.DER)) + 198 > 1024:
        raise ValueError('GOOSE 证书超出握手长度限制，请缩短主题信息或使用 P-256 CA')
    return dict(device_id=device_id, profile=profile, algorithm=algorithm, rsa_bits=bits,
                serial=format(cert.serial_number, 'X'), cn=data['cn'].strip(), created_at=current.isoformat(),
                expires_at=cert.not_valid_after_utc.isoformat(), cert=pem(cert), csr=pem(csr),
                encrypted_key=key_pem(key, password))


def make_crl(ca, key, number, revoked):
    current = now()
    if current >= ca.not_valid_after_utc:
        raise ValueError('CA 已过期，不能生成有效 CRL')
    builder = (x509.CertificateRevocationListBuilder().issuer_name(ca.subject).last_update(current-timedelta(minutes=5))
               .next_update(min(current+timedelta(days=30), ca.not_valid_after_utc))
               .add_extension(x509.CRLNumber(number), False)
               .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), False))
    for row in revoked:
        item = (x509.RevokedCertificateBuilder().serial_number(int(row['serial'], 16))
                .revocation_date(datetime.fromisoformat(row['revoked_at']))
                .add_extension(x509.CRLReason(getattr(x509.ReasonFlags, row['reason'])), False).build())
        builder = builder.add_revoked_certificate(item)
    return pem(builder.sign(key, hashes.SHA256()))
