"""Offline end-to-end tests: real production CSR C helper, CA chains and import CLIs."""
import json
import os
from pathlib import Path
import shutil
import subprocess

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
import pytest

from provisioning.ca import CertificateAuthority, validate_csr
from provisioning.common import ROLES, digest, json_bytes, public_package
from provisioning.device import DeviceProvisioner

ROOT = Path(__file__).resolve().parents[2]
PASSWORD = 'Test-Offline-CA-Password-2026!'


@pytest.fixture(scope='module')
def workspace(tmp_path_factory):
    base = tmp_path_factory.mktemp('commissioning')
    helper = base/'modbus_tee_identity'
    subprocess.run(['cc','-std=c99','-Wall','-Wextra','-Werror','-Wno-deprecated-declarations',
                    '-DMODBUS_WITH_TEE=0','-I'+str(ROOT/'logger/lib'),
                    str(ROOT/'logger/scripts/modbus_tee_identity.c'),str(ROOT/'logger/lib/modbus_identity.c'),
                    '-lcrypto','-lpthread','-o',str(helper)], check=True, capture_output=True)
    app = base/'app'; app.mkdir()
    (app/'script').symlink_to(ROOT/'exec/app/script', target_is_directory=True)
    modbus, https = base/'modbus', base/'https'
    config = base/'device.ini'
    config.write_text('[TLS]\nca_file='+str(base/'trust/roots.pem')+'\n[HTTPS]\ndevice_ips=192.168.2.136\n')
    tool = DeviceProvisioner(app, config, 'file', modbus, https, helper)
    request = base/'request'
    tool.generate('LC400-test-001', request)
    ca = CertificateAuthority.initialize(base/'private-ca', PASSWORD, 'Test Enterprise')
    bundle = base/'bundle'
    ca.issue_package(request, bundle, PASSWORD)
    return dict(base=base, tool=tool, ca=ca, request=request, bundle=bundle)


def changed_package(original, target):
    shutil.copytree(original, target)
    return target


def rehash(path):
    manifest = json.loads((path/'manifest.json').read_text())
    for name in manifest['files']:
        manifest['files'][name] = digest((path/name).read_bytes())
    (path/'manifest.json').write_bytes(json_bytes(manifest))


def test_real_three_csrs_and_encrypted_ca(workspace):
    w = workspace
    public_package(w['request'], 'lc400-csr')
    assert len(list(w['request'].glob('*.csr'))) == 3
    for filename in ('root-key.pem','issuer-key.pem'):
        data = (w['ca'].directory/filename).read_bytes()
        assert b'BEGIN ENCRYPTED PRIVATE KEY' in data
        assert (w['ca'].directory/filename).stat().st_mode & 0o777 == 0o600
    for path in w['bundle'].iterdir():
        assert b'PRIVATE KEY' not in path.read_bytes()


def test_preflight_and_role_eku(workspace):
    w = workspace
    result = w['tool'].preflight(w['bundle'], [w['ca'].fingerprint()])
    assert len(result['identities']) == 3
    keys = set()
    for role in ROLES:
        cert = x509.load_pem_x509_certificate((w['bundle']/(role+'-leaf.pem')).read_bytes())
        eku = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        assert set(eku) == {ExtendedKeyUsageOID.CLIENT_AUTH if role=='master' else ExtendedKeyUsageOID.SERVER_AUTH}
        keys.add(cert.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo))
    assert len(keys) == 3


def test_wrong_password_and_existing_output_refused(workspace, tmp_path):
    w = workspace
    with pytest.raises(ValueError): w['ca'].issue_package(w['request'], tmp_path/'bad', 'wrong-password')
    with pytest.raises(ValueError, match='已存在'): w['ca'].issue_package(w['request'], w['bundle'], PASSWORD)
    assert len(w['ca'].records()) == 3


@pytest.mark.parametrize('fingerprints', [[], ['A'*64], ['bad']])
def test_trust_pin_required(workspace, fingerprints):
    with pytest.raises(ValueError, match='指纹'):
        workspace['tool'].preflight(workspace['bundle'], fingerprints)


def test_tamper_and_path_injection(workspace, tmp_path):
    bad = changed_package(workspace['bundle'], tmp_path/'bad')
    (bad/'master-leaf.pem').write_bytes(b'changed')
    with pytest.raises(ValueError, match='摘要'):
        workspace['tool'].preflight(bad, [workspace['ca'].fingerprint()])
    manifest = json.loads((bad/'manifest.json').read_text())
    manifest['files']['../../outside'] = 'A'*64
    (bad/'manifest.json').write_bytes(json_bytes(manifest))
    with pytest.raises(ValueError, match='未知文件'): public_package(bad, 'lc400-certificates')


def test_wrong_role_or_missing_chain(workspace, tmp_path):
    w = workspace
    bad = changed_package(w['bundle'], tmp_path/'role')
    (bad/'master-leaf.pem').write_bytes((bad/'slave-leaf.pem').read_bytes()); rehash(bad)
    with pytest.raises(ValueError): w['tool'].preflight(bad, [w['ca'].fingerprint()])
    bad = changed_package(w['bundle'], tmp_path/'chain')
    (bad/'intermediates.pem').write_bytes(b''); rehash(bad)
    with pytest.raises(ValueError): w['tool'].preflight(bad, [w['ca'].fingerprint()])


def test_duplicate_csr_keys_refused(workspace, tmp_path):
    w = workspace
    bad = changed_package(w['request'], tmp_path/'duplicate')
    (bad/'https.csr').write_bytes((bad/'slave.csr').read_bytes()); rehash(bad)
    with pytest.raises(ValueError): w['ca'].inspect_request(bad)


@pytest.mark.parametrize('days', [0,826,-1])
def test_issuance_duration_limit(workspace, tmp_path, days):
    with pytest.raises(ValueError): workspace['ca'].issue_package(workspace['request'], tmp_path/'out', PASSWORD, days)


def test_csr_privilege_and_weak_key_refused():
    for bits, ca in ((2048,False),(3072,True)):
        key = rsa.generate_private_key(public_exponent=65537,key_size=bits)
        csr = (x509.CertificateSigningRequestBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'test')]))
               .add_extension(x509.BasicConstraints(ca=ca,path_length=None),True).sign(key,hashes.SHA256()))
        with pytest.raises(ValueError): validate_csr(csr.public_bytes(serialization.Encoding.PEM),'master')


def test_import_rollback_and_crash_recovery(workspace, monkeypatch):
    w = workspace; tool = w['tool']; real = tool.run
    targets = [tool.settings['ca_file'],tool.modbus/'master.crt',tool.modbus/'slave.crt',tool.https/'g3.crt']
    original_files = {p:p.read_bytes() if p.exists() else None for p in targets}
    def original_restored():
        return all((p.read_bytes() if p.exists() else None)==data for p,data in original_files.items())
    def interrupted(args, timeout=180):
        if 'identity-import' in args and any(str(x).endswith('https_certificates.py') for x in args):
            raise RuntimeError('simulated import failure')
        return real(args, timeout)
    with monkeypatch.context() as patch:
        patch.setattr(tool,'run',interrupted)
        with pytest.raises(RuntimeError, match='simulated'):
            tool.import_bundle(w['bundle'], [w['ca'].fingerprint()])
    assert original_restored()
    assert not (tool.modbus/'deployment-recovery').exists()
    def power_loss(args, timeout=180):
        if 'identity-import' in args: raise KeyboardInterrupt('power loss')
        return real(args, timeout)
    with monkeypatch.context() as patch:
        patch.setattr(tool,'run',power_loss)
        with pytest.raises(KeyboardInterrupt): tool.import_bundle(w['bundle'], [w['ca'].fingerprint()])
    assert tool.settings['ca_file'].exists()
    assert tool.recover()['recovered']
    assert original_restored()


def test_import_and_preserve_private_keys(workspace):
    w = workspace; tool = w['tool']
    paths = [tool.modbus/'master.key',tool.modbus/'slave.key',tool.https/'g3.key']
    before = [p.read_bytes() for p in paths]
    ini_before = tool.config.read_bytes()
    result = tool.import_bundle(w['bundle'], [w['ca'].fingerprint()])
    assert result['imported'] and result['applied'] is False
    assert tool.check()['valid']
    assert before == [p.read_bytes() for p in paths]
    assert ini_before == tool.config.read_bytes()
    assert not (tool.modbus/'deployment-recovery').exists()


def test_apply_real_pki_checks_mock_services(workspace, monkeypatch):
    tool = workspace['tool']; real = tool.run; called = []
    tool.import_bundle(workspace['bundle'], [workspace['ca'].fingerprint()])
    def run(args, timeout=180):
        if str(args[0]) in ('systemctl','bash'):
            called.append(list(map(str,args)))
            if '--property=LoadState' in args: return 'loaded'
            return 'MODBUS_KEY_BACKEND=file LC_INI_PATH='+str(tool.config) if 'show' in args else ''
        return real(args,timeout)
    monkeypatch.setattr(tool,'run',run)
    assert tool.apply('test-tems.service', install_https=False)['applied']
    assert any('--apply' in cmd for cmd in called)
    assert ['systemctl','restart','test-tems.service'] in called
    called.clear()
    def wrong_env(args, timeout=180):
        if '--property=LoadState' in args: return 'loaded'
        if 'show' in args: return 'MODBUS_KEY_BACKEND=tee'
        return run(args,timeout)
    monkeypatch.setattr(tool,'run',wrong_env)
    with pytest.raises(ValueError, match='后端'): tool.apply('test-tems.service', install_https=False)
    assert not called


def test_revocation_and_signed_crl(workspace, tmp_path):
    ca = workspace['ca']; serial = ca.records()[0]['serial']
    ca.revoke(serial, PASSWORD, 'key_compromise')
    with pytest.raises(ValueError): ca.revoke(serial, PASSWORD)
    crl_path = tmp_path/'issuer-crl.pem'
    ca.export_crl(crl_path,PASSWORD)
    crl = x509.load_pem_x509_crl(crl_path.read_bytes())
    issuer = x509.load_pem_x509_certificate((ca.directory/'intermediates.pem').read_bytes())
    assert crl.is_signature_valid(issuer.public_key())
    assert crl.get_revoked_certificate_by_serial_number(int(serial,16)) is not None
    assert crl.extensions.get_extension_for_class(x509.CRLNumber).value.crl_number == 1


def test_no_overwrite_or_short_ca_password(tmp_path):
    with pytest.raises(ValueError): CertificateAuthority.initialize(tmp_path/'short','short')
    path=tmp_path/'existing'; path.mkdir(); (path/'do-not-touch').write_text('keep')
    with pytest.raises(ValueError): CertificateAuthority.initialize(path,PASSWORD)
    assert (path/'do-not-touch').read_text()=='keep'


def test_key_compromise_blocks_reissue(workspace, tmp_path):
    ca=workspace['ca']
    if not any(r['reason']=='key_compromise' for r in ca.records()):
        ca.revoke(ca.records()[0]['serial'],PASSWORD,'key_compromise')
    with pytest.raises(ValueError, match='泄露'):
        ca.issue_package(workspace['request'], tmp_path/'blocked', PASSWORD)
    assert not (tmp_path/'blocked').exists()
    assert len(ca.records())==3


def test_apply_reports_partial_failure(workspace, monkeypatch):
    tool=workspace['tool']; real=tool.run
    tool.import_bundle(workspace['bundle'], [workspace['ca'].fingerprint()])
    def fail_restart(args, timeout=180):
        if str(args[0])=='systemctl':
            if '--property=LoadState' in args: return 'loaded'
            if 'show' in args: return 'MODBUS_KEY_BACKEND=file LC_INI_PATH='+str(tool.config)
            raise RuntimeError('simulated service failure')
        if str(args[0])=='bash': return 'HTTPS applied'
        return real(args,timeout)
    monkeypatch.setattr(tool,'run',fail_restart)
    with pytest.raises(RuntimeError, match='HTTPS 已应用'):
        tool.apply('actual-tems.service',install_https=False)


def test_device_key_loss_is_not_replaced(workspace):
    tool=workspace['tool']; key=tool.modbus/'master.key'
    original=key.read_bytes(); key.unlink()
    try:
        with pytest.raises(RuntimeError): tool.check()
        assert not key.exists()
    finally:
        key.write_bytes(original); key.chmod(0o600)


def test_single_file_distributions(tmp_path):
    subprocess.run([os.sys.executable,str(ROOT/'build_provisioning_tools.py'),'--out',str(tmp_path)],check=True,capture_output=True)
    import zipfile
    for name in ('ca_manager','device_deploy'):
        path=tmp_path/(name+'.pyz')
        result=subprocess.run([os.sys.executable,str(path),'--help'],capture_output=True,text=True)
        assert result.returncode==0,result.stderr
        with zipfile.ZipFile(path) as archive:
            assert not any(n.endswith(('.pem','.sqlite3','.key')) for n in archive.namelist())


def test_csr_trailing_private_material_rejected(workspace):
    data=(workspace['request']/'master.csr').read_bytes()
    with pytest.raises(ValueError, match='单份'):
        validate_csr(data+b'PRIVATE MATERIAL','master')


def test_gui_approval_is_bound_to_request(workspace, tmp_path):
    ca=workspace['ca']
    with pytest.raises(ValueError, match='审查确认'):
        ca.issue_package(workspace['request'],tmp_path/'no-sign',PASSWORD,expected_review={'other':'request'})


def test_crl_cannot_overwrite_ca_private_data(workspace):
    ca=workspace['ca']; original=(ca.directory/'issuer-key.pem').read_bytes()
    with pytest.raises(ValueError, match='之外'):
        ca.export_crl(ca.directory/'issuer-key.pem',PASSWORD)
    assert (ca.directory/'issuer-key.pem').read_bytes()==original


def test_atomic_write_portable_permission_fallback(tmp_path, monkeypatch):
    from provisioning.common import atomic_write
    monkeypatch.delattr(os,'fchmod')
    path=tmp_path/'public.pem'
    atomic_write(path,b'public material',0o600)
    assert path.read_bytes()==b'public material'


def test_gui_module_imports_without_starting_tk():
    import provisioning.ui
    import ca_manager
    import device_deploy
    assert callable(ca_manager.gui) and callable(device_deploy.gui)


def test_native_device_launcher_runs_real_workflow(workspace, tmp_path):
    from build_provisioning_executables import build_device_agent
    import platform
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        pytest.skip('native Linux x86_64 launcher smoke test')
    executable, archive = build_device_agent(tmp_path/'dist','x86_64')
    tool=workspace['tool']
    args=[str(executable),'--app',str(tool.app),'--config',str(tool.config),
          '--modbus-dir',str(tool.modbus),'--https-dir',str(tool.https),'--helper',str(tool.helper)]
    env=dict(os.environ,LC400_PYTHON=os.sys.executable)
    result=subprocess.run(args+['check'],capture_output=True,text=True,env=env,timeout=60)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['valid']
    assert archive.is_file()
    # Prove arguments and path-with-spaces survive the native exec -> Python zipapp boundary.
    spaced=tmp_path/'device deploy'
    shutil.copyfile(executable,spaced);spaced.chmod(0o755)
    result=subprocess.run([str(spaced),'--help'],capture_output=True,text=True,env=env,timeout=30)
    assert result.returncode==0 and 'generate' in result.stdout
    result=subprocess.run([str(spaced),'--help'],capture_output=True,text=True,
                          env=dict(env,LC400_PYTHON='relative-python'),timeout=30)
    assert result.returncode!=0 and 'absolute path' in result.stderr


def test_bundled_ca_executable_password_and_issuance(workspace, tmp_path):
    source=os.environ.get('LC400_CA_TEST_EXECUTABLE')
    if not source:
        pytest.skip('set LC400_CA_TEST_EXECUTABLE to validate a built desktop distribution')
    # A relocated distribution, including spaces, must not rely on the development venv.
    moved=tmp_path/'CA runtime relocated'
    shutil.copytree(Path(source).parent,moved)
    executable=moved/Path(source).name
    ca=tmp_path/'native-ca'; vault=tmp_path/'native-password.lcvault'
    protection='Executable-Test-Protection-2026!'
    environment=dict(os.environ,PATH='/usr/bin:/bin',PYTHONHOME='/nonexistent-python',
                     PYTHONPATH='/nonexistent-packages',LD_LIBRARY_PATH='/nonexistent-libs')
    environment.pop('VIRTUAL_ENV',None)
    def command(args,stdin=''):
        result=subprocess.run([str(executable),'--ca-dir',str(ca),*args],input=stdin,
                              capture_output=True,text=True,env=environment,timeout=90)
        assert result.returncode==0,result.stderr
        assert protection not in result.stdout+result.stderr
        return json.loads(result.stdout)
    assert command(['password-generate','--out',str(vault)],protection+'\n'+protection+'\n')['encrypted']
    assert command(['--vault-file',str(vault),'init'],protection+'\n')['root_fingerprint']
    assert command(['--vault-file',str(vault),'password-check'],protection+'\n')['ca_verified']
    issued=tmp_path/'native-issued'
    result=command(['--vault-file',str(vault),'sign',str(workspace['request']),str(issued)],protection+'\n')
    assert result['kind']=='lc400-certificates'
    for role in ROLES:
        check=subprocess.run(['openssl','verify','-CAfile',str(issued/'roots.pem'),'-untrusted',
            str(issued/'intermediates.pem'),str(issued/(role+'-leaf.pem'))],capture_output=True,text=True)
        assert check.returncode==0,check.stderr
    assert len(command(['list']))==3
    environment.pop('DISPLAY',None)
    result=subprocess.run([str(executable),'gui'],env=environment,capture_output=True,text=True,timeout=20)
    assert 'display' in result.stderr.lower(),result.stderr
    assert 'ModuleNotFoundError' not in result.stderr
    # Verify the released manifest includes nested Python/runtime files.
    for line in (moved/'SHA256SUMS').read_text().splitlines():
        expected,name=line.split('  ',1)
        assert digest((moved/name).read_bytes())==expected


def test_ca_delivery_record_and_legacy_manifest(workspace, tmp_path):
    from provisioning.deployment_record import load_record
    bundle = workspace['bundle']
    loaded = load_record(bundle/'deployment.json')
    assert loaded['root_fingerprints'] == [workspace['ca'].fingerprint()]
    assert loaded['bundle'] == str(bundle)
    assert loaded == load_record(bundle/'manifest.json')
    relocated = changed_package(bundle, tmp_path/'relocated')
    assert load_record(relocated/'deployment.json')['bundle'] == str(relocated)
    record = json.loads((relocated/'deployment.json').read_text())
    record['root_fingerprints'] = ['0'*64]
    (relocated/'deployment.json').write_bytes(json_bytes(record))
    with pytest.raises(ValueError, match='不匹配'):
        load_record(relocated/'deployment.json')


def test_delivery_record_rejects_rehashed_wrong_root(workspace, tmp_path):
    from provisioning.deployment_record import load_record
    bundle = changed_package(workspace['bundle'], tmp_path/'wrong-root-record')
    manifest = json.loads((bundle/'manifest.json').read_text())
    manifest['root_fingerprints'] = ['0'*64]
    (bundle/'manifest.json').write_bytes(json_bytes(manifest))
    with pytest.raises(ValueError, match='根证书'):
        load_record(bundle/'manifest.json')
