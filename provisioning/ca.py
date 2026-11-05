"""Encrypted offline root/issuing CA with transactional issuance and CRL ledger."""
import contextlib
import getpass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from .common import ROLES, atomic_write, digest, json_bytes, public_package, read_file


def now():
    return datetime.now(timezone.utc)


def pem(cert):
    return cert.public_bytes(serialization.Encoding.PEM)


def public(key):
    return key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


def key_usage(ca=False):
    return x509.KeyUsage(True, False, not ca, False, False, ca, ca, False, False)


def name(cn):
    if not isinstance(cn, str) or not 1 <= len(cn) <= 128 or any(ord(c) < 32 for c in cn):
        raise ValueError('CA 名称长度应为 1–128 且不能含控制字符')
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def builder(subject, issuer, key, days):
    return (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer.subject)
            .public_key(key).serial_number(x509.random_serial_number())
            .not_valid_before(now() - timedelta(minutes=5))
            .not_valid_after(min(now() + timedelta(days=days), issuer.not_valid_after_utc)))


def validate_csr(data, role):
    if role not in ROLES:
        raise ValueError('未知签发角色')
    if len(data) > 1024 * 1024:
        raise ValueError('CSR 过大')
    if not re.fullmatch(rb'\s*-----BEGIN CERTIFICATE REQUEST-----[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE REQUEST-----\s*', data):
        raise ValueError('只接受单份 PEM CSR，不接受附加私钥或其他内容')
    csr = x509.load_pem_x509_csr(data)
    if not csr.is_signature_valid:
        raise ValueError('CSR 自身签名无效')
    if csr.signature_hash_algorithm.name not in ('sha256', 'sha384', 'sha512'):
        raise ValueError('CSR 必须使用 SHA-256 或更强签名')
    key = csr.public_key()
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 3072:
        raise ValueError('设备身份必须使用至少 RSA-3072 公钥')
    cn = csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    if len(cn) != 1 or len(csr.subject) != 1:
        raise ValueError('CSR 主题必须只含一个 CN')
    if role == 'https':
        if cn[0].value != 'logger':
            raise ValueError('HTTPS CN 必须为 logger')
    elif not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', cn[0].value):
        raise ValueError('Modbus CN 不符合设备身份命名规则')
    allowed = {x509.ExtensionOID.BASIC_CONSTRAINTS, x509.ExtensionOID.KEY_USAGE,
               x509.ExtensionOID.EXTENDED_KEY_USAGE, x509.ExtensionOID.SUBJECT_ALTERNATIVE_NAME}
    sans = []
    for extension in csr.extensions:
        if extension.oid not in allowed:
            raise ValueError('CSR 包含不支持的扩展: ' + extension.oid.dotted_string)
        if isinstance(extension.value, x509.BasicConstraints) and extension.value.ca:
            raise ValueError('不能签发请求 CA 权限的设备 CSR')
        if isinstance(extension.value, x509.KeyUsage):
            ku = extension.value
            if not ku.digital_signature or ku.key_cert_sign or ku.crl_sign:
                raise ValueError('CSR 请求的密钥用途不合法')
        if isinstance(extension.value, x509.ExtendedKeyUsage):
            expected = ExtendedKeyUsageOID.CLIENT_AUTH if role == 'master' else ExtendedKeyUsageOID.SERVER_AUTH
            if set(extension.value) != {expected}:
                raise ValueError('CSR EKU 与所选角色不一致')
        if isinstance(extension.value, x509.SubjectAlternativeName):
            sans = list(extension.value)
    if len(sans) > 64:
        raise ValueError('SAN 数量过多')
    for san in sans:
        if isinstance(san, x509.IPAddress):
            if san.value.is_unspecified or san.value.is_multicast:
                raise ValueError('SAN 包含无效 IP')
        elif isinstance(san, x509.DNSName):
            if len(san.value) > 253 or not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', p) for p in san.value.split('.')):
                raise ValueError('SAN 包含无效 DNS 名称')
        else:
            raise ValueError('只支持 IP 和 DNS SAN')
    if role in ('slave', 'https') and not any(isinstance(s, x509.IPAddress) for s in sans):
        raise ValueError('从机和 HTTPS 证书必须包含 IP SAN')
    return csr, sans


class CertificateAuthority:
    def __init__(self, directory):
        self.directory = Path(directory).absolute()
        self.database = self.directory / 'ledger.sqlite3'

    @classmethod
    def initialize(cls, directory, password, organization='LC400 Enterprise', root_days=3650, issuer_days=1825):
        if len(password) < 12:
            raise ValueError('CA 加密口令至少 12 位')
        if not 365 <= issuer_days < root_days <= 7300:
            raise ValueError('签发 CA 有效期至少一年且短于根 CA，根 CA 最长 20 年')
        ca = cls(directory)
        ca.directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        if any(ca.directory.iterdir()):
            raise ValueError('初始化目录必须为空，不能覆盖已有 CA')
        os.chmod(ca.directory, 0o700)
        sentinel = ca.directory/'.initializing'
        fd = os.open(str(sentinel), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        root_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
        issuer_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
        root_name = name(organization + ' Root CA')
        root = (x509.CertificateBuilder().subject_name(root_name).issuer_name(root_name)
                .public_key(root_key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now() - timedelta(minutes=5)).not_valid_after(now() + timedelta(days=root_days))
                .add_extension(x509.BasicConstraints(ca=True, path_length=1), True)
                .add_extension(key_usage(True), True)
                .add_extension(x509.SubjectKeyIdentifier.from_public_key(root_key.public_key()), False)
                .sign(root_key, hashes.SHA256()))
        issuer = (builder(name(organization + ' Issuing CA'), root, issuer_key.public_key(), issuer_days)
                  .add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
                  .add_extension(key_usage(True), True)
                  .add_extension(x509.SubjectKeyIdentifier.from_public_key(issuer_key.public_key()), False)
                  .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(root_key.public_key()), False)
                  .sign(root_key, hashes.SHA256()))
        for filename, key in (('root-key.pem', root_key), ('issuer-key.pem', issuer_key)):
            atomic_write(ca.directory / filename, key.private_bytes(serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8, serialization.BestAvailableEncryption(password.encode())))
        atomic_write(ca.directory / 'roots.pem', pem(root), 0o644)
        atomic_write(ca.directory / 'intermediates.pem', pem(issuer), 0o644)
        with ca.connect(create=True) as conn:
            conn.executescript('''
                CREATE TABLE certificates(serial TEXT PRIMARY KEY, device_id TEXT NOT NULL, role TEXT NOT NULL,
                  cn TEXT NOT NULL, csr_sha256 TEXT NOT NULL, key_sha256 TEXT NOT NULL, issued_at TEXT NOT NULL,
                  expires_at TEXT NOT NULL, pem BLOB NOT NULL, revoked_at TEXT, reason TEXT);
                CREATE TABLE events(id INTEGER PRIMARY KEY, time TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL);
                CREATE TABLE metadata(key TEXT PRIMARY KEY, value INTEGER NOT NULL);
                INSERT INTO metadata VALUES('crl_number',0);
            ''')
            ca.event(conn, 'initialize', organization)
        os.chmod(ca.database, 0o600)
        sentinel.unlink()
        return ca

    @contextlib.contextmanager
    def connect(self, create=False):
        if not create and (self.directory/'.initializing').exists():
            raise ValueError('CA 初始化未完成，请核查数据目录')
        if not create and not self.database.is_file():
            raise ValueError('CA 尚未初始化，未找到签发数据库')
        if self.database.is_symlink():
            raise ValueError('CA 数据库不能为符号链接')
        connection = sqlite3.connect(str(self.database), timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def event(conn, action, detail):
        conn.execute('INSERT INTO events(time,action,detail) VALUES(?,?,?)', (now().isoformat(), action, json.dumps(dict(operator=getpass.getuser(), detail=detail), ensure_ascii=False)))

    def unlock(self, password):
        if os.name == 'posix':
            for path in (self.directory, self.directory/'issuer-key.pem', self.directory/'root-key.pem'):
                info = path.stat()
                if path.is_symlink() or info.st_uid != os.geteuid() or info.st_mode & 0o077:
                    raise ValueError('CA 目录及加密私钥必须归当前用户所有，且禁止组/其他用户访问')
        key = serialization.load_pem_private_key(read_file(self.directory / 'issuer-key.pem'), password.encode())
        cert = x509.load_pem_x509_certificate(read_file(self.directory / 'intermediates.pem'))
        root = x509.load_pem_x509_certificate(read_file(self.directory / 'roots.pem'))
        if public(key.public_key()) != public(cert.public_key()):
            raise ValueError('签发 CA 私钥和证书不匹配')
        root.public_key().verify(cert.signature, cert.tbs_certificate_bytes,
                                 cert.signature_algorithm_parameters, cert.signature_hash_algorithm)
        if not cert.not_valid_before_utc <= now() < cert.not_valid_after_utc or not root.not_valid_before_utc <= now() < root.not_valid_after_utc:
            raise ValueError('CA 已过期或尚未生效')
        return key, cert

    def fingerprint(self):
        return x509.load_pem_x509_certificate(read_file(self.directory / 'roots.pem')).fingerprint(hashes.SHA256()).hex().upper()

    def inspect_request(self, directory):
        manifest = public_package(directory, 'lc400-csr')
        result = []
        keys = set()
        for role in ROLES:
            data = read_file(Path(directory) / (role + '.csr'))
            csr, sans = validate_csr(data, role)
            kid = digest(public(csr.public_key()))
            if kid in keys:
                raise ValueError('三种设备身份必须使用不同公钥')
            keys.add(kid)
            result.append(dict(role=role, cn=csr.subject.rfc4514_string(), sans=[str(s.value) for s in sans], csr_sha256=digest(data)))
        return dict(device_id=manifest['device_id'], identities=result)

    def issue_package(self, request_directory, output, password, days=365, expected_review=None):
        if type(days) is not int or not 1 <= days <= 825:
            raise ValueError('设备证书有效期应为 1–825 天')
        review = self.inspect_request(request_directory)
        if expected_review is not None and review != expected_review:
            raise ValueError('CSR 自审查确认后发生变化，请重新预览并批准')
        key, issuer = self.unlock(password)
        if now() + timedelta(days=days) > issuer.not_valid_after_utc:
            raise ValueError('设备证书到期时间不能超过签发 CA 到期时间')
        output = Path(output).absolute()
        if output.exists():
            raise ValueError('输出目录已存在，请选择新的目录')
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.ca-sign-', dir=str(output.parent)) as temporary:
            stage = Path(temporary) / 'bundle'; stage.mkdir()
            files = {'roots.pem': read_file(self.directory / 'roots.pem'),
                     'intermediates.pem': read_file(self.directory / 'intermediates.pem')}
            rows = []
            for role in ROLES:
                data = read_file(Path(request_directory) / (role + '.csr'))
                if digest(data) != next(r['csr_sha256'] for r in review['identities'] if r['role'] == role):
                    raise ValueError('CSR 在签发期间发生变化')
                csr, sans = validate_csr(data, role)
                b = (builder(csr.subject, issuer, csr.public_key(), days)
                     .add_extension(x509.BasicConstraints(False, None), True)
                     .add_extension(key_usage(), True)
                     .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH if role == 'master' else ExtendedKeyUsageOID.SERVER_AUTH]), False)
                     .add_extension(x509.SubjectKeyIdentifier.from_public_key(csr.public_key()), False)
                     .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), False))
                if sans:
                    b = b.add_extension(x509.SubjectAlternativeName(sans), False)
                cert = b.sign(key, hashes.SHA256())
                encoded = pem(cert)
                files[role + '-leaf.pem'] = encoded
                rows.append((format(cert.serial_number, 'x'), review['device_id'], role,
                             csr.subject.rfc4514_string(), digest(data), digest(public(csr.public_key())),
                             now().isoformat(), cert.not_valid_after_utc.isoformat(), encoded))
            manifest = dict(version=1, kind='lc400-certificates', device_id=review['device_id'],
                            root_fingerprints=[self.fingerprint()], files={n:digest(d) for n,d in files.items()})
            for filename, data in files.items():
                atomic_write(stage / filename, data, 0o644)
            atomic_write(stage / 'manifest.json', json_bytes(manifest), 0o644)
            atomic_write(stage / 'deployment.json', json_bytes(dict(
                version=1, kind='lc400-deployment', device_id=review['device_id'],
                manifest_sha256=digest(json_bytes(manifest)),
                root_fingerprints=manifest['root_fingerprints'])), 0o644)
            # Commit issuance before delivery: failed delivery remains traceable, never an unrecorded certificate.
            with self.connect() as conn:
                conn.execute('BEGIN IMMEDIATE')
                for row in rows:
                    history = conn.execute('SELECT device_id,role,reason FROM certificates WHERE key_sha256=?', (row[5],)).fetchall()
                    if any(r['role'] != row[2] or r['device_id'] != row[1] for r in history):
                        raise ValueError('此公钥曾用于另一设备/角色，拒绝身份复用')
                    if any(r['reason'] == 'key_compromise' for r in history):
                        raise ValueError('此公钥已因密钥泄露吊销，禁止继续签发')
                    conn.execute('INSERT INTO certificates(serial,device_id,role,cn,csr_sha256,key_sha256,issued_at,expires_at,pem) VALUES(?,?,?,?,?,?,?,?,?)', row)
                self.event(conn, 'issue-package', json.dumps(dict(device_id=review['device_id'], serials=[r[0] for r in rows])))
            os.rename(stage, output)
        return manifest

    def records(self):
        with self.connect() as conn:
            return [dict(r) for r in conn.execute('SELECT serial,device_id,role,cn,issued_at,expires_at,revoked_at,reason FROM certificates ORDER BY issued_at DESC')]

    def revoke(self, serial, password, reason='cessation_of_operation'):
        self.unlock(password)
        reasons = {'key_compromise', 'superseded', 'cessation_of_operation', 'affiliation_changed'}
        if reason not in reasons:
            raise ValueError('无效吊销原因')
        with self.connect() as conn:
            changed = conn.execute('UPDATE certificates SET revoked_at=?,reason=? WHERE serial=? AND revoked_at IS NULL', (now().isoformat(), reason, serial)).rowcount
            if not changed:
                raise ValueError('证书不存在或已吊销')
            self.event(conn, 'revoke', serial + ':' + reason)

    def export_crl(self, path, password, days=7):
        if Path(path).absolute().parent == self.directory:
            raise ValueError('CRL 请导出到 CA 数据目录之外，避免覆盖密钥或数据库')
        key, issuer = self.unlock(password)
        if not 1 <= days <= 30:
            raise ValueError('CRL 有效期应为 1–30 天')
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute("UPDATE metadata SET value=value+1 WHERE key='crl_number'")
            number = conn.execute("SELECT value FROM metadata WHERE key='crl_number'").fetchone()[0]
            b = (x509.CertificateRevocationListBuilder().issuer_name(issuer.subject).last_update(now())
                 .next_update(min(now()+timedelta(days=days), issuer.not_valid_after_utc))
                 .add_extension(x509.CRLNumber(number), False)
                 .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), False))
            for r in conn.execute('SELECT serial,revoked_at,reason FROM certificates WHERE revoked_at IS NOT NULL'):
                revoked = (x509.RevokedCertificateBuilder().serial_number(int(r['serial'], 16))
                           .revocation_date(datetime.fromisoformat(r['revoked_at']))
                           .add_extension(x509.CRLReason(getattr(x509.ReasonFlags, r['reason'])), False).build())
                b = b.add_revoked_certificate(revoked)
            atomic_write(path, b.sign(key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM), 0o644)
            self.event(conn, 'export-crl', str(number))
