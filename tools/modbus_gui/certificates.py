"""Local certificate helpers. OpenSSL is only needed for inspection/generation."""
import ipaddress
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


def openssl(*args):
    try:
        result = subprocess.run(['openssl', *map(str, args)], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=60)
    except FileNotFoundError:
        raise ValueError('未找到 openssl，请安装并加入 PATH')
    if result.returncode:
        raise ValueError(result.stderr.decode(errors='replace').strip())
    return result.stdout


def inspect(path):
    if sys.platform == 'win32' or getattr(sys, 'frozen', False):
        from .certificate_crypto import inspect as inspect_native
        return inspect_native(path)
    return openssl('x509', '-in', path, '-noout', '-subject', '-issuer', '-dates',
                   '-fingerprint', '-sha256', '-ext', 'subjectAltName').decode(errors='replace')


def export_certificate(source, destination):
    data = Path(source).read_bytes()
    # Never export a private key accidentally, including combined PEM files.
    remainder = re.sub(rb'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----', b'', data, flags=re.S)
    if remainder.strip() or b'-----BEGIN CERTIFICATE-----' not in data:
        raise ValueError('只能导出纯 PEM 公开证书或 CA 证书链，不能包含私钥')
    if Path(source).resolve() == Path(destination).resolve():
        raise ValueError('导出位置不能与源文件相同')
    Path(destination).write_bytes(data)


def server_san(host):
    host = host.strip()
    try:
        san = 'IP:' + str(ipaddress.ip_address(host))
    except ValueError:
        if len(host) > 253 or not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label) for label in host.split('.')):
            raise ValueError('请输入合法的服务端 IP 或 DNS 名称')
        san = 'DNS:' + host
    return san


def generate_device(parent, host='127.0.0.1'):
    """Directly self-signed CA:FALSE identities accepted by EMS trust-add."""
    if sys.platform == 'win32' or getattr(sys, 'frozen', False):
        from .certificate_crypto import generate
        return generate(parent, host, device=True)
    san = server_san(host)
    folder = Path(tempfile.mkdtemp(prefix='modbus-device-certs-', dir=parent))
    folder.chmod(0o700)
    try:
        for role, purpose in [('server', 'serverAuth'), ('client', 'clientAuth')]:
            key = folder / (role + '.key')
            key.touch(mode=0o600)
            openssl('genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:3072', '-out', key)
            config = folder / (role + '.cnf')
            # Match the TA identity profile, including its absent keyUsage extension.
            # OpenSSL 1.1.1 otherwise fails to recognize a CA:FALSE leaf as self-signed
            # when keyUsage excludes keyCertSign, even when directly trusted.
            config.write_text('[req]\ndistinguished_name=dn\nx509_extensions=identity\n[dn]\n[identity]\n'
                              'basicConstraints=critical,CA:FALSE\n'
                              'subjectKeyIdentifier=hash\nextendedKeyUsage=' + purpose + '\n' +
                              ('subjectAltName=' + san + ',DNS:localhost\n' if role == 'server' else ''), encoding='ascii')
            openssl('req', '-new', '-x509', '-sha256', '-days', '365', '-key', key,
                    '-out', folder / (role + '.crt'), '-subj', '/CN=Modbus-GUI-' + role, '-config', config)
            config.unlink()
        return folder
    except BaseException:
        shutil.rmtree(folder)
        raise


def generate_demo(parent, host='127.0.0.1'):
    if sys.platform == 'win32' or getattr(sys, 'frozen', False):
        from .certificate_crypto import generate
        return generate(parent, host, device=False)
    san = server_san(host)
    folder = Path(tempfile.mkdtemp(prefix='modbus-certs-', dir=parent))
    folder.chmod(0o700)
    try:
        def key(name):
            path = folder / (name + '.key')
            path.touch(mode=0o600)
            openssl('genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048', '-out', path)
        key('ca')
        config = folder / 'ca.cnf'
        config.write_text('[req]\ndistinguished_name=dn\nx509_extensions=ca\n[dn]\n[ca]\n'
                          'basicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,cRLSign\n'
                          'subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid:always\n', encoding='ascii')
        openssl('req', '-new', '-x509', '-sha256', '-days', '365', '-key', folder / 'ca.key',
                '-out', folder / 'ca.crt', '-subj', '/CN=Modbus-GUI-Demo-CA',
                '-config', config)
        for role, purpose in [('server', 'serverAuth'), ('client', 'clientAuth')]:
            key(role)
            openssl('req', '-new', '-sha256', '-key', folder / (role + '.key'),
                    '-out', folder / (role + '.csr'), '-subj', '/CN=Modbus-GUI-' + role)
            ext = folder / (role + '.ext')
            ext.write_text('basicConstraints=critical,CA:FALSE\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid:always\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=' + purpose + '\n' +
                           ('subjectAltName=' + san + ',DNS:localhost\n' if role == 'server' else ''), encoding='ascii')
            openssl('x509', '-req', '-sha256', '-days', '365', '-in', folder / (role + '.csr'),
                    '-CA', folder / 'ca.crt', '-CAkey', folder / 'ca.key', '-CAcreateserial',
                    '-extfile', ext, '-out', folder / (role + '.crt'))
            ext.unlink()
            (folder / (role + '.csr')).unlink()
        config.unlink()
        return folder
    except BaseException:
        shutil.rmtree(folder)
        raise
