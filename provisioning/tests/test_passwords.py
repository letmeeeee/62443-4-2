"""Password generation, authenticated storage, CA binding, GUI redaction and CLI tests."""
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

from provisioning.ca import CertificateAuthority
from provisioning.passwords import generate_password, load_for_ca, load_password, save_password

PROTECTION = 'Only-For-Tests-Vault-Protection-2026!'
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope='module')
def vault(tmp_path_factory):
    base = tmp_path_factory.mktemp('ca-password')
    ca_password = generate_password()
    path = base/'password.lcvault'
    ca = CertificateAuthority(base/'ca')
    save_password(path, ca_password, PROTECTION, ca.directory)
    return dict(path=path, ca=ca, password=ca_password, base=base)


def test_random_generation():
    values={generate_password() for _ in range(100)}
    assert len(values)==100
    assert all(len(p)==43 for p in values)


def test_encrypted_roundtrip_and_private_permissions(vault):
    path=vault['path']; password=vault['password']
    data=path.read_bytes()
    assert password.encode() not in data and PROTECTION.encode() not in data
    assert load_password(path, PROTECTION)['password']==password
    assert load_for_ca(path, PROTECTION, vault['ca'])==password
    if os.name=='posix': assert path.stat().st_mode & 0o777 == 0o600


def test_wrong_protection_and_tamper(vault, tmp_path):
    with pytest.raises(ValueError, match='错误或'):
        load_password(vault['path'], 'Wrong-Protection-Password!')
    data=bytearray(vault['path'].read_bytes());data[-1]^=1
    path=tmp_path/'damaged.lcvault';path.write_bytes(data)
    with pytest.raises(ValueError, match='错误或'): load_password(path, PROTECTION)


@pytest.mark.parametrize('content', [b'',b'LC4VLT01',b'not a vault',b'X'*16385])
def test_invalid_file_bounds(tmp_path, content):
    path=tmp_path/'invalid';path.write_bytes(content)
    with pytest.raises(ValueError, match='格式错误'): load_password(path, PROTECTION)


def test_password_policy_no_clobber_or_ca_data_write(vault, tmp_path):
    original=vault['path'].read_bytes()
    with pytest.raises(ValueError, match='已存在'):
        save_password(vault['path'], generate_password(), PROTECTION, vault['ca'].directory)
    assert vault['path'].read_bytes()==original
    for password, protection in [('short',PROTECTION),(generate_password(),'short'),(PROTECTION,PROTECTION)]:
        with pytest.raises(ValueError): save_password(tmp_path/'blocked',password,protection,vault['ca'].directory)
    with pytest.raises(ValueError,match='之外'):
        save_password(vault['ca'].directory/'password.lcvault',vault['password'],PROTECTION,vault['ca'].directory)
    assert not (tmp_path/'blocked').exists()


def test_symlink_refused(vault, tmp_path):
    if os.name!='posix': pytest.skip('POSIX symbolic link case')
    path=tmp_path/'linked';path.symlink_to(vault['path'])
    with pytest.raises(ValueError): load_password(path,PROTECTION)
    with pytest.raises(ValueError): save_password(path,generate_password(),PROTECTION,vault['ca'].directory)


def test_ca_binding_and_existing_key_validation(vault, tmp_path):
    ca=vault['ca']
    with pytest.raises(ValueError,match='另一 CA'):
        load_for_ca(vault['path'],PROTECTION,CertificateAuthority(tmp_path/'other'))
    CertificateAuthority.initialize(ca.directory,vault['password'],'Vault Test')
    assert load_for_ca(vault['path'],PROTECTION,ca)==vault['password']
    # A restored CA can move: its real encrypted private key proves the password is correct.
    moved=tmp_path/'restored-ca';shutil.copytree(ca.directory,moved)
    assert load_for_ca(vault['path'],PROTECTION,CertificateAuthority(moved))==vault['password']
    wrong=tmp_path/'wrong.lcvault'
    save_password(wrong,generate_password(),PROTECTION,ca.directory)
    with pytest.raises(ValueError): load_for_ca(wrong,PROTECTION,ca)


def test_window_consumes_secret_before_output():
    from provisioning.ui import Window
    window=Window.__new__(Window)
    rendered=[]
    window.queue=queue.Queue();window.queue.put((True,'DO-NOT-LOG-THIS-SECRET'))
    window.busy=True;window.on_success=lambda secret:'Secret loaded' if secret else ''
    window.root=SimpleNamespace(after=lambda *_:None)
    window.output=SimpleNamespace(insert=lambda _,text:rendered.append(text),see=lambda _:None)
    window.poll()
    assert 'DO-NOT-LOG-THIS-SECRET' not in ''.join(rendered)
    assert 'Secret loaded' in ''.join(rendered)


def test_gui_load_and_clear_without_logging(vault, monkeypatch):
    from provisioning.password_ui import PasswordPanel
    import provisioning.password_ui as ui
    panel=PasswordPanel.__new__(PasswordPanel)
    panel.secret=panel.directory=None
    status=[];outputs=[]
    panel.status=SimpleNamespace(set=status.append)
    def task(work,on_success): outputs.append(on_success(work()))
    panel.window=SimpleNamespace(busy=False,values=lambda:{'ca':str(vault['ca'].directory)},task=task)
    panel.protection=lambda:PROTECTION
    monkeypatch.setattr(ui.filedialog,'askopenfilename',lambda **_:str(vault['path']))
    panel.action('load')
    assert panel.get()==vault['password']
    assert vault['password'] not in ''.join(outputs+status)
    panel.clear()
    assert panel.secret is None and panel.directory is None


def test_cli_generate_and_initialize_from_saved_password(tmp_path):
    ca=tmp_path/'new-ca';path=tmp_path/'new-ca-password.lcvault'
    args=[sys.executable,str(ROOT/'ca_manager.py'),'--ca-dir',str(ca)]
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
    def command(extra, inputs):
        result=subprocess.run(args+extra,input=inputs,capture_output=True,text=True,env=env,timeout=60)
        assert result.returncode==0,result.stderr
        assert PROTECTION not in result.stdout+result.stderr
        return result
    generated=command(['password-generate','--out',str(path)],PROTECTION+'\n'+PROTECTION+'\n')
    assert json.loads(generated.stdout)['encrypted']
    secret=load_password(path,PROTECTION)['password']
    assert secret not in generated.stdout+generated.stderr
    initialized=command(['--vault-file',str(path),'init','--name','CLI Vault CA'],PROTECTION+'\n')
    assert 'root_fingerprint' in json.loads(initialized.stdout)
    assert secret not in initialized.stdout+initialized.stderr
    checked=command(['--vault-file',str(path),'password-check'],PROTECTION+'\n')
    assert json.loads(checked.stdout)==dict(loaded=True,ca_verified=True)
    assert secret not in checked.stdout+checked.stderr
