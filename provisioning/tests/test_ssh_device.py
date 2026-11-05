"""Real localhost OpenSSH/SFTP round trips, using production device CSR and import code."""
import base64
import getpass
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import zipfile

import paramiko
import pytest

from provisioning.common import public_package
from provisioning.ssh_device import SSHDeviceProvisioner, RemoteDeploymentError, agent_archive, fingerprint
from provisioning.tests.test_provisioning import workspace


@pytest.fixture(scope='module')
def ssh_server(tmp_path_factory):
    if not shutil.which('sshd') or not shutil.which('ssh-keygen'):
        pytest.skip('OpenSSH test server not installed')
    base=tmp_path_factory.mktemp('lc400-test-sshd')
    host_key=base/'host';identity=base/'identity';known=base/'known_hosts'
    for path in (host_key,identity):
        subprocess.run(['ssh-keygen','-q','-t','ed25519','-N','','-f',str(path)],check=True,capture_output=True)
    rsa_key=base/'host_rsa'
    subprocess.run(['ssh-keygen','-q','-t','rsa','-b','3072','-N','','-f',str(rsa_key)],check=True,capture_output=True)
    authorized=base/'authorized_keys';shutil.copyfile(str(identity)+'.pub',authorized)
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
    configuration=base/'sshd_config'
    configuration.write_text('\n'.join([
        'Port '+str(port),'ListenAddress 127.0.0.1','HostKey '+str(host_key),
        'HostKey '+str(rsa_key),'PidFile '+str(base/'sshd.pid'),'AuthorizedKeysFile '+str(authorized),
        'StrictModes no','UsePAM no','PasswordAuthentication no','PubkeyAuthentication yes',
        'KbdInteractiveAuthentication no','Subsystem sftp internal-sftp',
        'AllowUsers '+getpass.getuser(),'LogLevel VERBOSE','PermitRootLogin prohibit-password','']))
    log=base/'server.log'
    with log.open('wb') as stream:
        process=subprocess.Popen([shutil.which('sshd'),'-D','-e','-f',str(configuration)],stdout=stream,stderr=stream)
    try:
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            if process.poll() is not None:
                raise AssertionError(log.read_text())
            try:
                probe=socket.create_connection(('127.0.0.1',port),timeout=0.2);probe.close();break
            except OSError:time.sleep(0.05)
        else:raise AssertionError('Test SSH server did not start')
        key=paramiko.Ed25519Key.from_private_key_file(str(host_key))
        hosts=paramiko.HostKeys();hosts.add('[127.0.0.1]:'+str(port),key.get_name(),key);hosts.save(str(known))
        yield dict(base=base,host='127.0.0.1',port=port,user=getpass.getuser(),identity=identity,
                   pin=fingerprint(key),known=known,rsa_key=rsa_key,log=log)
    finally:
        process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.wait()


def client(server,workspace,**override):
    tool=workspace['tool']
    values=dict(host=server['host'],port=server['port'],username=server['user'],identity_file=server['identity'],
        host_fingerprint=server['pin'],options=dict(app=str(tool.app),config=str(tool.config),backend='file',
            modbus_dir=str(tool.modbus),https_dir=str(tool.https),helper=str(tool.helper)))
    values.update(override)
    return SSHDeviceProvisioner(**values)


def test_pc_import_has_no_device_only_dependency():
    root=Path(__file__).resolve().parents[2]
    result=subprocess.run([sys.executable,'-c',
        "import sys;sys.modules['fcntl']=None;import device_deploy;print('PC import OK')"],
        cwd=str(root),capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    data=agent_archive()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert 'provisioning/device.py' in archive.namelist()
        assert not any(name.endswith(('.key','.pem','.lcvault')) for name in archive.namelist())


def test_ssh_probe_does_not_trust_or_authenticate(ssh_server,workspace):
    tool=client(ssh_server,workspace,host_fingerprint=None)
    result=tool.probe()
    assert result['trusted'] is False and result['ssh_fingerprint']==ssh_server['pin']
    assert tool.client is None
    with pytest.raises(RemoteDeploymentError,match='未知 SSH'):
        tool.connect()


def test_host_pin_and_known_hosts_checked_before_auth(ssh_server,workspace):
    wrong='SHA256:'+base64.b64encode(b'X'*32).decode().rstrip('=')
    with pytest.raises(RemoteDeploymentError,match='指纹不匹配'):
        client(ssh_server,workspace,host_fingerprint=wrong).connect()
    with client(ssh_server,workspace,host_fingerprint=None,known_hosts=ssh_server['known']) as tool:
        assert tool.info()['ready']
    rsa_known=ssh_server['base']/'rsa_known_hosts'
    recorded=paramiko.HostKeys()
    key=paramiko.RSAKey.from_private_key_file(str(ssh_server['rsa_key']))
    recorded.add('[127.0.0.1]:'+str(ssh_server['port']),key.get_name(),key);recorded.save(str(rsa_known))
    with client(ssh_server,workspace,host_fingerprint=None,known_hosts=rsa_known) as tool:
        assert tool.info()['ready']

    bad=ssh_server['base']/'wrong_known_hosts'
    keys=paramiko.HostKeys()
    key=paramiko.Ed25519Key.from_private_key_file(str(ssh_server['identity']))
    keys.add('[127.0.0.1]:'+str(ssh_server['port']),key.get_name(),key);keys.save(str(bad))
    with pytest.raises(RemoteDeploymentError,match='known_hosts 不一致'):
        client(ssh_server,workspace,known_hosts=bad).connect()


def test_info_and_remote_generate_to_pc(ssh_server,workspace,tmp_path):
    before=set(Path('/tmp').glob('lc400-pc-*'))
    original=[(workspace['tool'].modbus/(r+'.key')).read_bytes() for r in ('master','slave')]
    original.append((workspace['tool'].https/'g3.key').read_bytes())
    out=tmp_path/'downloaded request'
    with client(ssh_server,workspace) as tool:
        info=tool.info()
        assert info['ready'] and info['configuration_exists']
        result=tool.generate('LC400-test-001',out)
        assert result['downloaded'] and 'public_files' not in result
    manifest=public_package(out,'lc400-csr')
    assert manifest['device_id']=='LC400-test-001'
    assert set(p.name for p in out.iterdir())=={'master.csr','slave.csr','https.csr','manifest.json'}
    assert original[:2]==[(workspace['tool'].modbus/(r+'.key')).read_bytes() for r in ('master','slave')]
    assert original[2]==(workspace['tool'].https/'g3.key').read_bytes()
    assert set(Path('/tmp').glob('lc400-pc-*'))==before


def test_remote_import_check_no_private_material_upload(ssh_server,workspace):
    bundle=workspace['bundle']
    (bundle/'must-not-upload.key').write_text('FAKE PRIVATE MATERIAL NEVER TRANSFER')
    pin=workspace['ca'].fingerprint()
    with client(ssh_server,workspace) as tool:
        uploads=[];upload=tool._upload
        def observed(path,data):
            uploads.append((path,data));return upload(path,data)
        tool._upload=observed
        assert tool.preflight(bundle,[pin])['valid']
        assert tool.import_bundle(bundle,[pin])['imported']
        assert tool.check()['valid']
        assert not any(path.endswith('.key') or b'FAKE PRIVATE MATERIAL NEVER TRANSFER' in data for path,data in uploads)
        assert not tool.cleanup_warning


def test_remote_invalid_ca_and_failure_do_not_modify_trust(ssh_server,workspace):
    ca=workspace['tool'].settings['ca_file'];before=ca.read_bytes() if ca.exists() else None
    folders=set(Path('/tmp').glob('lc400-pc-*'))
    with client(ssh_server,workspace) as tool:
        with pytest.raises(RemoteDeploymentError,match='指纹'):
            tool.import_bundle(workspace['bundle'],['A'*64])
    assert (ca.read_bytes() if ca.exists() else None)==before
    assert folders==set(Path('/tmp').glob('lc400-pc-*'))


def test_pc_manifest_tamper_refused_before_upload(ssh_server,workspace,tmp_path):
    bad=tmp_path/'bad';shutil.copytree(workspace['bundle'],bad)
    (bad/'master-leaf.pem').write_bytes(b'changed')
    with client(ssh_server,workspace) as tool:
        uploads=[]
        tool._upload=lambda *args:uploads.append(args)
        with pytest.raises(ValueError,match='摘要'):
            tool.import_bundle(bad,[workspace['ca'].fingerprint()])
        assert not uploads


def test_remote_command_arguments_are_quoted(ssh_server,workspace):
    marker=ssh_server['base']/'injection-marker'
    python='/usr/bin/python3; touch '+str(marker)
    with client(ssh_server,workspace,remote_python=python) as tool:
        with pytest.raises(RemoteDeploymentError,match='执行失败'):
            tool.info()
    assert not marker.exists()


def test_remote_recovery_and_apply_privilege(ssh_server,workspace):
    local=workspace['tool']
    local.import_bundle(workspace['bundle'],[workspace['ca'].fingerprint()])
    paths=[local.settings['ca_file'],local.modbus/'master.crt',local.modbus/'slave.crt',
           local.https/'g3.crt',local.https/'.reload-required']
    recovery=local.modbus/'deployment-recovery';recovery.mkdir()
    entries=[]
    for index,path in enumerate(paths):
        exists=path.exists();entry=dict(path=str(path),existed=exists)
        if exists:
            (recovery/str(index)).write_bytes(path.read_bytes())
            entry.update(file=str(index),mode=path.stat().st_mode & 0o777)
        entries.append(entry)
    (recovery/'manifest.json').write_text(json.dumps(entries))
    original=(local.modbus/'master.crt').read_bytes()
    (local.modbus/'master.crt').write_bytes(b'interrupted')
    with client(ssh_server,workspace) as tool:
        assert tool.recover()['recovered']
        assert tool.check()['valid']
        if os.geteuid()!=0:
            with pytest.raises(RemoteDeploymentError,match='需要 root'):
                tool.apply('must-not-run.service',False)
    assert (local.modbus/'master.crt').read_bytes()==original


def test_authentication_failure_does_not_reveal_password(ssh_server,workspace):
    secret='Never-log-this-SSH-secret!'
    with pytest.raises(paramiko.AuthenticationException) as error:
        client(ssh_server,workspace,password=secret,identity_file=None).connect()
    assert secret not in str(error.value)


def test_rpc_disconnect_is_not_reported_as_not_executed(ssh_server,workspace,monkeypatch):
    with client(ssh_server,workspace) as tool:
        transport=tool.client.get_transport()
        class Disconnected:
            def settimeout(self,*args):pass
            def exec_command(self,*args):raise EOFError('connection lost')
            def close(self):pass
        monkeypatch.setattr(transport,'open_session',lambda **kwargs:Disconnected())
        with pytest.raises(RemoteDeploymentError,match='可能已执行'):
            tool._rpc('/tmp/lc400-pc-test','apply')
        class LostStatus(Disconnected):
            def exec_command(self,*args):pass
            def sendall(self,*args):pass
            def shutdown_write(self):pass
            def recv_ready(self):return False
            def recv_stderr_ready(self):return False
            def exit_status_ready(self):return True
            def recv_exit_status(self):return -1
        monkeypatch.setattr(transport,'open_session',lambda **kwargs:LostStatus())
        with pytest.raises(RemoteDeploymentError,match='可能已执行'):
            tool._rpc('/tmp/lc400-pc-test','apply')



def test_pc_executable_uses_ssh_after_relocation(ssh_server,workspace,tmp_path):
    source=os.environ.get('LC400_PC_TEST_EXECUTABLE')
    if not source:pytest.skip('set LC400_PC_TEST_EXECUTABLE for packaged SSH validation')
    moved=tmp_path/'PC SSH runtime relocated'
    shutil.copytree(Path(source).parent,moved)
    executable=moved/Path(source).name
    local=workspace['tool']
    args=[str(executable),'--host',ssh_server['host'],'--port',str(ssh_server['port']),
          '--user',ssh_server['user'],'--identity',str(ssh_server['identity']),
          '--host-fingerprint',ssh_server['pin'],'--app',str(local.app),'--config',str(local.config),
          '--modbus-dir',str(local.modbus),'--https-dir',str(local.https),'--helper',str(local.helper)]
    env=dict(os.environ,PATH='/usr/bin:/bin',PYTHONHOME='/nonexistent-python',
             PYTHONPATH='/nonexistent-packages',LD_LIBRARY_PATH='/nonexistent-libs')
    env.pop('VIRTUAL_ENV',None)
    def command(*extra):
        result=subprocess.run(args+list(extra),capture_output=True,text=True,env=env,timeout=90)
        assert result.returncode==0,result.stderr
        return json.loads(result.stdout)
    assert command('connect')['ready']
    out=tmp_path/'PC downloaded CSRs'
    assert command('generate','--device-id','LC400-test-001','--out',str(out))['downloaded']
    assert public_package(out,'lc400-csr')['device_id']=='LC400-test-001'
    assert command('import','--bundle',str(workspace['bundle']),
                   '--fingerprint',workspace['ca'].fingerprint())['imported']
    assert command('check')['valid']
    for line in (moved/'SHA256SUMS').read_text().splitlines():
        expected,name=line.split('  ',1)
        assert hashlib.sha256((moved/name).read_bytes()).hexdigest()==expected


def test_probe_and_connection_choose_same_recorded_key(ssh_server,workspace):
    known=ssh_server['base']/'probe-rsa-known-hosts'
    keys=paramiko.HostKeys()
    rsa=paramiko.RSAKey.from_private_key_file(str(ssh_server['rsa_key']))
    keys.add('[127.0.0.1]:'+str(ssh_server['port']),rsa.get_name(),rsa);keys.save(str(known))
    tool=client(ssh_server,workspace,host_fingerprint=None,known_hosts=known)
    result=tool.probe()
    assert result['key_type']=='ssh-rsa'
    assert result['ssh_fingerprint']==fingerprint(rsa)
    with client(ssh_server,workspace,host_fingerprint=result['ssh_fingerprint'],known_hosts=known) as connected:
        assert connected.info()['ready']
