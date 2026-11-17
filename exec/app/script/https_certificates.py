#!/usr/bin/env python3
"""HTTPS external-CA CSR/import/renewal requests; CA signing remains offline."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pki_common as pki
from https_config import read_device_ips


def key_public(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('HTTPS private key is missing or is a symbolic link')
    info=path.stat()
    if info.st_uid!=os.geteuid() or info.st_mode&0o077:
        raise ValueError('HTTPS key requires current-user ownership and mode 0600')
    pki.run('pkey','-in',path,'-passin','pass:','-check','-noout')
    return pki.run('pkey','-in',path,'-passin','pass:','-pubout','-outform','DER')


def generate_csr(directory,config):
    key=directory/'g3.key'
    csr=directory/'g3.csr'
    if not key.exists():
        if key.is_symlink() or csr.exists() or (directory/'g3.crt').exists():
            raise ValueError('HTTPS identity key was lost; automatic key replacement is forbidden')
        pki.atomic_write(key,pki.run('genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:2048'))
    public=key_public(key)
    ips=read_device_ips(config)
    data=pki.run('req','-new','-key',key,'-passin','pass:','-sha256','-subj','/CN=LC400-logger',
        '-addext','subjectAltName='+','.join('IP:'+ip for ip in ips),
        '-addext','basicConstraints=critical,CA:FALSE',
        '-addext','extendedKeyUsage=serverAuth',
        '-addext','keyUsage=critical,digitalSignature,keyEncipherment')
    if pki.csr_public_key(data)!=public:
        raise ValueError('CSR private key mismatch')
    if not csr.exists() or csr.read_bytes()!=data:
        pki.atomic_write(csr,data,0o644)
    return dict(csr=str(csr),sha256=hashlib.sha256(data).hexdigest(),device_ips=ips)


def check(directory,settings,match_csr=False):
    certificate=directory/'g3.crt'
    if certificate.is_symlink():
        raise ValueError('Certificate cannot be a symbolic link')
    csr=(directory/'g3.csr').read_bytes() if match_csr else None
    leaf,chain=pki.validate_identity(certificate.read_bytes(),None,settings['ca_file'],'sslserver',csr,settings['crl_file'],require_fresh_crl=True)
    if pki.public_key(leaf)!=key_public(directory/'g3.key'):
        raise ValueError('HTTPS certificate does not match the device private key')
    expected={('IP',ip) for ip in read_device_ips(settings['config_file'])}
    if not pki.subject_cn(leaf).startswith('LC400-') or not expected.issubset(pki.san_values(leaf)):
        raise ValueError('HTTPS certificate CN/SAN does not match the current device configuration')
    return leaf,chain


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path)
    parser.add_argument('--dir',type=Path,default=Path('/etc/ssl/g3'))
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('csr')
    export=sub.add_parser('csr-export');export.add_argument('--out',type=Path,required=True)
    incoming=sub.add_parser('identity-import')
    incoming.add_argument('--cert',type=Path,required=True)
    incoming.add_argument('--chain',type=Path)
    roots=sub.add_parser('ca-import')
    roots.add_argument('--cert',type=Path,required=True)
    roots.add_argument('--fingerprint',action='append')
    sub.add_parser('check')
    sub.add_parser('status')
    renewal=sub.add_parser('reconcile')
    renewal.add_argument('--renew-window-days',type=int,default=30)
    args=parser.parse_args()
    settings=pki.read_config(args.config)
    if settings['mode']!='external_ca':
        raise ValueError('HTTPS CA provisioning requires [TLS] certificate_mode=external_ca')
    directory=args.dir.absolute()
    with contextlib.ExitStack() as stack:
        if args.command in ('identity-import', 'ca-import'):
            stack.enter_context(pki.operation_lock(settings))
        stack.enter_context(pki.locked(directory))
        if args.command=='csr':
            result=generate_csr(directory,settings['config_file'])
        elif args.command=='csr-export':
            data=(directory/'g3.csr').read_bytes()
            if pki.csr_public_key(data)!=key_public(directory/'g3.key'):
                raise ValueError('CSR no longer matches the HTTPS key')
            with args.out.open('xb') as stream:
                stream.write(data)
            result=dict(exported=str(args.out))
        elif args.command=='ca-import':
            result=dict(fingerprints=pki.import_roots(settings['ca_file'],args.cert.read_bytes(),args.fingerprint,
                (Path(os.environ.get('MODBUS_CERT_DIR', '/etc/ems/modbus')), directory)))
        elif args.command=='identity-import':
            csr=(directory/'g3.csr').read_bytes()
            anchors=settings['ca_file'].read_bytes()
            leaf,chain=pki.validate_identity(args.cert.read_bytes(),args.chain.read_bytes() if args.chain else None,
                settings['ca_file'],'sslserver',csr,settings['crl_file'],require_fresh_crl=True)
            if pki.public_key(leaf)!=key_public(directory/'g3.key'):
                raise ValueError('Issued certificate does not match the HTTPS device key')
            expected={('IP',ip) for ip in read_device_ips(settings['config_file'])}
            if not pki.subject_cn(leaf).startswith('LC400-') or not expected.issubset(pki.san_values(leaf)):
                raise ValueError('Issued certificate does not match current HTTPS CN/SAN')
            if settings['ca_file'].read_bytes()!=anchors:
                raise ValueError('CA trust changed during verification; retry import')
            certificate=directory/'g3.crt'
            if certificate.exists():
                backup=directory/'backup';backup.mkdir(mode=0o700,exist_ok=True)
                pki.atomic_write(backup/('g3-'+str(time.time_ns())+'.crt'),certificate.read_bytes())
            pki.atomic_write(directory/'.reload-required',b'New external-CA identity imported\n')
            pki.mark_pending(settings, 'nginx', 'https')
            pki.atomic_write(certificate,leaf+chain,0o644)
            # Explicit return to the CSR flow; old endpoints remain available.
            pki.identity_source_path(directory, 'https').unlink(missing_ok=True)
            result=dict(imported=True,sha256=pki.fingerprint(leaf),reload_required=True,
                        chain_certificates=1+len(pki.certificates(chain)) if chain else 1)
        elif args.command in ('check', 'status'):
            result=dict(valid=False,reload_required=(directory/'.reload-required').exists(),
                        pki_mode='trina' if pki.is_external_identity(directory, 'https') else 'general')
            try:
                leaf,_=check(directory,settings)
                result.update(valid=True,sha256=pki.fingerprint(leaf))
            except (OSError,ValueError) as error:
                if args.command=='check':
                    raise
                result.update(reason='HTTPS_IDENTITY_INVALID_OR_MISSING',detail=str(error))
            pending=directory/'renewal-status.json'
            try:
                result['renewal']=json.loads(pending.read_text()) if pending.exists() else None
                if isinstance(result['renewal'], dict) and result['renewal'].get('pki_mode') == 'custom':
                    result['renewal']['pki_mode'] = 'trina'
            except (OSError,ValueError):
                result['renewal']=None
        else:
            if not 1<=args.renew_window_days<=365:
                raise ValueError('Invalid renewal window')
            external=pki.is_external_identity(directory, 'https')
            reason=None
            try:
                leaf,_=check(directory,settings)
                expires=subprocess.run(['openssl','x509','-noout','-checkend',str(args.renew_window_days*86400)],
                    input=leaf,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60).returncode!=0
                if expires:
                    reason='expiring'
            except (OSError,ValueError):
                reason='missing_invalid_or_configuration_changed'
            status=dict(mode='external_ca',renewal_required=bool(reason),reason=reason)
            if external:
                status.update(pki_mode='trina',external_issuance_required=bool(reason),csr_generated=False)
            if reason and not external:
                status.update(generate_csr(directory,settings['config_file']))
            pki.atomic_write(directory/'renewal-status.json',json.dumps(status).encode(),0o644)
            if reason=='missing_invalid_or_configuration_changed':
                if external:
                    raise ValueError('External HTTPS identity is unavailable/invalid; import a replacement certificate/key; no CSR generated')
                raise ValueError('Signed HTTPS identity is unavailable/invalid; CSR ready, external CA issuance required')
            result=status
        print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    os.umask(0o077)
    try:
        main()
    except (OSError,ValueError,subprocess.SubprocessError) as exc:
        print('HTTPS PKI error: '+str(exc),file=sys.stderr)
        sys.exit(1)
