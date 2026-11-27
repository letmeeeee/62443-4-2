"""Real C authentication -> IEC decoder -> middle.c -> Modbus write boundary."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import struct

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools/goose_publisher'))
sys.path.insert(0,str(ROOT/'goose/goose_test/tests'))
from test_goose_security import material, native, session
from tools.goose_publisher.test_protocol import publisher, handshake


@pytest.fixture(scope='session')
def bridge_library(tmp_path_factory):
    library=os.environ.get('GOOSE_TEST_LIBIEC')
    if not library:
        pytest.skip('GOOSE_TEST_LIBIEC must reference a native libiec61850.so')
    base=ROOT/'goose/goose_test'
    iec=ROOT/'goose/libiec61850'
    output=tmp_path_factory.mktemp('bridge')/'bridge.so'
    command=['gcc','-std=gnu99','-shared','-fPIC','-fvisibility=hidden','-ffunction-sections','-fdata-sections',
             '-Wl,--gc-sections','-I'+str(base)]
    for directory in ('src','src/iec61850/inc','src/common/inc','src/goose','src/mms/inc',
                      'src/mms/iso_mms','src/mms/iso_mms/asn1c','src/logging','hal/inc','src/r_session'):
        command.append('-I'+str(iec/directory))
    command += [str(base/'tests/bridge_harness.c'),str(base/'security/goose_security.c'),
                str(base/'security/goose_log.c'),str(Path(library).resolve()),
                '-Wl,-rpath,'+str(Path(library).resolve().parent),'-lcrypto','-lpthread','-lrt','-o',str(output)]
    subprocess.run(command,check=True,capture_output=True)
    lib=ctypes.CDLL(str(output))
    lib.bridge_feed.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t]
    lib.bridge_write_byte.argtypes=[ctypes.c_uint,ctypes.c_uint]
    lib.bridge_modbus_response_fault.argtypes=[ctypes.c_int]
    yield lib


@pytest.fixture
def bridge(bridge_library,session):
    assert bridge_library.bridge_init()==0
    yield bridge_library
    bridge_library.bridge_close()


def feed(bridge,session,packet):
    result=bridge.bridge_feed(session,packet,len(packet))
    writes=bridge.bridge_drain()
    assert writes >= 0
    return result,writes


def test_tamper_replay_and_sq_retransmission_do_not_repeat_writes(material,native,session,tmp_path,bridge):
    pub=publisher(material,tmp_path)
    pub.accept_ack(handshake(pub,native,session))
    values=[11,12,13,14,21,22,23,24]
    packet=pub.frame(bytes(6),values)
    # A bad tag before the first valid frame never reaches Modbus.
    result,writes=feed(bridge,session,packet[:-1]+bytes([packet[-1]^1]))
    assert result < 0 and writes == 0
    result,writes=feed(bridge,session,packet)
    assert result > 0 and writes == 2  # two actual 0x10 batches for dual BUS
    assert bridge.bridge_write_byte(0,7)==0x10
    assert (bridge.bridge_write_byte(0,8)<<8 | bridge.bridge_write_byte(0,9))==27204
    assert (bridge.bridge_write_byte(1,8)<<8 | bridge.bridge_write_byte(1,9))==27504
    assert bridge.bridge_write_byte(0,14)==11
    assert bridge.bridge_write_byte(1,14)==21
    # An exact wire replay is rejected at the security layer.
    result,writes=feed(bridge,session,packet)
    assert result < 0 and writes == 2
    # Fresh sqNum is authenticated but the same state must not be written again.
    repeated=pub.frame(bytes(6),values,st=1,sq=1)
    result,writes=feed(bridge,session,repeated)
    assert result > 0 and writes == 2
    changed=pub.frame(bytes(6),values,st=2,sq=0)
    result,writes=feed(bridge,session,changed[:-1]+bytes([changed[-1]^1]))
    assert result < 0 and writes == 2
    result,writes=feed(bridge,session,changed)
    assert result > 0 and writes == 4
    text=next((tmp_path/'logs').glob('*.log')).read_text()
    assert 'same-state retransmission ignored: stNum=1 sqNum=1' in text
    assert 'Modbus batch queued addr=27204 count=4 stNum=1 sqNum=0' in text
    assert 'Modbus TX peer=127.0.0.1:1502' in text and 'Modbus RX tid=' in text


def test_plaintext_and_modified_authenticated_header_never_write(material,native,session,tmp_path,bridge):
    pub=publisher(material,tmp_path)
    pub.accept_ack(handshake(pub,native,session))
    plain=pub.frame(bytes(6),[0]*8,st=1,plaintext=True)
    assert feed(bridge,session,plain)[1]==0
    packet=pub.frame(bytes(6),[0]*8,st=2)
    modified=bytearray(packet)
    position=packet.index(b'gocb1')
    modified[position]^=1
    result,writes=feed(bridge,session,bytes(modified))
    assert result < 0 and writes==0
    assert feed(bridge,session,packet)[1]==2


@pytest.mark.parametrize('fault', [0, 1, 2, 3, 4])
def test_modbus_fragmented_response_and_invalid_replies(bridge, fault):
    bridge.bridge_modbus_response_fault(fault)
    result=bridge.bridge_modbus_probe()
    assert (result == 0) == (fault == 0)


def _resign_header(packet, key, old, new, st):
    assert len(old) == len(new) and old in packet
    frame=bytearray(packet.replace(old,new,1))
    data=frame.index(b'\xab',22)
    length=frame[data+1]
    if length & 0x80:
        width=length & 0x7f
        length=int.from_bytes(frame[data+2:data+2+width],'big')
        start=data+2+width
    else:
        start=data+2
    body=frame.index(b'\x61',22)
    aad_start=body+2 if frame[body+1]<128 else body+2+(frame[body+1]&0x7f)
    aad=bytes(frame[aad_start:start])
    plaintext=AESGCM(key).decrypt(struct.pack('!QI',st,0),packet[start:start+length]+packet[start+length+5:start+length+21],
                                  bytes(packet[aad_start:start]))
    sealed=AESGCM(key).encrypt(struct.pack('!QI',st,0),plaintext,aad)
    frame[start:start+length]=sealed[:-16]
    frame[start+length+5:start+length+21]=sealed[-16:]
    return bytes(frame)


@pytest.mark.parametrize('old,new', [
    (b'TEMPLATEPIGO/LLN0$dsGOOSE1',b'TEMPLATEPIGO/LLN0$dsGOOSE2'),
    (b'\x88\x01\x01',b'\x88\x01\x02'),
    (b'\x87\x01\x00',b'\x87\x01\x01'),
    (b'\x89\x01\x00',b'\x89\x01\x01'),
])
def test_authenticated_wrong_business_header_never_writes(material,native,session,tmp_path,bridge,old,new):
    pub=publisher(material,tmp_path)
    pub.accept_ack(handshake(pub,native,session))
    packet=pub.frame(bytes(6),[1]*8)
    modified=_resign_header(packet,pub.key,old,new,1)
    result,writes=feed(bridge,session,modified)
    assert result > 0 and writes == 0
