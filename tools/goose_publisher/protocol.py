"""Independent publisher implementation; authenticates ACK before deriving a key."""
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import time

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

REFERENCE = b'TEMPLATEPIGO/LLN0$GO$gocb1'
DESTINATION = bytes.fromhex('010ccd010000')
CERTIFICATE = re.compile(rb'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----', re.S)


def tlv(tag, value):
    return bytes([tag])+struct.pack('!H', len(value))+value


def ber_length(n):
    if n < 128:
        return bytes([n])
    raw = n.to_bytes((n.bit_length()+7)//8, 'big')
    return bytes([0x80+len(raw)])+raw


def ber(tag, value):
    return bytes([tag])+ber_length(len(value))+value


def unsigned(n):
    raw = n.to_bytes(max(1, (n.bit_length()+7)//8), 'big')
    return b'\0'+raw if raw[0] & 0x80 else raw


def signed(n):
    if type(n) is not int or not -(2**31) <= n < 2**31:
        raise ValueError('数据集值必须为有符号 32 位整数')
    raw = n.to_bytes(4, 'big', signed=True)
    while len(raw) > 1 and ((raw[0] == 0 and raw[1] < 128) or (raw[0] == 255 and raw[1] >= 128)):
        raw = raw[1:]
    return raw


def parse_ack(data):
    if len(data) > 1024:
        raise ValueError('ACK 超过 1024 字节')
    fields, offset = {}, 0
    while offset < len(data):
        if offset+3 > len(data):
            raise ValueError('ACK TLV 头不完整')
        tag, size = struct.unpack('!BH', data[offset:offset+3])
        offset += 3
        if tag not in range(1, 9) or tag in fields or offset+size > len(data):
            raise ValueError('ACK TLV 重复、未知或越界')
        fields[tag] = data[offset:offset+size]
        offset += size
    if not set(range(1,8)) <= fields.keys():
        raise ValueError('ACK 缺少必要字段')
    if fields[1] != b'GSEC1' or fields[2] != b'\x02' or fields[3] != b'\x00\x01':
        raise ValueError('ACK MAGIC、TYPE 或 KEYID 错误')
    if len(fields[4]) != 65 or fields[4][0] != 4 or len(fields[5]) != 32 or (8 in fields and len(fields[8]) != 32):
        raise ValueError('ACK EPH、SALT 或 FP 长度错误')
    return fields


class Publisher:
    def __init__(self, cert, key, ca, crl, verifier=None):
        self.verifier = verifier
        self.ca, self.crl = Path(ca).resolve(), Path(crl).resolve()
        certificates = CERTIFICATE.findall(Path(cert).read_bytes())
        if not certificates:
            raise ValueError('未找到发布端 PEM 证书')
        self.chain = b'\n'.join(certificates[1:]+CERTIFICATE.findall(self.crl.read_bytes()))
        self.certificate = x509.load_pem_x509_certificate(certificates[0])
        self.identity = serialization.load_pem_private_key(Path(key).read_bytes(), None)
        if not isinstance(self.identity, ec.EllipticCurvePrivateKey) or not isinstance(self.identity.curve, ec.SECP256R1):
            raise ValueError('发布端私钥必须为 P-256')
        pub = lambda item: item.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        if pub(self.identity) != pub(self.certificate):
            raise ValueError('发布端证书与私钥不匹配')
        self.verify_certificate(self.certificate)
        self.ephemeral = ec.generate_private_key(ec.SECP256R1())
        self.point = self.ephemeral.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        self.salt = os.urandom(32)
        signature = self.identity.sign(b'GSEC1\x01\x00\x01'+self.point+self.salt, ec.ECDSA(hashes.SHA256()))
        self.hello = b''.join(tlv(tag, value) for tag, value in [(1,b'GSEC1'), (2,b'\x01'), (3,b'\x00\x01'),
            (4,self.point), (5,self.salt), (6,self.certificate.public_bytes(serialization.Encoding.DER)), (7,signature)])
        if len(self.hello) > 1024:
            raise ValueError('发布端证书使 HELLO 超过 1024 字节')
        self.key = None
        self.last_counter = None
        self.ack_accepted = False

    def verify_certificate(self, cert):
        key = cert.public_key()
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
            raise ValueError('握手身份必须为 P-256')
        if cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
            raise ValueError('握手身份不能是 CA 证书')
        if not cert.extensions.get_extension_for_class(x509.KeyUsage).value.digital_signature:
            raise ValueError('握手身份缺少 digitalSignature 用途')
        if self.verifier is not None:
            self.verifier(cert, self.ca, self.crl, self.chain)
            return
        with tempfile.TemporaryDirectory(prefix='goose-peer-verify-') as temporary:
            leaf = Path(temporary)/'peer.pem'
            leaf.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            command = ['openssl', 'verify', '-no-CAfile', '-no-CApath', '-trusted', str(self.ca),
                       '-x509_strict', '-verify_depth', '8', '-purpose', 'any', '-CRLfile', str(self.crl), '-crl_check_all']
            if self.chain:
                chain = Path(temporary)/'chain.pem'
                chain.write_bytes(self.chain)
                command += ['-untrusted', str(chain)]
            result = subprocess.run(command+[str(leaf)], capture_output=True, timeout=15)
            if result.returncode:
                raise ValueError('握手证书链/有效期/CRL 校验失败：'+result.stderr.decode(errors='replace').strip()[:1000])

    def accept_ack(self, packet):
        if self.ack_accepted:
            raise ValueError('本发布端实例已经建立会话，重新握手须新建实例')
        self.key = None
        self.last_counter = None
        fields = parse_ack(packet)
        cert = x509.load_der_x509_certificate(fields[6])
        self.verify_certificate(cert)
        cert.public_key().verify(fields[7], b'GSEC1\x02\x00\x01'+fields[4]+fields[5]+self.point+self.salt,
                                 ec.ECDSA(hashes.SHA256()))
        remote = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), fields[4])
        shared = self.ephemeral.exchange(ec.ECDH(), remote)
        self.key = HKDF(algorithm=hashes.SHA256(), length=16, salt=self.salt+fields[5], info=b'GOOSE_SEC_P2S_V1').derive(shared)
        self.ack_accepted = True
        return cert.subject.rfc4514_string()

    def frame(self, source, values, st=1, sq=0, plaintext=False):
        if self.key is None:
            raise ValueError('必须先完成已认证握手')
        if not 1 <= st <= 0xffffffff or not 0 <= sq <= 0xffffffff:
            raise ValueError('stNum/sqNum 超出当前订阅端 uint32 范围')
        if self.last_counter is not None and (st,sq) <= self.last_counter:
            raise ValueError('同一会话禁止重复加密 nonce；重放测试须重发缓存帧')
        if not 1 <= len(values) <= 256 or len(source) != 6:
            raise ValueError('数据集长度或源 MAC 不合法')
        data = b''.join(ber(0x85, signed(value)) for value in values)
        seconds = time.time()
        timestamp = struct.pack('!I', int(seconds))+int((seconds-int(seconds))*2**24).to_bytes(3,'big')+b'\x0a'
        aad = b''.join(ber(tag,value) for tag,value in [(0x80,REFERENCE), (0x81,unsigned(5000)),
            (0x82,b'TEMPLATEPIGO/LLN0$dsGOOSE1'), (0x83,b'gocb1'), (0x84,timestamp), (0x85,unsigned(st)),
            (0x86,unsigned(sq)), (0x87,b'\0'), (0x88,b'\x01'), (0x89,b'\0'), (0x8a,unsigned(len(values)))])
        aad += b'\xab'+ber_length(len(data))
        if plaintext:
            body = aad+data
        else:
            ciphertext = AESGCM(self.key).encrypt(struct.pack('!QI', st, sq), data, aad)
            body = aad+ciphertext[:-16]+ber(0x9c,b'\x01\x00\x01'+ciphertext[-16:])
        pdu = ber(0x61,body)
        frame = DESTINATION+source+b'\x88\xb8'+struct.pack('!HHHH',0x1000,len(pdu)+8,0,0)+pdu
        if len(frame) > 1514:
            raise ValueError('帧超过标准以太网 MTU，请减少数据集元素')
        self.last_counter = st,sq
        return frame
