"""Real X.509/CRL + C responder interoperability with an independent Python EMS.

No raw socket privileges, network devices, production keys or services required.
"""
import ctypes
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import struct
import subprocess
import sys

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'exec/app'))
from script.goose_pki import GoosePKI
from script.custom_pki import Conflict

REFERENCE = b'TEMPLATEPIGO/LLN0$GO$gocb1'
DEST = bytes.fromhex('010ccd010000')
ENC = serialization.Encoding.PEM


def identity(name, issuer=None, issuer_key=None, ca=False, expired=False):
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.now(timezone.utc)
    builder = (x509.CertificateBuilder().subject_name(subject)
        .issuer_name(issuer.subject if issuer else subject).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=2))
        .not_valid_after(now+timedelta(days=-1 if expired else 30))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), True)
        .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
            key_encipherment=False, data_encipherment=False, key_agreement=False,
            key_cert_sign=ca, crl_sign=ca, encipher_only=False, decipher_only=False), True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(
            (issuer_key or key).public_key()), False))
    return key, builder.sign(issuer_key or key, hashes.SHA256())


def crl(issuer, key, number=1, revoked=(), expired=False):
    now = datetime.now(timezone.utc)
    b = (x509.CertificateRevocationListBuilder().issuer_name(issuer.subject)
         .last_update(now-timedelta(days=2)).next_update(now+timedelta(days=-1 if expired else 7))
         .add_extension(x509.CRLNumber(number), False)
         .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), False))
    for serial in revoked:
        b = b.add_revoked_certificate(x509.RevokedCertificateBuilder().serial_number(serial)
            .revocation_date(now-timedelta(days=3)).build())
    return b.sign(key, hashes.SHA256()).public_bytes(ENC)


def key_bytes(key):
    return key.private_bytes(ENC, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def install(manager, files, runner=lambda service: None):
    batch = None
    for part, data in files.items():
        batch = manager.upload(part, data, batch_id=batch)['batch_id']
    return manager.apply(batch, runner)


@pytest.fixture
def material(tmp_path):
    root_key, root = identity('test-root', ca=True)
    key, cert = identity('subscriber', root, root_key)
    peer_key, peer_cert = identity('publisher', root, root_key)
    files = dict(key=key_bytes(key), identity=cert.public_bytes(ENC),
                 ca=root.public_bytes(ENC), crl=crl(root, root_key))
    manager = GoosePKI(tmp_path / 'goose-pki')
    return dict(manager=manager, files=files, root=root, root_key=root_key,
                key=key, cert=cert, peer_key=peer_key, peer_cert=peer_cert)


@pytest.fixture(scope='session')
def native(tmp_path_factory):
    directory = tmp_path_factory.mktemp('goose-c')
    output = directory / 'libgsec.so'
    source = ROOT / 'goose/goose_test/security'
    subprocess.run(['gcc', '-std=gnu99', '-Wall', '-Wextra', '-Werror', '-fPIC', '-shared',
                    str(source/'goose_security.c'), str(source/'goose_log.c'),
                    '-lcrypto', '-lpthread', '-o', str(output)], check=True)
    lib = ctypes.CDLL(str(output))
    lib.gsec_create.argtypes = [ctypes.c_char_p, ctypes.c_uint16, ctypes.c_void_p, ctypes.c_char_p]
    lib.gsec_create.restype = ctypes.c_void_p
    lib.gsec_destroy.argtypes = [ctypes.c_void_p]
    lib.gsec_hello.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32,
                             ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t)]
    lib.gsec_open_frame.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                   ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
    return lib


@pytest.fixture
def session(material, native, tmp_path, monkeypatch):
    monkeypatch.setenv('GOOSE_LOG_DIR', str(tmp_path/'logs'))
    install(material['manager'], material['files'])
    ctx = native.gsec_create(os.fsencode(material['manager'].home), 0x1000, DEST, REFERENCE)
    assert ctx
    yield ctx
    native.gsec_destroy(ctx)


def tlv(tag, value):
    return bytes([tag])+struct.pack('!H', len(value))+value


class EMS:
    def __init__(self, material):
        self.identity = material['peer_key']
        self.cert = material['peer_cert']
        self.eph = ec.generate_private_key(ec.SECP256R1())
        self.point = self.eph.public_key().public_bytes(serialization.Encoding.X962,
                                                       serialization.PublicFormat.UncompressedPoint)
        self.salt = os.urandom(32)
        transcript = b'GSEC1\x01\x00\x01'+self.point+self.salt
        signature = self.identity.sign(transcript, ec.ECDSA(hashes.SHA256()))
        self.hello = b''.join(tlv(t,v) for t,v in [(1,b'GSEC1'),(2,b'\x01'),(3,b'\x00\x01'),
            (4,self.point),(5,self.salt),(6,self.cert.public_bytes(serialization.Encoding.DER)),(7,signature)])
        self.key = None

    def handshake(self, lib, ctx, packet=None, expect=True):
        packet = self.hello if packet is None else packet
        ack = ctypes.create_string_buffer(1024)
        size = ctypes.c_size_t()
        rc = lib.gsec_hello(ctx, packet, len(packet), 0x0100007f, ack, ctypes.byref(size))
        if not expect:
            assert rc == -1 and size.value == 0
            return
        assert rc == 0
        answer = ack.raw[:size.value]
        fields = {}
        pos = 0
        while pos < len(answer):
            tag, length = struct.unpack('!BH', answer[pos:pos+3])
            fields[tag] = answer[pos+3:pos+3+length]
            pos += 3+length
        remote = x509.load_der_x509_certificate(fields[6])
        remote.public_key().verify(fields[7], b'GSEC1\x02\x00\x01'+fields[4]+fields[5]+
                                   self.point+self.salt, ec.ECDSA(hashes.SHA256()))
        shared = self.eph.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), fields[4]))
        self.key = HKDF(algorithm=hashes.SHA256(), length=16, salt=self.salt+fields[5],
                        info=b'GOOSE_SEC_P2S_V1').derive(shared)
        return answer

    def frame(self, st=1, sq=0, values=None, vlan=False, plaintext=False):
        values = b'\x85\x01\x2a' if values is None else values
        aad = b''.join(ber(t,v) for t,v in [(0x80,REFERENCE),(0x81,b'\x13\x88'),(0x82,b'dataset'),
            (0x83,b'goid'),(0x84,b'\0'*8),(0x85,positive(st)),(0x86,positive(sq)),(0x87,b'\0'),
            (0x88,b'\x01'),(0x89,b'\0'),(0x8a,b'\x01')]) + b'\xab'+ber_len(len(values))
        if plaintext:
            body = aad+values
        else:
            encrypted = AESGCM(self.key).encrypt(struct.pack('!QI',st,sq), values, aad)
            body = aad+encrypted[:-16]+ber(0x9c,b'\x01\x00\x01'+encrypted[-16:])
        pdu = ber(0x61,body)
        ethernet = DEST+bytes.fromhex('001122334455')+(b'\x81\x00\x00\x04' if vlan else b'')+b'\x88\xb8'
        return ethernet+struct.pack('!HHHH',0x1000,len(pdu)+8,0,0)+pdu


def positive(n):
    b = n.to_bytes(max(1,(n.bit_length()+7)//8),'big')
    return b'\0'+b if b[0]&128 else b


def ber_len(n):
    if n < 128:
        return bytes([n])
    b = n.to_bytes((n.bit_length()+7)//8,'big')
    return bytes([128+len(b)])+b


def ber(tag,value):
    return bytes([tag])+ber_len(len(value))+value


def receive(lib, ctx, frame, ok=True):
    output = ctypes.create_string_buffer(2048)
    first = ctypes.c_int()
    length = lib.gsec_open_frame(ctx, frame, len(frame), output, ctypes.byref(first))
    if ok:
        assert length > 0
        return output.raw[:length], first.value
    assert length == -1 and output.raw == bytes(2048)


def test_real_handshake_decryption_and_plaintext_rejection(material, native, session):
    ems = EMS(material)
    receive(native,session,ems.frame(plaintext=True),False)
    ems.handshake(native,session)
    for st,sq in [(1,0),(1,1),(2,0),(2,5)]:
        expected = ems.frame(st,sq,plaintext=True)
        output, first = receive(native,session,ems.frame(st,sq))
        assert output == expected
        assert first == (st==1 and sq==0)
    receive(native,session,ems.frame(2,5),False)
    receive(native,session,ems.frame(2,4),False)
    receive(native,session,ems.frame(1,100),False)
    receive(native,session,ems.frame(3,0,plaintext=True),False)


def test_tamper_does_not_pollute_replay_state(material,native,session):
    ems=EMS(material); ems.handshake(native,session)
    forged=bytearray(ems.frame(0x7fffffff,99)); forged[-1]^=1
    receive(native,session,bytes(forged),False)
    # Every protected field/region must authenticate; failed candidates stay private.
    original=ems.frame(1,0)
    for index in (30,50,len(original)-22,len(original)-10,len(original)-1):
        changed=bytearray(original); changed[index]^=1
        receive(native,session,bytes(changed),False)
    receive(native,session,original)
    malformed=ems.frame(2,0,values=b'\x85\x07\x01')
    receive(native,session,malformed,False)
    receive(native,session,ems.frame(2,0))


def test_duplicate_hello_keeps_ack_and_replay_state(material,native,session):
    ems=EMS(material); first=ems.handshake(native,session)
    receive(native,session,ems.frame())
    assert ems.handshake(native,session)==first
    receive(native,session,ems.frame(),False)
    receive(native,session,ems.frame(1,1))
    EMS(material).handshake(native,session,expect=False)


@pytest.mark.parametrize('size',[1,20,40,100,128,200,250,300])
def test_ber_length_transitions_and_vlan(material,native,session,size):
    ems=EMS(material); ems.handshake(native,session)
    values=ber(0x89,b'x'*size)
    frame=ems.frame(values=values,vlan=True)
    out,_=receive(native,session,frame)
    assert out==ems.frame(values=values,vlan=True,plaintext=True)


def test_malformed_hello_and_bad_signature(material,native,session):
    ems=EMS(material)
    for packet in (b'',ems.hello[:20],ems.hello+tlv(2,b'\x01'),ems.hello+tlv(9,b'x'),b'x'*1025):
        ems.handshake(native,session,packet,False)
    bad=bytearray(ems.hello); bad[-1]^=1
    ems.handshake(native,session,bytes(bad),False)
    ems.handshake(native,session)


@pytest.mark.parametrize('failure',['foreign','expired','revoked'])
def test_peer_certificate_rejected(material,native,tmp_path,monkeypatch,failure):
    monkeypatch.setenv('GOOSE_LOG_DIR',str(tmp_path/'logs'))
    if failure=='foreign':
        root_key,root=identity('foreign-root',ca=True)
        material['peer_key'],material['peer_cert']=identity('foreign',root,root_key)
    elif failure=='expired':
        material['peer_key'],material['peer_cert']=identity('expired',material['root'],material['root_key'],expired=True)
    else:
        material['files']['crl']=crl(material['root'],material['root_key'],revoked=[material['peer_cert'].serial_number])
    install(material['manager'],material['files'])
    ctx=native.gsec_create(os.fsencode(material['manager'].home),0x1000,DEST,REFERENCE)
    assert ctx
    try:
        EMS(material).handshake(native,ctx,expect=False)
    finally:
        native.gsec_destroy(ctx)


def test_missing_pki_is_fail_closed(native,tmp_path):
    assert not native.gsec_create(os.fsencode(tmp_path/'missing'),0x1000,DEST,REFERENCE)


def test_atomic_generation_retry_and_tls_isolation(material,tmp_path):
    manager=material['manager']
    sentinel=tmp_path/'tls.crt'; sentinel.write_bytes(b'unchanged TLS')
    calls=[]
    def fail(service):
        calls.append(service)
        raise OSError('service unavailable')
    state=install(manager,material['files'],fail)
    assert state['status']=='installed' and state['pending']==['goose']
    assert calls==['goose']
    generation=manager.active()
    assert manager.apply(state['batch_id'],calls.append)['status']=='applied'
    assert manager.active()==generation and calls==['goose','goose']
    assert sentinel.read_bytes()==b'unchanged TLS'
    assert manager.status()['installed']
    assert (generation/'enc.key').stat().st_mode & 0o777 == 0o600
    with pytest.raises(Conflict):
        manager.upload('key',material['files']['key'],batch_id=state['batch_id'])


@pytest.mark.parametrize('failure',['key','missing','expired_crl','revoked','foreign_crl'])
def test_bad_pki_never_publishes(material,failure):
    files=material['files'].copy()
    if failure=='key':
        files['key']=key_bytes(ec.generate_private_key(ec.SECP256R1()))
    elif failure=='missing':
        del files['crl']
    elif failure=='expired_crl':
        files['crl']=crl(material['root'],material['root_key'],expired=True)
    elif failure=='revoked':
        files['crl']=crl(material['root'],material['root_key'],revoked=[material['cert'].serial_number])
    else:
        key,cert=identity('foreign',ca=True); files['crl']=crl(cert,key)
    with pytest.raises((ValueError,FileNotFoundError)):
        install(material['manager'],files,lambda _: pytest.fail('must not restart'))
    assert material['manager'].active() is None


def test_partial_crl_update_and_rollback_protection(material):
    manager=material['manager']; install(manager,material['files'])
    first=manager.active()
    second=manager.upload('crl',crl(material['root'],material['root_key'],number=2))['batch_id']
    third=manager.upload('crl',crl(material['root'],material['root_key'],number=3))['batch_id']
    manager.apply(second,lambda _: None)
    with pytest.raises(Conflict):
        manager.apply(third,lambda _: pytest.fail('stale batch'))
    assert manager.active()!=first
    rollback=manager.upload('crl',material['files']['crl'])['batch_id']
    with pytest.raises(ValueError,match='rollback'):
        manager.apply(rollback,lambda _: pytest.fail('rollback'))


def test_intermediate_ca_chain(material,native,tmp_path,monkeypatch):
    monkeypatch.setenv('GOOSE_LOG_DIR',str(tmp_path/'logs'))
    ikey,intermediate=identity('intermediate',material['root'],material['root_key'],ca=True)
    material['key'],material['cert']=identity('subscriber',intermediate,ikey)
    material['peer_key'],material['peer_cert']=identity('publisher',intermediate,ikey)
    material['files'].update(key=key_bytes(material['key']),
        identity=material['cert'].public_bytes(ENC)+intermediate.public_bytes(ENC),
        crl=crl(material['root'],material['root_key'])+crl(intermediate,ikey))
    install(material['manager'],material['files'])
    ctx=native.gsec_create(os.fsencode(material['manager'].home),0x1000,DEST,REFERENCE)
    assert ctx
    try:
        ems=EMS(material); ems.handshake(native,ctx)
        receive(native,ctx,ems.frame())
    finally:
        native.gsec_destroy(ctx)


def test_authenticated_plaintext_enters_real_libiec61850(material,native,session):
    """Set GOOSE_TEST_LIBIEC to the native shared library to exercise its real decoder."""
    library=os.environ.get('GOOSE_TEST_LIBIEC')
    if not library:
        pytest.skip('set GOOSE_TEST_LIBIEC for real libiec61850 callback integration')
    iec=ctypes.CDLL(library)
    iec.GooseReceiver_create.restype=ctypes.c_void_p
    iec.GooseSubscriber_create.argtypes=[ctypes.c_char_p,ctypes.c_void_p]
    iec.GooseSubscriber_create.restype=ctypes.c_void_p
    for name in ('GooseReceiver_destroy','GooseSubscriber_destroy'):
        getattr(iec,name).argtypes=[ctypes.c_void_p]
    iec.GooseReceiver_addSubscriber.argtypes=[ctypes.c_void_p,ctypes.c_void_p]
    iec.GooseReceiver_handleMessage.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int]
    iec.GooseSubscriber_setDstMac.argtypes=[ctypes.c_void_p,ctypes.c_void_p]
    iec.GooseSubscriber_setAppId.argtypes=[ctypes.c_void_p,ctypes.c_uint16]
    iec.GooseSubscriber_getDataSetValues.argtypes=[ctypes.c_void_p]
    iec.GooseSubscriber_getDataSetValues.restype=ctypes.c_void_p
    iec.MmsValue_getElement.argtypes=[ctypes.c_void_p,ctypes.c_int]
    iec.MmsValue_getElement.restype=ctypes.c_void_p
    iec.MmsValue_toInt32.argtypes=[ctypes.c_void_p]
    iec.MmsValue_toInt32.restype=ctypes.c_int32
    iec.GooseSubscriber_isValid.argtypes=[ctypes.c_void_p]
    iec.GooseSubscriber_isValid.restype=ctypes.c_bool
    callback_type=ctypes.CFUNCTYPE(None,ctypes.c_void_p,ctypes.c_void_p)
    received=[]
    @callback_type
    def callback(subscriber,_):
        if iec.GooseSubscriber_isValid(subscriber):
            dataset=iec.GooseSubscriber_getDataSetValues(subscriber)
            received.append(iec.MmsValue_toInt32(iec.MmsValue_getElement(dataset,0)))
    iec.GooseSubscriber_setListener.argtypes=[ctypes.c_void_p,callback_type,ctypes.c_void_p]
    receiver=iec.GooseReceiver_create()
    subscriber=iec.GooseSubscriber_create(REFERENCE,None)
    iec.GooseSubscriber_setDstMac(subscriber,DEST)
    iec.GooseSubscriber_setAppId(subscriber,0x1000)
    iec.GooseSubscriber_setListener(subscriber,callback,None)
    iec.GooseReceiver_addSubscriber(receiver,subscriber)
    try:
        ems=EMS(material); ems.handshake(native,session)
        for frame in (ems.frame(),ems.frame(),ems.frame(2,0,plaintext=True),ems.frame(2,0,values=ber(0x85,b'\x2b'))):
            output=ctypes.create_string_buffer(2048); first=ctypes.c_int()
            size=native.gsec_open_frame(session,frame,len(frame),output,ctypes.byref(first))
            if size>0:
                iec.GooseReceiver_handleMessage(receiver,output,size)
        assert received==[42,43] # No duplicate or unauthenticated callback.
    finally:
        iec.GooseReceiver_destroy(receiver)


def test_process_restart_establishes_new_key_and_rejects_old_session(material,native,session):
    old=EMS(material); old.handshake(native,session)
    old_frame=old.frame()
    receive(native,session,old_frame)
    replacement=native.gsec_create(os.fsencode(material['manager'].home),0x1000,DEST,REFERENCE)
    assert replacement
    try:
        fresh=EMS(material); fresh.handshake(native,replacement)
        assert fresh.key!=old.key
        receive(native,replacement,old_frame,False)
        receive(native,replacement,fresh.frame())
    finally:
        native.gsec_destroy(replacement)


def test_runtime_rejects_publicly_readable_private_key(material,native,tmp_path,monkeypatch):
    monkeypatch.setenv('GOOSE_LOG_DIR',str(tmp_path/'logs'))
    install(material['manager'],material['files'])
    (material['manager'].active()/'enc.key').chmod(0o644)
    assert not native.gsec_create(os.fsencode(material['manager'].home),0x1000,DEST,REFERENCE)


def test_log_format_and_no_private_key_disclosure(material,native,session,tmp_path):
    ems=EMS(material); ems.handshake(native,session)
    receive(native,session,ems.frame())
    logs=list((tmp_path/'logs').glob('*.log'))
    assert len(logs)==1
    text=logs[0].read_text()
    import re
    assert re.search(r'\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{6}\] \[goose_security.c:\d+\] \[\w+\] \[INFO\]',text)
    assert 'PRIVATE KEY' not in text and ems.key.hex() not in text


def test_rejection_log_correlates_untrusted_counters(material,native,session,tmp_path):
    ems=EMS(material); ems.handshake(native,session)
    packet=ems.frame(st=7,sq=2)
    receive(native,session,packet[:-1]+bytes([packet[-1]^1]),False)
    receive(native,session,packet)
    receive(native,session,packet,False)
    text=next((tmp_path/'logs').glob('*.log')).read_text()
    assert 'blocked before decoder/Modbus: reason=GCM tag mismatch' in text
    assert 'untrusted_stNum=7 untrusted_sqNum=2' in text
    assert 'last_accepted_stNum=7 last_accepted_sqNum=2' in text
    assert 'reason=replayed/out-of-order frame' in text
    assert ems.key.hex() not in text


def test_packet_trace_is_opt_in_and_bounded(native,tmp_path,monkeypatch):
    monkeypatch.setenv('GOOSE_LOG_DIR',str(tmp_path))
    native.goose_log_packet.argtypes=[ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_char_p,
                                     ctypes.c_void_p,ctypes.c_size_t]
    wire=bytes(range(100))
    monkeypatch.delenv('GOOSE_PACKET_TRACE',raising=False)
    native.goose_log_packet(b'test.c',1,b'test',b'wire-test',wire,len(wire))
    assert not list(tmp_path.glob('*.log'))
    monkeypatch.setenv('GOOSE_PACKET_TRACE','1')
    native.goose_log_packet(b'test.c',1,b'test',b'wire-test',wire,len(wire))
    text=next(tmp_path.glob('*.log')).read_text()
    assert 'bytes=100 shown=64' in text
    assert '3e 3f ...' in text and '3f 40' not in text


def test_async_log_worker_flushes_on_stop(native,tmp_path,monkeypatch):
    monkeypatch.setenv('GOOSE_LOG_DIR',str(tmp_path/'async-logs'))
    native.goose_log_start_async.restype=ctypes.c_int
    assert native.goose_log_start_async() == 0
    try:
        native.goose_log_packet.argtypes=[ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,
                                         ctypes.c_char_p,ctypes.c_void_p,ctypes.c_size_t]
        monkeypatch.setenv('GOOSE_PACKET_TRACE','1')
        for i in range(20):
            data=bytes([i])
            native.goose_log_packet(b'test.c',1,b'test',b'async-wire',data,len(data))
    finally:
        native.goose_log_stop_async()
    text=next((tmp_path/'async-logs').glob('*.log')).read_text()
    assert text.count('async-wire') == 20
