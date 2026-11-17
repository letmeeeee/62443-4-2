"""OpenSSL-based external-CA provisioning shared by HTTPS and Modbus tools."""
import configparser
import contextlib
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

DEFAULT_CONFIG = '/home/zlg/lc_data_set.ini'
DEFAULT_CA = '/etc/ems/pki/ca-roots.crt'
PEM = re.compile(rb'-----BEGIN CERTIFICATE-----\s+.*?-----END CERTIFICATE-----', re.S)


def run(*arguments, data=None):
    result = subprocess.run(['openssl', *map(str,arguments)], input=data,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    if result.returncode:
        raise ValueError(result.stderr.decode(errors='replace').strip() or 'OpenSSL verification failed')
    return result.stdout


def read_config(path=None):
    source=Path(path or os.environ.get('LC_INI_PATH',DEFAULT_CONFIG))
    parser=configparser.ConfigParser(interpolation=None,strict=False)
    if source.exists():
        with source.open(encoding='utf-8-sig') as stream:
            parser.read_file(stream)
    elif path or os.environ.get('LC_INI_PATH'):
        raise ValueError('TLS configuration file not found')
    mode=parser.get('TLS','certificate_mode',fallback='external_ca').strip()
    if mode != 'external_ca':
        raise ValueError('Only external_ca certificate provisioning is supported; remove the old mode setting')
    ca=Path(parser.get('TLS','ca_file',fallback=DEFAULT_CA).strip())
    if not ca.is_absolute():
        raise ValueError('[TLS] ca_file must be an absolute path')
    crl = Path(parser.get('TLS', 'crl_file', fallback=str(ca) + '.crls.pem').strip())
    if not crl.is_absolute() or crl == ca:
        raise ValueError('[TLS] crl_file must be absolute and different from ca_file')
    return dict(mode=mode,ca_file=ca,crl_file=crl,config_file=source)


def certificates(data):
    if len(data)>1024*1024:
        raise ValueError('Certificate input exceeds 1 MiB')
    blocks=PEM.findall(data)
    if not blocks or PEM.sub(b'',data).strip():
        raise ValueError('Only PEM certificates are accepted; no private keys or CSRs')
    return [run('x509','-outform','PEM',data=block) for block in blocks]


def fingerprint(cert):
    return hashlib.sha256(run('x509','-outform','DER',data=cert)).hexdigest().upper()


def public_key(cert):
    pem=run('x509','-pubkey','-noout',data=cert)
    return run('pkey','-pubin','-outform','DER',data=pem)


def csr_public_key(csr):
    run('req','-verify','-noout',data=csr)
    pem=run('req','-pubkey','-noout',data=csr)
    return run('pkey','-pubin','-outform','DER',data=pem)


def san_values(data, csr=False):
    text=run('req','-text','-noout',data=data).decode() if csr else run(
        'x509','-noout','-ext','subjectAltName',data=data).decode()
    match=re.search(r'X509v3 Subject Alternative Name:[^\n]*\n\s*([^\n]+)',text)
    result=set()
    if match:
        for value in match.group(1).split(','):
            kind,_,name=value.strip().partition(':')
            if kind=='IP Address':
                result.add(('IP',str(ipaddress.ip_address(name))))
            elif kind=='DNS':
                result.add(('DNS',name.lower()))
    return result


def subject_cn(data, csr=False):
    command='req' if csr else 'x509'
    value=run(command,'-subject','-noout','-nameopt','RFC2253',data=data).decode().strip()
    match=re.search(r'(?:subject=|,)CN=([^,]+)',value)
    if not match:
        raise ValueError('Certificate/CSR requires a CN')
    return match.group(1)


def check_ca(cert):
    constraints=run('x509','-noout','-ext','basicConstraints',data=cert).decode()
    usage=run('x509','-noout','-ext','keyUsage',data=cert).decode()
    if 'CA:TRUE' not in constraints or 'Certificate Sign' not in usage:
        raise ValueError('CA certificate requires CA:TRUE and keyCertSign')


def validate_roots(data):
    roots=certificates(data)
    with tempfile.TemporaryDirectory(prefix='lc-ca-') as directory:
        for index,cert in enumerate(roots):
            check_ca(cert)
            path=Path(directory)/str(index)
            path.write_bytes(cert)
            run('verify','-no-CAfile','-no-CApath','-trusted',path,'-check_ss_sig',
                '-auth_level','2','-purpose','any',path)
            names=run('x509','-subject','-issuer','-noout','-nameopt','RFC2253',data=cert).decode().splitlines()
            if names[0].partition('=')[2] != names[1].partition('=')[2]:
                raise ValueError('Trust anchors must be self-signed roots; import intermediates with the leaf')
    return b''.join(roots)


def validate_identity(data, chain, roots_path, purpose, csr=None, crl_path=None,
                      require_fresh_crl=False):
    roots=validate_roots(Path(roots_path).read_bytes())
    anchors={fingerprint(cert) for cert in certificates(roots)}
    incoming=certificates(data)
    leaf=incoming[0]
    intermediates=incoming[1:]+(certificates(chain) if chain else [])
    if 'CA:FALSE' not in run('x509','-noout','-ext','basicConstraints',data=leaf).decode():
        raise ValueError('Identity must explicitly declare CA:FALSE')
    expected='TLS Web Client Authentication' if purpose=='sslclient' else 'TLS Web Server Authentication'
    usage=run('x509','-noout','-ext','extendedKeyUsage',data=leaf).decode()
    other='TLS Web Server Authentication' if purpose=='sslclient' else 'TLS Web Client Authentication'
    if expected not in usage or other in usage:
        raise ValueError('Identity EKU does not match its role')
    if 'Digital Signature' not in run('x509','-noout','-ext','keyUsage',data=leaf).decode():
        raise ValueError('Identity requires digitalSignature key usage')
    clean=[]
    seen={fingerprint(leaf)}
    for cert in intermediates:
        check_ca(cert)
        digest=fingerprint(cert)
        if digest not in anchors and digest not in seen:
            clean.append(cert)
            seen.add(digest)
    if fingerprint(leaf) in anchors:
        raise ValueError('A trust root cannot be used as a device identity')
    previous=leaf
    for cert in clean:
        issuer=run('x509','-issuer','-noout','-nameopt','RFC2253',data=previous).decode().partition('=')[2].strip()
        subject=run('x509','-subject','-noout','-nameopt','RFC2253',data=cert).decode().partition('=')[2].strip()
        if issuer!=subject:
            raise ValueError('Intermediate chain must be ordered from leaf issuer to root, without unrelated certificates')
        previous=cert
    if csr:
        if public_key(leaf)!=csr_public_key(csr) or subject_cn(leaf)!=subject_cn(csr,True):
            raise ValueError('Issued identity does not match the CSR public key/CN')
        if not san_values(csr,True).issubset(san_values(leaf)):
            raise ValueError('Issued identity does not contain all requested SANs')
    with tempfile.TemporaryDirectory(prefix='lc-chain-') as directory:
        root=Path(directory)/'roots.pem';root.write_bytes(roots)
        certificate=Path(directory)/'leaf.pem';certificate.write_bytes(leaf)
        untrusted=Path(directory)/'intermediates.pem';untrusted.write_bytes(b''.join(clean))
        command=['verify','-no-CAfile','-no-CApath','-trusted',root,'-auth_level','2',
                 '-verify_depth','8','-purpose',purpose]
        if clean:
            command+=['-untrusted',untrusted]
        run(*command,certificate)
    if crl_path is not None and (Path(crl_path).exists() or Path(crl_path).is_symlink()):
        try:
            from . import crl_store
        except ImportError:
            import crl_store
        result = crl_store.certificate_status(leaf + b''.join(clean), roots_path, crl_path)
        if result['revocationStatus'] in ('revoked', 'unknown') or (
                require_fresh_crl and result['revocationStatus'] == 'stale'):
            raise ValueError('Certificate revocation check failed: ' + result['revocationReason'])
    return leaf,b''.join(clean)


def atomic_write(path, data, mode=0o600):
    path=Path(path)
    if path.is_symlink():
        raise ValueError('Symbolic links are not accepted')
    fd,temporary=tempfile.mkstemp(prefix='.'+path.name+'-',dir=str(path.parent))
    try:
        with os.fdopen(fd,'wb') as stream:
            os.fchmod(stream.fileno(),mode)
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
        directory_fd=os.open(str(path.parent),os.O_RDONLY|os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextlib.contextmanager
def locked(directory):
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    if directory.is_symlink():
        raise ValueError('Symbolic link directory is not accepted')
    fd=os.open(str(directory/'.pki.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX)
        yield


def operation_lock(settings):
    """Serialize identity/CA/CRL imports with the application endpoint."""
    return locked(settings['ca_file'].parent / '.certificate-operations')


def pending_path(settings, service):
    if service not in ('nginx', 'tems'):
        raise ValueError('Unknown certificate service')
    return settings['ca_file'].parent / ('.' + service + '-apply-required')


def mark_pending(settings, service, reason):
    path = pending_path(settings, service)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    atomic_write(path, json.dumps(dict(reason=reason, updatedAt=time.time_ns())).encode(), 0o600)


def pending_services(settings):
    return [service for service in ('nginx', 'tems') if pending_path(settings, service).exists()]


def identity_source_path(directory, role):
    if role not in ('master', 'slave', 'https'):
        raise ValueError('Unknown identity role')
    return Path(directory) / ('.' + ('g3' if role == 'https' else role) + '-pki-source.json')


def is_external_identity(directory, role):
    # Presence is conservative: even damaged metadata must not trigger automatic key/CSR creation.
    marker = identity_source_path(directory, role)
    if marker.is_symlink():
        raise ValueError('Identity source marker cannot be a symbolic link')
    return marker.exists()


def import_roots(path, data, expected=None, identity_dirs=None):
    validated=validate_roots(data)
    roots=certificates(validated)
    if expected:
        actual={fingerprint(cert) for cert in roots}
        wanted={value.replace(':','').strip().upper() for value in expected}
        if actual!=wanted:
            raise ValueError('CA root fingerprint mismatch')
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o755)
    with locked(path.parent):
        if not path.exists() or path.read_bytes() != validated:
            modbus, https = identity_dirs or (
                Path(os.environ.get('MODBUS_CERT_DIR', '/etc/ems/modbus')),
                Path(os.environ.get('HTTPS_CERT_DIR', '/etc/ssl/g3')),
            )
            with tempfile.TemporaryDirectory(prefix='root-check-') as folder:
                candidate = Path(folder) / 'roots.pem'
                candidate.write_bytes(validated)
                for role, certificate in (('master', Path(modbus) / 'master.crt'),
                                          ('slave', Path(modbus) / 'slave.crt'),
                                          ('https', Path(https) / 'g3.crt')):
                    if certificate.is_symlink():
                        raise ValueError('Symbolic link identity rejected: ' + role)
                    if certificate.exists():
                        try:
                            validate_identity(certificate.read_bytes(), None, candidate,
                                              'sslclient' if role == 'master' else 'sslserver')
                        except ValueError as error:
                            raise ValueError('Shared root replacement invalidates role=' + role
                                             + ': ' + str(error)) from error
        if path.exists():
            atomic_write(path.with_name(path.name+'.previous'),path.read_bytes())
        for service in ('nginx', 'tems'):
            mark_pending(dict(ca_file=path), service, 'shared-ca')
        atomic_write(path,validated,0o644)
    return [fingerprint(cert) for cert in roots]
