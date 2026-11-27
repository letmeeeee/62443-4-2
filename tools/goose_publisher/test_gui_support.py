"""GUI runner checks with real crypto/C receiver and mocked Windows I/O."""
import ctypes
import io
import json
from pathlib import Path
import socket
import struct
import sys
import threading
from types import SimpleNamespace
import zipfile

import pytest

pytest.importorskip('OpenSSL')
from tools.goose_publisher import runner, prepare_windows
from tools.goose_publisher.trust import verify_certificate
from tools.goose_publisher.test_protocol import material, native, session, publisher, handshake, receive, identity, crl, ENC


def test_inprocess_verifier_interoperates_with_c(material,native,session,tmp_path):
    pub = publisher(material,tmp_path,verifier=verify_certificate)
    pub.accept_ack(handshake(pub,native,session))
    receive(native,session,pub.frame(bytes(6),[0]*8))


@pytest.mark.parametrize('failure',['revoked','expired_crl','wrong_root','missing_crl'])
def test_inprocess_verifier_rejects_invalid_peer(material,native,session,tmp_path,failure):
    pub = publisher(material,tmp_path,verifier=verify_certificate)
    ack = handshake(pub,native,session)
    if failure == 'revoked':
        pub.crl.write_bytes(crl(material['root'],material['root_key'],2,revoked=[material['cert'].serial_number]))
    elif failure == 'expired_crl':
        pub.crl.write_bytes(crl(material['root'],material['root_key'],expired=True))
    elif failure == 'wrong_root':
        key,root = identity('foreign',ca=True)
        pub.ca.write_bytes(root.public_bytes(ENC))
        pub.crl.write_bytes(crl(root,key))
    else:
        pub.crl.write_bytes(b'')
    with pytest.raises(ValueError):
        pub.accept_ack(ack)
    assert pub.key is None


def test_windows_bind_uses_selected_address_and_network_order_index(monkeypatch):
    monkeypatch.setattr(runner.sys,'platform','win32')
    calls = []
    sock = SimpleNamespace(bind=lambda address:calls.append(address),setsockopt=lambda *args:calls.append(args))
    adapter = runner.Adapter('Ethernet','Intel','NPF-guid','192.168.2.254','00:11:22:33:44:55',201)
    runner.bind_udp(sock,adapter)
    assert calls == [('192.168.2.254',0),(socket.IPPROTO_IP,31,struct.pack('!I',201))]


def test_adapter_selection_does_not_filter_stale_up_flags():
    interface = SimpleNamespace(name='Ethernet',description='Intel NIC',network_name='NPF-guid',
                                ips={4:['192.168.2.254']},ip='192.168.2.254',mac='00-11-22-33-44-55',index=201,flags=0)
    logs=[]
    selected=runner.collect_adapters([interface],logs.append)
    assert len(selected)==1 and selected[0].address=='192.168.2.254'
    assert selected[0].network_name=='NPF-guid' and selected[0].index==201
    assert 'flags=0' in logs[0]


def test_adapter_primary_ipv4_fallback_and_exclusion_reasons():
    def adapter(**kwargs):
        data=dict(name='Ethernet',description='NIC',network_name='NPF-guid',ips={},ip='192.168.2.254',
                  mac='00:11:22:33:44:55',index=3,flags=0)
        data.update(kwargs)
        return SimpleNamespace(**data)
    logs=[]
    interfaces=[adapter(),adapter(mac='00:00:00:00:00:00'),adapter(ip=None),adapter(ip='not-ip')]
    selected=runner.collect_adapters(interfaces,logs.append)
    assert len(selected)==1
    assert any('MAC' in item and '排除' in item for item in logs)
    assert any('没有 IPv4' in item for item in logs)
    assert any('不是有效 IPv4' in item for item in logs)


@pytest.mark.parametrize('mode',['normal','replay','tamper','tamper-recover','plaintext','bad-signature'])
@pytest.mark.parametrize('custom',[False,True])
def test_runner_modes_real_c_peer_and_mocked_driver(material,native,session,tmp_path,monkeypatch,mode,custom):
    pub = publisher(material,tmp_path,verifier=verify_certificate)
    monkeypatch.setattr(runner,'bind_udp',lambda sock,adapter:None)
    sent,accepted,logs = [],[],[]
    class UDP:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def settimeout(self,value): pass
        def connect(self,address): assert address == ('192.168.2.136',30001)
        def send(self,data):
            output = ctypes.create_string_buffer(1024); size = ctypes.c_size_t()
            self.rc = native.gsec_hello(session,data,len(data),0x0100007f,output,ctypes.byref(size))
            self.answer = output.raw[:size.value]
        def recv(self,size):
            if self.rc:
                raise socket.timeout()
            return self.answer
    class Ethernet:
        closed = False
        def send(self,data):
            sent.append(data)
            output = ctypes.create_string_buffer(2048); first = ctypes.c_int()
            accepted.append(native.gsec_open_frame(session,data,len(data),output,ctypes.byref(first)) > 0)
        def close(self): self.closed = True
    class Stop(threading.Event):
        def wait(self,timeout=None): return self.is_set()
    ethernet = Ethernet()
    data = dict(target='192.168.2.136',count='2',interval='1',values='0,0,0,0,0,0,0,0',mode=mode,
                cert='',key='',ca='',crl='',change_state=False)
    if custom:
        data['custom_frames']=json.dumps([dict(stNum=7,sqNum=10,values=list(range(8))),
                                         dict(stNum=8,sqNum=0,values=list(range(8,16)))])
    adapter = runner.Adapter('Ethernet','Intel','NPF-guid','192.168.2.254','00:11:22:33:44:55',20)
    result = runner.run(data,adapter,Stop(),logs.append,publisher_factory=lambda *args:pub,
                        udp_factory=UDP,ethernet_factory=lambda adapter:ethernet)
    assert ethernet.closed
    if mode == 'bad-signature':
        assert result == 'negative-unconfirmed' and not sent
    else:
        assert result == 'finished'
        assert accepted == {'normal':[True,True], 'replay':[True,False,True,False],
                            'tamper':[False,False], 'tamper-recover':[False,True,False,True], 'plaintext':[False,False]}[mode]


def test_custom_plan_and_counter_overflow():
    data=dict(count=2,st_start=3,sq_start=10,values='1,2,3,4,5,6,7,8')
    assert [row[:2] for row in runner.frame_plan(data)] == [(3,10),(3,11)]
    assert [row[:2] for row in runner.frame_plan(dict(data,change_state=True))] == [(3,10),(4,0)]
    with pytest.raises(ValueError):
        runner.frame_plan(dict(data,sq_start=0xffffffff))
    for rows in ([dict(stNum=1,sqNum=0,values=[0]*8)]*2,
                 [dict(stNum=1,sqNum=0,values=[0]*7)],
                 [dict(stNum=True,sqNum=0,values=[0]*8)]):
        with pytest.raises(ValueError):
            runner.frame_plan(dict(data,custom_frames=json.dumps(rows)))


def test_custom_wire_headers(material,native,session,tmp_path):
    pub=publisher(material,tmp_path,verifier=verify_certificate)
    pub.accept_ack(handshake(pub,native,session))
    options=runner.frame_options(dict(appid='0x1234',reference='custom/LLN0$GO$test',destination='01:0c:cd:01:00:09'))
    packet=pub.frame(bytes(6),[0]*8,**options)
    assert packet[:6] == bytes.fromhex('010ccd010009')
    assert packet[14:16] == b'\x12\x34'
    assert b'custom/LLN0$GO$test' in packet
    # The fixed subscriber must reject an unconfigured destination/APPID/reference.
    output=ctypes.create_string_buffer(2048); first=ctypes.c_int()
    assert native.gsec_open_frame(session,packet,len(packet),output,ctypes.byref(first)) < 0
    for data in (dict(appid='65536'),dict(destination='00:11:22:33:44:55'),dict(reference='')):
        with pytest.raises(ValueError):
            runner.frame_options(data)


def test_stop_before_handshake_does_not_open_sockets():
    stop = threading.Event(); stop.set()
    data = dict(target='192.168.2.136',count=1,interval=1,values='0,0,0,0,0,0,0,0',mode='normal')
    adapter = runner.Adapter('Ethernet','Intel','NPF-guid','192.168.2.254','00:11:22:33:44:55',20)
    assert runner.run(data,adapter,stop,lambda message:None) == 'stopped'


def test_buildkit_contains_only_allowlisted_sources(tmp_path,monkeypatch):
    package = Path(prepare_windows.__file__).resolve().parent
    source = tmp_path/'tools/goose_publisher'; source.mkdir(parents=True)
    for name in prepare_windows.FILES:
        (source/name).write_bytes((package/name).read_bytes())
    (source/'enc.key').write_text('must not ship')
    (source/'private.log').write_text('must not ship')
    monkeypatch.setattr(prepare_windows,'__file__',str(source/'prepare_windows.py'))
    target = prepare_windows.main()
    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()
        assert len(names) == len(prepare_windows.FILES)+2
        assert not any(name.endswith(('.key','.log','.crt','.pem')) for name in names)
        assert b'\r\n' in archive.read('tools/goose_publisher/build_installer.bat')


def test_config_roundtrip_without_display(tmp_path,monkeypatch):
    from tools.goose_publisher import gui
    class Value:
        def __init__(self,value): self.value=value
        def get(self,*args): return self.value
        def set(self,value): self.value=value
        def delete(self,*args): self.value=''
        def insert(self,index,value): self.value=value
    app=gui.Application.__new__(gui.Application)
    app.fields={k:Value(v) for k,v in dict(count='2',interval='1',values='0,0,0,0,0,0,0,0',
        st_start='1',sq_start='0',appid='0x1234',reference='custom/LLN0$GO$test',
        destination='01:0c:cd:01:00:09',key='secret-key-path').items()}
    app.mode=Value(next(iter(gui.MODES)))
    app.change_state=Value(False)
    app.use_custom=Value(True)
    app.frame_editor=Value(json.dumps([dict(stNum=7,sqNum=10,values=list(range(8)))]))
    logs=[]; errors=[]
    app.log=logs.append
    monkeypatch.setattr(gui.messagebox,'showerror',lambda *args:errors.append(args))
    path=tmp_path/'config.json'
    monkeypatch.setattr(gui.filedialog,'asksaveasfilename',lambda **kwargs:str(path))
    monkeypatch.setattr(gui.filedialog,'askopenfilename',lambda **kwargs:str(path))
    app.export_config()
    assert 'secret-key-path' not in path.read_text()
    original=app.packet_config()
    app.fields['appid'].set('0x1000'); app.use_custom.set(False)
    app.import_config()
    assert app.packet_config() == original
    path.write_text('{"format":"unsupported"}')
    app.import_config()
    assert errors and app.packet_config() == original
