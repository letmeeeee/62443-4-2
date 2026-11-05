"""Offline test-only CA. Its private keys never enter a device identity directory."""
from pathlib import Path
import secrets
import subprocess


def openssl(*arguments):
    result=subprocess.run(['openssl',*map(str,arguments)],capture_output=True,timeout=60)
    if result.returncode:
        raise AssertionError(result.stderr.decode(errors='replace'))
    return result.stdout


def make_ca(directory,name='test-ca'):
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    root=directory/'root.crt';root_key=directory/'root.key'
    intermediate=directory/'intermediate.crt';intermediate_key=directory/'intermediate.key'
    configuration=directory/'request.cnf'
    configuration.write_text('[req]\ndistinguished_name=dn\n[dn]\n')
    openssl('req','-config',configuration,'-x509','-newkey','rsa:2048','-nodes','-sha256','-days','3650',
        '-keyout',root_key,'-out',root,'-subj','/CN='+name,
        '-addext','basicConstraints=critical,CA:TRUE',
        '-addext','keyUsage=critical,keyCertSign,cRLSign','-addext','subjectKeyIdentifier=hash')
    request=directory/'intermediate.csr'
    openssl('req','-new','-newkey','rsa:2048','-nodes','-keyout',intermediate_key,
            '-out',request,'-subj','/CN='+name+'-intermediate')
    extensions=directory/'intermediate.ext'
    extensions.write_text('basicConstraints=critical,CA:TRUE,pathlen:0\nkeyUsage=critical,keyCertSign,cRLSign\n'
                          'subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n')
    openssl('x509','-req','-in',request,'-CA',root,'-CAkey',root_key,'-set_serial','2',
            '-days','3650','-sha256','-extfile',extensions,'-out',intermediate)
    return dict(root=root,root_key=root_key,intermediate=intermediate,intermediate_key=intermediate_key)


def sign_csr(csr,destination,ca,role='server',ips=(),days=365):
    destination=Path(destination)
    extensions=destination.with_suffix('.ext')
    data='basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n'
    data+='extendedKeyUsage='+('clientAuth' if role=='client' else 'serverAuth')+'\n'
    data+='subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n'
    if ips:
        data+='subjectAltName='+','.join('IP:'+value for value in ips)+'\n'
    extensions.write_text(data)
    openssl('x509','-req','-in',csr,'-CA',ca['intermediate'],'-CAkey',ca['intermediate_key'],
        '-set_serial',str(secrets.randbits(64)+1),'-days',str(days),'-sha256',
        '-extfile',extensions,'-out',destination)
    return destination
