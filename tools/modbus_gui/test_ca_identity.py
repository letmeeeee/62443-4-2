"""Enterprise CA single-role issuance and real debug-tool mTLS round trips."""
import json
from pathlib import Path
import shutil
import pytest
from provisioning.ca import CertificateAuthority
from provisioning.common import public_package
from .ca_identity import generate, import_bundle
from .core import Server, exchange, tls_context

PASSWORD='Offline-Test-Password-2026!'


@pytest.fixture(scope='module')
def identities(tmp_path_factory):
    base=tmp_path_factory.mktemp('pc-ca')
    ca=CertificateAuthority.initialize(base/'ca',PASSWORD,'PC Test')
    data={}
    for role in ('master','slave'):
        folder=generate(base,role,'PC-debug','127.0.0.1')
        request=folder/'request'
        review=ca.inspect_request(request)
        assert [i['role'] for i in review['identities']]==[role]
        bundle=base/(role+'-bundle')
        ca.issue_package(request,bundle,PASSWORD,expected_review=review)
        public_package(bundle,'lc400-role-certificates')
        data[role]=dict(folder=folder,bundle=bundle)
    return dict(ca=ca,data=data,base=base)


def test_single_role_ca_ledger_and_private_key_isolation(identities):
    w=identities
    records=w['ca'].records()
    assert len(records)==2
    assert {r['role'] for r in records}=={'master','slave'}
    for role,v in w['data'].items():
        assert set(p.name for p in (v['folder']/'request').iterdir())=={'manifest.json',role+'.csr'}
        assert not list(v['bundle'].glob('*.key'))
        assert (v['folder']/(role+'.key')).stat().st_mode & 0o777 == 0o600


def test_debug_tool_mutual_ca_tls(identities):
    w=identities;loaded={}
    for role,v in w['data'].items():
        loaded[role]=import_bundle(v['folder'],v['bundle'],[w['ca'].fingerprint()])
    def ctx(role):
        v=loaded[role]
        return tls_context(role=='slave',v['cert'],v['key'],v['ca'])
    server=Server(ctx('slave'),'127.0.0.1',0)
    server.start()
    try:
        assert exchange(ctx('master'),'127.0.0.1',server.port,1,6,0,values=[321])==[321]
        assert exchange(ctx('master'),'127.0.0.1',server.port,1,3,0)==[321]
    finally:server.stop()


@pytest.mark.parametrize('fault',['pin','role','csr','key','tamper'])
def test_reject_incorrect_delivery(identities,tmp_path,fault):
    w=identities;v=w['data']['master']
    folder=tmp_path/'identity';shutil.copytree(v['folder'],folder)
    bundle=tmp_path/'bundle';shutil.copytree(v['bundle'],bundle)
    pins=[w['ca'].fingerprint()]
    if fault=='pin':pins=['0'*64]
    if fault=='role':shutil.copyfile(w['data']['slave']['bundle']/'manifest.json',bundle/'manifest.json')
    if fault=='csr':(folder/'request/master.csr').write_bytes(b'bad')
    if fault=='key':shutil.copyfile(w['data']['slave']['folder']/'slave.key',folder/'master.key')
    if fault=='tamper':(bundle/'master-leaf.pem').write_bytes(b'bad')
    with pytest.raises(ValueError):import_bundle(folder,bundle,pins)


def test_single_role_cross_identity_reuse_refused(identities,tmp_path):
    w=identities;request=tmp_path/'request'
    shutil.copytree(w['data']['master']['folder']/'request',request)
    manifest=json.loads((request/'manifest.json').read_text());manifest['device_id']='Other-PC'
    (request/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='复用'):
        w['ca'].issue_package(request,tmp_path/'bad',PASSWORD)


def test_gui_csr_and_ca_import_callbacks(tmp_path):
    import os
    if not os.environ.get('DISPLAY'):pytest.skip('GUI requires DISPLAY')
    import tkinter as tk
    import time
    from unittest.mock import patch
    from .gui import Window
    root=tk.Tk();root.withdraw();window=Window(root);errors=[]
    def wait(predicate):
        deadline=time.monotonic()+30
        while not predicate():
            root.update()
            if errors:raise AssertionError(errors)
            if time.monotonic()>deadline:raise AssertionError('GUI callback timed out')
            time.sleep(.01)
        root.update()
    try:
        with patch(Window.__module__+'.filedialog.askdirectory',return_value=str(tmp_path)), \
                patch(Window.__module__+'.messagebox.showinfo'), \
                patch(Window.__module__+'.messagebox.showerror',side_effect=lambda *v:errors.append(v)), \
                patch(Window.__module__+'.messagebox.askyesno',return_value=True):
            window.generate_pc_csr()
            wait(lambda:bool(window.pc_folder.get()))
            folder=Path(window.pc_folder.get())
            ca=CertificateAuthority.initialize(tmp_path/'ca',PASSWORD,'GUI Test')
            ca.issue_package(folder/'request',tmp_path/'bundle',PASSWORD)
            with patch(Window.__module__+'.filedialog.askdirectory',return_value=str(tmp_path/'bundle')):
                window.import_pc_identity()
                wait(lambda:bool(window.fields['client']['cert'].get()))
            assert window.fields['client']['key'].get()==str(folder/'master.key')
            assert window.fields['client']['verify_peer'].get()
            assert window.fields['client']['mutual'].get()
            assert window.pc_roots.get()==ca.fingerprint()
    finally:root.destroy()


def test_packaged_ca_single_role_signing(tmp_path):
    import os
    import subprocess
    executable=os.environ.get('LC400_CA_TEST_EXECUTABLE')
    if not executable:pytest.skip('set LC400_CA_TEST_EXECUTABLE for packaged CA')
    executable=str(Path(executable).resolve());ca_dir=tmp_path/'ca'
    def run(*args,input=None):
        result=subprocess.run([executable,'--ca-dir',str(ca_dir),*map(str,args)],input=input,text=True,capture_output=True,timeout=60)
        assert result.returncode==0,result.stderr
        return json.loads(result.stdout)
    run('init','--name','Packaged PC Test',input=PASSWORD+'\n'+PASSWORD+'\n')
    folder=generate(tmp_path,'master','Packaged-PC')
    assert run('inspect',folder/'request')['identities'][0]['role']=='master'
    result=run('sign',folder/'request',tmp_path/'bundle',input=PASSWORD+'\n')
    assert result['kind']=='lc400-role-certificates'
    assert import_bundle(folder,tmp_path/'bundle',result['root_fingerprints'])['role']=='master'


def test_packaged_debug_import_uses_bundled_module(identities,tmp_path):
    import os
    import subprocess
    executable=os.environ.get('LC400_MODBUS_TEST_EXECUTABLE')
    if not executable:pytest.skip('set LC400_MODBUS_TEST_EXECUTABLE for packaged debug runtime')
    base=Path(executable).resolve().parent
    folder=tmp_path/'pc';shutil.copytree(identities['data']['slave']['folder'],folder)
    # Source test may already have installed a version; remove public installs only in this temporary copy.
    for installed in folder.glob('issued-*'):shutil.rmtree(installed)
    environment=dict(os.environ,PYTHONHOME=str(base/'runtime'),
        PYTHONPATH=str(base/'app')+os.pathsep+str(base/'runtime/lib/python3.8/site-packages'),
        LD_LIBRARY_PATH=str(base/'runtime/lib'),PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1')
    script='import json,sys;from tools.modbus_gui.ca_identity import import_bundle;print(json.dumps(import_bundle(sys.argv[1],sys.argv[2],[sys.argv[3]])))'
    result=subprocess.run([str(base/'runtime/bin/python3'),'-c',script,str(folder),
        str(identities['data']['slave']['bundle']),identities['ca'].fingerprint()],
        env=environment,cwd=tmp_path,text=True,capture_output=True,timeout=30)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['role']=='slave'
