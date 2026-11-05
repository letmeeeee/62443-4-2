"""CA-only CSR, role isolation, trust and rejection tests with real OpenSSL."""
import base64
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import types

import pytest
from flask import Blueprint
from pki_test_helpers import make_ca,sign_csr,openssl
from test_auth_session import auth_app,login
from script import pki_common as pki

ROOT=Path(__file__).resolve().parents[3]


@pytest.fixture(scope='session')
def identity_binary(tmp_path_factory):
    output=tmp_path_factory.mktemp('ca-identity')/'identity'
    result=subprocess.run(['cc','-std=c99','-Wall','-Wextra','-Werror',
        '-Wno-deprecated-declarations','-DMODBUS_WITH_TEE=0','-I'+str(ROOT/'logger/lib'),
        str(ROOT/'logger/scripts/modbus_tee_identity.c'),str(ROOT/'logger/lib/modbus_identity.c'),
        '-lcrypto','-lpthread','-o',str(output)],capture_output=True)
    assert result.returncode==0,result.stderr.decode()
    return output


@pytest.fixture(scope='session')
def authority(tmp_path_factory):
    return make_ca(tmp_path_factory.mktemp('offline-ca'))


@pytest.fixture
def device(tmp_path,identity_binary,authority):
    directory=tmp_path/'modbus'
    https=tmp_path/'https'
    roots=tmp_path/'trust'/'roots.crt'
    config=tmp_path/'device.ini'
    config.write_text('[TLS]\nca_file='+str(roots)+'\n[HTTPS]\ndevice_ips=127.0.0.1\n')
    env=dict(os.environ,MODBUS_TEE_IDENTITY=str(identity_binary),MODBUS_KEY_BACKEND='file',LC_INI_PATH=str(config))
    def tool(role,*arguments,success=True):
        script=ROOT/('exec/app/script/modbus_certs.py' if role=='modbus' else 'exec/app/script/https_certificates.py')
        location=directory if role=='modbus' else https
        result=subprocess.run([sys.executable,str(script),'--config',str(config),'--dir',str(location),*map(str,arguments)],
            env=env,capture_output=True,timeout=60)
        assert (result.returncode==0)==success,result.stderr.decode()
        return result
    tool('modbus','ca-import','--cert',authority['root'],'--fingerprint',pki.fingerprint(authority['root'].read_bytes()))
    return dict(modbus=directory,https=https,roots=roots,config=config,env=env,tool=tool)


def test_three_independent_keys_and_ca_chains(device,authority,tmp_path):
    tool=device['tool']
    public=[]
    for role in ('master','slave'):
        args=['--ip','127.0.0.1'] if role=='slave' else []
        tool('modbus','csr','--role',role,'--name','test-'+role,*args)
        csr=device['modbus']/(role+'.csr')
        public.append(pki.csr_public_key(csr.read_bytes()))
        leaf=sign_csr(csr,tmp_path/(role+'.crt'),authority,role='client' if role=='master' else 'server',ips=['127.0.0.1'] if role=='slave' else [])
        tool('modbus','identity-import','--role',role,'--cert',leaf,'--chain',authority['intermediate'])
        tool('modbus','check','--role',role)
        original=(device['modbus']/(role+'.key')).read_bytes()
        tool('modbus','csr','--role',role,'--name','test-'+role,*args)
        assert (device['modbus']/(role+'.key')).read_bytes()==original
        exported=tmp_path/(role+'-export.csr')
        tool('modbus','csr-export','--role',role,'--out',exported)
        assert exported.read_bytes()==csr.read_bytes()
    tool('https','csr')
    csr=device['https']/'g3.csr'
    public.append(pki.csr_public_key(csr.read_bytes()))
    assert len(set(public))==3
    leaf=sign_csr(csr,tmp_path/'https.crt',authority,ips=['127.0.0.1'])
    tool('https','identity-import','--cert',leaf,'--chain',authority['intermediate'])
    tool('https','check')
    assert (device['https']/'g3.crt').read_bytes().count(b'BEGIN CERTIFICATE')==2
    assert not any(path.name in ('root.key','intermediate.key') for path in tmp_path.rglob('*.key'))


@pytest.mark.parametrize('failure',['missing-chain','wrong-role','wrong-key','wrong-ca','missing-san','expired','tampered'])
def test_invalid_identity_never_replaces_existing_certificate(device,authority,tmp_path,failure):
    tool=device['tool']
    tool('modbus','csr','--role','slave','--name','test-slave','--ip','127.0.0.1')
    csr=device['modbus']/'slave.csr'
    valid=sign_csr(csr,tmp_path/'valid.crt',authority,ips=['127.0.0.1'])
    tool('modbus','identity-import','--role','slave','--cert',valid,'--chain',authority['intermediate'])
    original=(device['modbus']/'slave.crt').read_bytes()
    issuer=make_ca(tmp_path/'other-ca','other-ca') if failure=='wrong-ca' else authority
    signing_csr=csr
    if failure=='wrong-key':
        signing_csr=tmp_path/'other.csr'
        openssl('req','-new','-newkey','rsa:2048','-nodes','-subj','/CN=test-slave',
                '-keyout',tmp_path/'other.key','-out',signing_csr)
    leaf=sign_csr(signing_csr,tmp_path/'bad.crt',issuer,
        role='client' if failure=='wrong-role' else 'server',
        ips=[] if failure=='missing-san' else ['127.0.0.1'],days=-1 if failure=='expired' else 365)
    if failure=='tampered':
        der=bytearray(openssl('x509','-in',leaf,'-outform','DER'));der[-1]^=1
        encoded=base64.encodebytes(bytes(der))
        leaf.write_bytes(b'-----BEGIN CERTIFICATE-----\n'+encoded+b'-----END CERTIFICATE-----\n')
    args=[] if failure=='missing-chain' else ['--chain',issuer['intermediate']]
    tool('modbus','identity-import','--role','slave','--cert',leaf,*args,success=False)
    assert (device['modbus']/'slave.crt').read_bytes()==original


def test_removed_self_signing_operations_and_missing_keys_fail_closed(device):
    tool=device['tool']
    tool('modbus','generate','--role','master','--name','old',success=False)
    tool('modbus','renew','--role','master','--name','old',success=False)
    tool('modbus','trust-add','--cert',device['roots'],success=False)
    tool('https','csr')
    key=device['https']/'g3.key';key.unlink()
    tool('https','csr',success=False)
    assert not key.exists() and not (device['https']/'g3.crt').exists()


def test_legacy_mode_cannot_enable_a_fallback(device):
    with device['config'].open('a') as stream:
        stream.write('\n[TLS]\ncertificate_mode=self_signed\n')
    device['tool']('modbus','csr','--role','master','--name','old',success=False)
    device['tool']('https','csr',success=False)


def test_ca_root_fingerprint_mismatch_and_leaf_anchor_rejected(device,authority,tmp_path):
    tool=device['tool']
    original=device['roots'].read_bytes()
    tool('modbus','ca-import','--cert',authority['root'],'--fingerprint','0'*64,success=False)
    tool('https','csr')
    leaf=sign_csr(device['https']/'g3.csr',tmp_path/'leaf.crt',authority,ips=['127.0.0.1'])
    tool('modbus','ca-import','--cert',leaf,success=False)
    assert device['roots'].read_bytes()==original


def test_https_expired_issued_identity_is_not_replaced_by_a_local_leaf(device,authority,tmp_path):
    tool=device['tool']
    tool('https','csr')
    expired=sign_csr(device['https']/'g3.csr',tmp_path/'expired.crt',authority,ips=['127.0.0.1'],days=-1)
    identity=expired.read_bytes()+authority['intermediate'].read_bytes()
    (device['https']/'g3.crt').write_bytes(identity)
    key=(device['https']/'g3.key').read_bytes()
    tool('https','reconcile',success=False)
    assert (device['https']/'g3.crt').read_bytes()==identity
    assert (device['https']/'g3.key').read_bytes()==key


def test_admin_http_csr_and_import_contract(auth_app,device,authority,tmp_path,monkeypatch):
    app,_,_=auth_app
    config=sys.modules['config']
    config.INI_PATH=device['config'];config.STATE_DONE=3;config.STATE_ERROR=-1
    app.config.update(MODBUS_CERT_DIR=str(device['modbus']),HTTPS_CERT_DIR=str(device['https']))
    monkeypatch.setenv('MODBUS_TEE_IDENTITY',device['env']['MODBUS_TEE_IDENTITY'])
    monkeypatch.setenv('MODBUS_KEY_BACKEND','file')
    module=types.ModuleType('routes.route_g3');module.g3_bp=Blueprint('ca-test',__name__)
    monkeypatch.setitem(sys.modules,'routes.route_g3',module)
    spec=importlib.util.spec_from_file_location('ca_test_routes',ROOT/'exec/app/routes/route_cert.py')
    routes=importlib.util.module_from_spec(spec);spec.loader.exec_module(routes)
    routes.CERT_SCRIPT=ROOT/'exec/app/script/modbus_certs.py'
    app.register_blueprint(module.g3_bp)
    client=app.test_client();credentials=login(client,'admin').json
    headers={'X-CSRF-Token':credentials['csrf_token']}
    assert client.post('/api/cert/generate',json={},headers=headers).status_code==410
    assert client.post('/api/cert/csr',json=dict(role='master',name='http-master'),headers=headers).status_code==200
    exported=client.get('/api/cert/csr/export?role=master')
    assert exported.status_code==200 and b'CERTIFICATE REQUEST' in exported.data
    leaf=sign_csr(device['modbus']/'master.csr',tmp_path/'http-master.crt',authority,role='client')
    response=client.post('/api/cert/identity/import',headers=headers,data={
        'role':'master','file':(io.BytesIO(leaf.read_bytes()),'identity.crt'),
        'chain':(io.BytesIO(authority['intermediate'].read_bytes()),'chain.crt')})
    assert response.status_code==200 and response.json['data']['restart_required']
    assert client.get('/api/cert/check?role=master').json['data']['chain_verified']
    assert client.post('/api/cert/https/csr',json={},headers=headers).status_code==200
    assert client.get('/api/cert/https/csr/export').status_code==200
    visitor=app.test_client();visitor_credentials=login(visitor).json
    assert visitor.post('/api/cert/csr',json=dict(role='master',name='forbidden'),
        headers={'X-CSRF-Token':visitor_credentials['csrf_token']}).status_code==403
