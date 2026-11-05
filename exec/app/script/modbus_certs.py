#!/usr/bin/env python3
"""Manage CA-issued Modbus identities and shared trust with Python/OpenSSL."""
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

import pki_common as pki

PEM = re.compile(rb'-----BEGIN CERTIFICATE-----\s+.*?-----END CERTIFICATE-----', re.S)
TEE_IDENTITY = os.environ.get('MODBUS_TEE_IDENTITY', '/home/zlg/app/bin/modbus_tee_identity')


def key_backend():
    value = os.environ.get('MODBUS_KEY_BACKEND', 'file')
    if value not in ('file', 'tee'):
        raise ValueError('MODBUS_KEY_BACKEND 只允许 file 或 tee')
    return value


def tee_identity(*args, directory=None):
    prefix = [TEE_IDENTITY]
    if directory is not None:
        prefix += ['--dir', str(directory)]
    result = subprocess.run([*prefix, *map(str, args)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    if result.returncode:
        raise ValueError(result.stderr.decode(errors='replace').strip() or 'Modbus identity operation failed')
    return result.stdout


def openssl(*args, data=None):
    result = subprocess.run(['openssl', *map(str, args)], input=data,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
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
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
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


def show_cert(cert):
    print(openssl('x509', '-noout', '-subject', '-issuer', '-dates', data=cert).decode().strip())
    print('SHA256:', fingerprint(cert))


def create_csr(args,directory):
    if not re.fullmatch(r'[A-Za-z0-9_.:@-]{1,64}',args.name):
        raise ValueError('Invalid identity name')
    sans=['IP:'+str(ipaddress.ip_address(value)) for value in args.ip]
    for value in args.dns:
        if len(value)>253 or not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?',label) for label in value.split('.')):
            raise ValueError('Invalid DNS name')
        sans.append('DNS:'+value)
    cert,_=identity_paths(directory,args.role)
    destination=directory/(args.role+'.csr')
    operation='csr-existing' if cert.exists() or destination.exists() else 'csr'
    data=tee_identity(operation,args.role,args.name,','.join(sans),directory=directory)
    public=pki.csr_public_key(data)
    other='slave' if args.role=='master' else 'master'
    for path in (directory/(other+'.csr'),directory/(other+'.crt')):
        if path.exists():
            other_public=pki.csr_public_key(path.read_bytes()) if path.suffix=='.csr' else pki.public_key(certificates(path.read_bytes())[0])
            if public==other_public:
                raise ValueError('Master and slave must have independent private keys')
    atomic_write(destination,data,0o644)
    print('CSR:',destination)
    print('CSR SHA256:',hashlib.sha256(data).hexdigest().upper())
    print('Export CSR for external CA signing; no private key is exported or CA key stored.')


def import_identity(args,directory,settings):
    destination,_=identity_paths(directory,args.role)
    csr=directory/(args.role+'.csr')
    if not csr.is_file() or csr.is_symlink():
        raise ValueError('Generate the local role CSR before importing its signed identity')
    anchors=settings['ca_file'].read_bytes()
    leaf,chain=pki.validate_identity(args.cert.read_bytes(),args.chain.read_bytes() if args.chain else None,
        settings['ca_file'],'sslclient' if args.role=='master' else 'sslserver',csr.read_bytes())
    with tempfile.TemporaryDirectory(prefix='.identity-',dir=directory) as temporary:
        candidate=Path(temporary)/'identity.pem'
        candidate.write_bytes(leaf+chain)
        tee_identity('check',args.role,candidate,directory=directory)
    if settings['ca_file'].read_bytes()!=anchors:
        raise ValueError('CA trust changed during verification; retry import')
    if destination.exists():
        print('Previous identity backup:',backup(directory,[destination]))
    atomic_write(destination,leaf+chain,0o644)
    print('Imported identity:',destination,'SHA256:',fingerprint(leaf))
    print('Full chain verified, CSR/private key matched; restart tems during maintenance.')


def main():
    parser=argparse.ArgumentParser(description='CA-issued Modbus identity management')
    parser.add_argument('--dir',type=Path,default=Path('/etc/ems/modbus'))
    parser.add_argument('--config',type=Path)
    sub=parser.add_subparsers(dest='command',required=True)
    for command in ('show','check','export','csr-export'):
        item=sub.add_parser(command)
        item.add_argument('--role',required=True,choices=['master','slave'])
        if command in ('export','csr-export'):
            item.add_argument('--out',type=Path,required=True)
    item=sub.add_parser('csr')
    item.add_argument('--role',required=True,choices=['master','slave'])
    item.add_argument('--name',required=True)
    item.add_argument('--ip',action='append',default=[])
    item.add_argument('--dns',action='append',default=[])
    item=sub.add_parser('identity-import')
    item.add_argument('--role',required=True,choices=['master','slave'])
    item.add_argument('--cert',type=Path,required=True)
    item.add_argument('--chain',type=Path)
    item=sub.add_parser('ca-import')
    item.add_argument('--cert',type=Path,required=True)
    item.add_argument('--fingerprint',action='append')
    sub.add_parser('ca-list')
    args=parser.parse_args()
    key_backend()
    settings=pki.read_config(args.config)
    if args.config:
        os.environ['LC_INI_PATH']=str(args.config.absolute())
    directory=args.dir.absolute()
    with locked(directory):
        if args.command=='csr':
            create_csr(args,directory)
        elif args.command=='csr-export':
            source=directory/(args.role+'.csr')
            tee_identity('check-csr',args.role,source,directory=directory)
            with args.out.open('xb') as stream:
                stream.write(source.read_bytes())
            print('Exported CSR:',args.out)
        elif args.command=='identity-import':
            import_identity(args,directory,settings)
        elif args.command=='ca-import':
            print('Shared root CA fingerprints:',pki.import_roots(settings['ca_file'],args.cert.read_bytes(),args.fingerprint))
        elif args.command=='ca-list':
            for cert in certificates(settings['ca_file'].read_bytes()):
                show_cert(cert)
        else:
            cert_path,_=identity_paths(directory,args.role)
            data=cert_path.read_bytes()
            certs=certificates(data)
            if args.command=='check':
                pki.validate_identity(data,None,settings['ca_file'],
                    'sslclient' if args.role=='master' else 'sslserver')
                tee_identity('check',args.role,cert_path,directory=directory)
                print('Verified CA chain, validity, role and device private key')
            elif args.command=='export':
                with args.out.open('xb') as stream:
                    stream.write(b''.join(certs))
                print('Exported public identity chain:',args.out)
            show_cert(certs[0])


if __name__=='__main__':
    os.umask(0o077)
    try:
        main()
    except (OSError,ValueError,subprocess.SubprocessError) as exc:
        print('Error:',exc,file=sys.stderr)
        sys.exit(1)
