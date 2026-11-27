"""Optional real Tk checks; no network traffic is emitted."""
from pathlib import Path
import time
import tkinter as tk

import pytest

pytest.importorskip('OpenSSL')
from tools.goose_publisher import gui, runner
from tools.goose_publisher.test_protocol import material, key_bytes, crl, ENC


def pump(root, app):
    deadline = time.monotonic()+5
    while app.busy and time.monotonic() < deadline:
        root.update()
        time.sleep(.01)
    root.update()
    assert not app.busy


def test_tk_directory_pki_and_background_run(material,tmp_path,monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip('no accessible display')
    root.withdraw()
    errors = []
    adapter = runner.Adapter('Ethernet','Test NIC','NPF-test','192.168.2.254','00:11:22:33:44:55',201)
    monkeypatch.setattr(runner,'adapters',lambda **kwargs:[adapter])
    monkeypatch.setattr(gui.messagebox,'showerror',lambda title,message:errors.append(message))
    monkeypatch.setattr(gui.messagebox,'askyesno',lambda *args:True)
    monkeypatch.setattr(gui.filedialog,'askdirectory',lambda **kwargs:str(tmp_path))
    files = {'enc.crt':material['peer_cert'].public_bytes(ENC),'enc.key':key_bytes(material['peer_key']),
             'ca-roots.crt':material['root'].public_bytes(ENC),'crls.pem':crl(material['root'],material['root_key'])}
    for name,data in files.items():
        (tmp_path/name).write_bytes(data)
    app = gui.Application(root)
    try:
        app.refresh_adapters(); pump(root,app)
        assert app.adapter_box.current() == 0
        assert 'Test NIC' in app.adapter_box.get()
        app.choose_directory()
        assert Path(app.fields['key'].get()).name == 'enc.key'
        app.verify_pki(); pump(root,app)
        assert not errors
        assert 'CRL 校验通过' in app.output.get('1.0','end')
        calls = []
        def run(data, selected, stop, log):
            calls.append((data,selected))
            log('test: ACK verified')
            return 'finished'
        monkeypatch.setattr(runner,'run',run)
        app.start(); pump(root,app)
        assert len(calls) == 1 and calls[0][1] == adapter
        assert calls[0][0]['mode'] == 'normal'
        app.use_custom.set(True)
        app.fields['appid'].set('0x1234')
        app.fields['destination'].set('01:0c:cd:01:00:09')
        app.fields['reference'].set('custom/LLN0$GO$test')
        config_path=tmp_path/'packets.json'
        monkeypatch.setattr(gui.filedialog,'asksaveasfilename',lambda **kwargs:str(config_path))
        app.export_config()
        assert 'enc.key' not in config_path.read_text()
        app.fields['appid'].set('0x1000')
        app.use_custom.set(False)
        monkeypatch.setattr(gui.filedialog,'askopenfilename',lambda **kwargs:str(config_path))
        app.import_config()
        assert app.fields['appid'].get() == '0x1234'
        assert app.fields['destination'].get() == '01:0c:cd:01:00:09'
        assert app.fields['reference'].get() == 'custom/LLN0$GO$test'
        assert app.use_custom.get()
        assert len(runner.frame_plan(app.data())) == 2
        assert app.status.get() == '发送完成'
        assert str(app.start_button.cget('state')) == 'normal'
        assert str(app.stop_button.cget('state')) == 'disabled'
        assert not errors
    finally:
        for timer in root.tk.call('after','info'):
            root.after_cancel(timer)
        root.destroy()
