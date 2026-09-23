#!/usr/bin/env python3
"""Manage directly self-signed Modbus identities with Python 3 + OpenSSL 1.1.1+."""
import argparse
import contextlib
import datetime
import fcntl
import hashlib
import ipaddress
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid

PEM = re.compile(rb'-----BEGIN CERTIFICATE-----\s+.*?-----END CERTIFICATE-----', re.S)


def openssl(*args, data=None):
    result = subprocess.run(['openssl', *map(str, args)], input=data,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise ValueError(result.stderr.decode(errors='replace').strip() or 'OpenSSL operation failed')
    return result.stdout


def certificates(data):
    blocks = PEM.findall(data)
    if not blocks or PEM.sub(b'', data).strip():
        raise ValueError('只接受 PEM 证书文件，不接受私钥、CSR 或其他内容')
    return [openssl('x509', '-outform', 'PEM', data=b) for b in blocks]


def fingerprint(cert):
    return hashlib.sha256(openssl('x509', '-outform', 'DER', data=cert)).hexdigest().upper()


def normalize_fingerprint(value):
    value = value.replace(':', '').strip().upper()
    if not re.fullmatch(r'[0-9A-F]{64}', value):
        raise ValueError('指纹必须是完整的 SHA-256 十六进制值（可带冒号）')
    return value


def validate(cert, role, directory):
    info = openssl('x509', '-noout', '-subject', '-issuer', '-nameopt', 'RFC2253', data=cert).decode().splitlines()
    if info[0].partition('=')[2].strip() != info[1].partition('=')[2].strip():
        raise ValueError('要求设备直接自签证书，不能使用 CA 签发的证书')
    details = openssl('x509', '-noout', '-ext', 'basicConstraints', data=cert).decode()
    if 'CA:FALSE' not in details or 'CA:TRUE' in details:
        raise ValueError('设备证书必须显式设置 basicConstraints=CA:FALSE')
    expected = 'TLS Web Client Authentication' if role == 'master' else 'TLS Web Server Authentication'
    usage = openssl('x509', '-noout', '-ext', 'extendedKeyUsage', data=cert).decode()
    if expected not in usage:
        raise ValueError('证书用途不匹配：主机需要 clientAuth，从机需要 serverAuth')
    with tempfile.TemporaryDirectory(prefix='.verify-', dir=directory) as temp:
        path = Path(temp) / 'cert.pem'
        path.write_bytes(cert)
        # Verify the self-signature as well as validity and intended usage.
        openssl('verify', '-check_ss_sig', '-no-CAfile', '-no-CApath',
                '-trusted', path, '-purpose', 'sslclient' if role == 'master' else 'sslserver', path)


def atomic_write(path, data, mode=0o600):
    if path.is_symlink():
        raise ValueError('拒绝覆盖符号链接: ' + str(path))
    fd, temp = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


@contextlib.contextmanager
def locked(directory):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.is_symlink():
        raise ValueError('证书目录不能是符号链接')
    fd = os.open(directory / '.cert-manager.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def identity_paths(directory, role):
    return directory / (role + '.crt'), directory / (role + '.key')


def backup(directory, paths):
    name = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:8]
    target = directory / 'backups' / name
    target.mkdir(parents=True, mode=0o700)
    for path in paths:
        if path.is_symlink():
            raise ValueError('拒绝处理符号链接: ' + str(path))
        if path.exists():
            atomic_write(target / path.name, path.read_bytes())
    return target


def generate(args, directory):
    cert_path, key_path = identity_paths(directory, args.role)
    paths = (cert_path, key_path)
    if any(p.is_symlink() for p in paths):
        raise ValueError('证书/私钥路径不能是符号链接')
    exists = any(p.exists() for p in paths)
    if args.command == 'generate' and exists:
        raise ValueError('已有证书或私钥；需要换证时使用 renew（自动备份）')
    if args.command == 'renew' and not all(p.exists() for p in paths):
        raise ValueError('renew 要求已有完整证书和私钥；首次创建请使用 generate')
    if not re.fullmatch(r'[A-Za-z0-9_.:@-]{1,64}', args.name):
        raise ValueError('设备名称限 1～64 个字母、数字或 _ . : @ -')
    if not 1 <= args.days <= 3650:
        raise ValueError('有效期必须在 1～3650 天之间')
    sans = ['IP:' + str(ipaddress.ip_address(ip)) for ip in args.ip]
    for dns in args.dns:
        if len(dns) > 253 or not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label) for label in dns.split('.')):
            raise ValueError('无效 DNS 名称: ' + dns)
        sans.append('DNS:' + dns)
    with tempfile.TemporaryDirectory(prefix='.generate-', dir=directory) as temp:
        cert, key = Path(temp) / 'cert.pem', Path(temp) / 'key.pem'
        config = Path(temp) / 'openssl.cnf'
        config.write_text('[req]\ndistinguished_name = dn\n[dn]\n')
        # OpenSSL 1.1.1 recognizes directly trusted self-signed leaves without
        # a keyUsage extension. CA:FALSE prevents issuing other certificates;
        # EKU constrains the TLS role. Do not grant keyCertSign to a leaf.
        command = ['req', '-config', config, '-new', '-x509', '-newkey', 'rsa:2048', '-nodes', '-sha256',
                   '-days', str(args.days), '-subj', '/CN=' + args.name,
                   '-keyout', key, '-out', cert,
                   '-addext', 'basicConstraints=critical,CA:FALSE',
                   '-addext', 'extendedKeyUsage=' + ('clientAuth' if args.role == 'master' else 'serverAuth'),
                   '-addext', 'subjectKeyIdentifier=hash']
        if sans:
            command += ['-addext', 'subjectAltName=' + ','.join(sans)]
        openssl(*command)
        cert_data, key_data = cert.read_bytes(), key.read_bytes()
        validate(cert_data, args.role, directory)
        saved = backup(directory, paths) if exists else None
        try:
            atomic_write(key_path, key_data)
            atomic_write(cert_path, cert_data)
        except BaseException:
            for path in paths:
                if saved:
                    atomic_write(path, (saved / path.name).read_bytes())
                else:
                    path.unlink(missing_ok=True)
            raise
    print('已生成:', cert_path)
    print('SHA256:', fingerprint(cert_data))
    if saved:
        print('旧证书和私钥备份:', saved)
    print('私钥仅保存在本机。生效需重启 tems；脚本不会自动重启。')
    if args.role == 'master':
        print('请将新的 master.crt 导入需要连接的从机信任文件。')


def show_cert(cert):
    print(openssl('x509', '-noout', '-subject', '-issuer', '-dates', data=cert).decode().strip())
    print('SHA256:', fingerprint(cert))


def main():
    parser = argparse.ArgumentParser(description='Modbus 自签证书管理（需手动重启相关服务）')
    parser.add_argument('--dir', type=Path, default=Path('/etc/ems/modbus'), help='证书目录，默认 /etc/ems/modbus')
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('generate', 'renew'):
        p = sub.add_parser(command, help='创建本机身份' if command == 'generate' else '备份并更换证书与私钥')
        p.add_argument('--role', required=True, choices=['master', 'slave'])
        p.add_argument('--name', required=True, help='本机设备唯一名称（CN）')
        p.add_argument('--days', type=int, default=365)
        p.add_argument('--ip', action='append', default=[], help='SAN IP，可重复')
        p.add_argument('--dns', action='append', default=[], help='SAN DNS，可重复')
    for command in ('show', 'check', 'export'):
        p = sub.add_parser(command)
        p.add_argument('--role', required=True, choices=['master', 'slave'])
        if command == 'export':
            p.add_argument('--out', type=Path, required=True, help='仅导出公开证书，不覆盖已有文件')
    p = sub.add_parser('trust-add', help='从机导入一个可信主机自签证书')
    p.add_argument('--cert', type=Path, required=True)
    p.add_argument('--fingerprint', help='可选：与可信渠道取得的 SHA256 指纹核对')
    sub.add_parser('trust-list', help='列出信任文件内的所有主机证书')
    p = sub.add_parser('trust-remove', help='按完整 SHA256 指纹移除主机证书，自动备份')
    p.add_argument('--fingerprint', required=True)
    args = parser.parse_args()
    directory = args.dir.absolute()
    with locked(directory):
        if args.command in ('generate', 'renew'):
            generate(args, directory)
        elif args.command in ('show', 'check', 'export'):
            cert_path, key_path = identity_paths(directory, args.role)
            certs = certificates(cert_path.read_bytes())
            if len(certs) != 1:
                raise ValueError('本机身份必须是单个直接自签证书')
            cert = certs[0]
            if args.command == 'check':
                validate(cert, args.role, directory)
                openssl('pkey', '-in', key_path, '-passin', 'pass:', '-check', '-noout')
                key_pub = openssl('pkey', '-in', key_path, '-passin', 'pass:', '-pubout', '-outform', 'DER')
                cert_pub = openssl('pkey', '-pubin', '-outform', 'DER', data=openssl('x509', '-pubkey', '-noout', data=cert))
                if key_pub != cert_pub:
                    raise ValueError('证书与私钥不匹配')
                if key_path.stat().st_mode & 0o077:
                    raise ValueError('私钥权限过宽，应为 600（或更严格）')
                print('校验通过：自签名、有效期、用途和私钥匹配')
            elif args.command == 'export':
                with args.out.open('xb') as stream:
                    stream.write(cert)
                print('已导出公开证书:', args.out)
            show_cert(cert)
        else:
            bundle = directory / 'master-ca.crt'
            old = certificates(bundle.read_bytes()) if bundle.exists() and bundle.stat().st_size else []
            if args.command == 'trust-list':
                print('可信主机证书数量:', len(old))
                for cert in old:
                    show_cert(cert)
                return
            if args.command == 'trust-add':
                incoming = certificates(args.cert.read_bytes())
                if len(incoming) != 1:
                    raise ValueError('每次只导入一个主机证书')
                cert = incoming[0]
                validate(cert, 'master', directory)
                digest = fingerprint(cert)
                if args.fingerprint and normalize_fingerprint(args.fingerprint) != digest:
                    raise ValueError('指纹不匹配，未修改信任文件')
                if digest in [fingerprint(c) for c in old]:
                    print('证书已存在，未重复导入:', digest)
                    return
                updated = old + [cert]
            else:
                digest = normalize_fingerprint(args.fingerprint)
                updated = [c for c in old if fingerprint(c) != digest]
                if len(updated) == len(old):
                    raise ValueError('未找到该指纹，未修改信任文件')
            if bundle.exists():
                print('旧信任文件备份:', backup(directory, [bundle]))
            atomic_write(bundle, b''.join(updated))
            print('可信主机证书数量:', len(updated), 'SHA256:', digest)
            print('重启 tems 后生效；脚本不会自动重启。')
            if not updated:
                print('信任文件已为空：当前 TLS 实现重启后不会启动从机监听，需重新导入证书。')


if __name__ == '__main__':
    os.umask(0o077)
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print('错误:', exc, file=sys.stderr)
        sys.exit(1)
