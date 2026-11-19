"""Publisher interoperability against the real C subscriber security layer."""
import ctypes
import os
from pathlib import Path
import sys

import pytest
from cryptography.exceptions import InvalidSignature

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'goose/goose_test/tests'))
from test_goose_security import material, native, session, identity, crl, key_bytes, ENC, receive
from tools.goose_publisher.protocol import Publisher, signed, parse_ack


def publisher(material, tmp_path, verifier=None, **overrides):
    files = {'cert':material['peer_cert'].public_bytes(ENC), 'key':key_bytes(material['peer_key']),
             'ca':material['root'].public_bytes(ENC), 'crl':crl(material['root'],material['root_key'])}
    files.update(overrides)
    paths = {}
    for name,data in files.items():
        path = tmp_path/name
        path.write_bytes(data)
        paths[name] = path
    return Publisher(**paths,verifier=verifier)


def handshake(pub, lib, ctx):
    output = ctypes.create_string_buffer(1024)
    size = ctypes.c_size_t()
    assert lib.gsec_hello(ctx,pub.hello,len(pub.hello),0x0100007f,output,ctypes.byref(size)) == 0
    return output.raw[:size.value]


def test_publisher_c_handshake_dataset_and_replay(material,native,session,tmp_path):
    pub = publisher(material,tmp_path)
    ack = handshake(pub,native,session)
    pub.accept_ack(ack)
    values = [0,1,-1,127,128,-128,32767,-32768]
    packet = pub.frame(bytes.fromhex('001122334455'),values)
    plain,first = receive(native,session,packet)
    assert first == 1 and plain != packet
    assert b'\x9c\x13' not in plain[-21:]
    receive(native,session,packet,False)
    with pytest.raises(ValueError,match='nonce'):
        pub.frame(bytes(6),values)
    with pytest.raises(ValueError,match='建立会话'):
        pub.accept_ack(ack)
    packet = pub.frame(bytes(6),values,st=1,sq=1)
    corrupted = packet[:-1]+bytes([packet[-1]^1])
    receive(native,session,corrupted,False)
    receive(native,session,packet)
    receive(native,session,pub.frame(bytes(6),values,st=2,plaintext=True),False)


def test_bad_ack_signature_never_creates_session(material,native,session,tmp_path):
    pub = publisher(material,tmp_path)
    ack = handshake(pub,native,session)
    with pytest.raises(InvalidSignature):
        pub.accept_ack(ack[:-1]+bytes([ack[-1]^1]))
    assert pub.key is None
    with pytest.raises(ValueError,match='握手'):
        pub.frame(bytes(6),[0]*8)


def test_eight_integers_reach_real_iec_decoder(material,native,session,tmp_path):
    library = os.environ.get('GOOSE_TEST_LIBIEC')
    if not library:
        pytest.skip('set GOOSE_TEST_LIBIEC for real dataset decoder')
    pub = publisher(material,tmp_path)
    pub.accept_ack(handshake(pub,native,session))
    expected = [0,1,-1,128,32767,-32768,2**31-1,-2**31]
    plain,_ = receive(native,session,pub.frame(bytes.fromhex('001122334455'),expected))
    iec = ctypes.CDLL(library)
    pointer = ctypes.c_void_p
    iec.GooseReceiver_create.restype = pointer
    iec.GooseSubscriber_create.argtypes = [ctypes.c_char_p,pointer]
    iec.GooseSubscriber_create.restype = pointer
    for name in ('GooseReceiver_destroy',):
        getattr(iec,name).argtypes = [pointer]
    iec.GooseReceiver_addSubscriber.argtypes = [pointer,pointer]
    iec.GooseReceiver_handleMessage.argtypes = [pointer,pointer,ctypes.c_int]
    iec.GooseSubscriber_setAppId.argtypes = [pointer,ctypes.c_uint16]
    iec.GooseSubscriber_getDataSetValues.argtypes = [pointer]
    iec.GooseSubscriber_getDataSetValues.restype = pointer
    iec.GooseSubscriber_isValid.argtypes = [pointer]
    iec.GooseSubscriber_isValid.restype = ctypes.c_bool
    iec.MmsValue_getArraySize.argtypes = [pointer]
    iec.MmsValue_getArraySize.restype = ctypes.c_int
    iec.MmsValue_getElement.argtypes = [pointer,ctypes.c_int]
    iec.MmsValue_getElement.restype = pointer
    iec.MmsValue_toInt32.argtypes = [pointer]
    iec.MmsValue_toInt32.restype = ctypes.c_int32
    listener_type = ctypes.CFUNCTYPE(None,pointer,pointer)
    received = []
    @listener_type
    def listener(subscriber,_):
        if iec.GooseSubscriber_isValid(subscriber):
            dataset = iec.GooseSubscriber_getDataSetValues(subscriber)
            received.append([iec.MmsValue_toInt32(iec.MmsValue_getElement(dataset,i)) for i in range(iec.MmsValue_getArraySize(dataset))])
    iec.GooseSubscriber_setListener.argtypes = [pointer,listener_type,pointer]
    receiver = iec.GooseReceiver_create()
    subscriber = iec.GooseSubscriber_create(b'TEMPLATEPIGO/LLN0$GO$gocb1',None)
    iec.GooseSubscriber_setAppId(subscriber,0x1000)
    iec.GooseSubscriber_setListener(subscriber,listener,None)
    iec.GooseReceiver_addSubscriber(receiver,subscriber)
    try:
        iec.GooseReceiver_handleMessage(receiver,plain,len(plain))
        assert received == [expected]
    finally:
        iec.GooseReceiver_destroy(receiver)


def test_peer_revocation_checked_by_publisher(material,native,session,tmp_path):
    pub = publisher(material,tmp_path)
    ack = handshake(pub,native,session)
    pub.crl.write_bytes(crl(material['root'],material['root_key'],2,revoked=[material['cert'].serial_number]))
    with pytest.raises(ValueError,match='CRL'):
        pub.accept_ack(ack)
    assert pub.key is None


def test_wrong_trust_root_checked_by_publisher(material,native,session,tmp_path):
    pub = publisher(material,tmp_path)
    ack = handshake(pub,native,session)
    foreign_key,foreign_root = identity('foreign',ca=True)
    pub.ca.write_bytes(foreign_root.public_bytes(ENC))
    pub.crl.write_bytes(crl(foreign_root,foreign_key))
    with pytest.raises(ValueError,match='证书链'):
        pub.accept_ack(ack)
    assert pub.key is None


@pytest.mark.parametrize('value',[-2**31,-32768,-129,-128,-1,0,127,128,2**31-1])
def test_signed_ber_integer_roundtrip(value):
    assert int.from_bytes(signed(value),'big',signed=True) == value


@pytest.mark.parametrize('packet',[b'',b'\x01\x00',b'\x01\x00\x10abc',b'x'*1025])
def test_malformed_ack_is_rejected(packet):
    with pytest.raises(ValueError):
        parse_ack(packet)
