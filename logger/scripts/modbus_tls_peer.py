#!/usr/bin/env python3
"""手动 Modbus TLS 主机/模拟从机，只使用 Python 标准库。"""
import argparse
import hashlib
import socket
import ssl
import struct
import sys
from pathlib import Path


def context(role, directory, no_cert=False):
    required = ['master-ca.crt'] if role == 'slave' else []
    if not no_cert:
        required += [role + '.crt', role + '.key']
    missing = [str(directory / name) for name in required if not (directory / name).is_file()]
    if missing:
        raise ValueError('缺少证书文件：' + '、'.join(missing) +
                         '。请先用 modbus_certs.py generate 生成本机身份；'
                         '从机还需用 trust-add 导入对端主机公开证书，生成 master-ca.crt。')
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER if role == 'slave' else ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    if role == 'master':
        # 与项目一致：只要求主动方证明身份，不验证从机身份。
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    else:
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.load_verify_locations(str(directory / 'master-ca.crt'))
    if not no_cert:
        ctx.load_cert_chain(str(directory / (role + '.crt')), str(directory / (role + '.key')))
    return ctx


def exact(conn, size):
    data = bytearray()
    while len(data) < size:
        part = conn.recv(size - len(data))
        if not part:
            raise ConnectionError('对端关闭连接，未收到完整 Modbus 报文')
        data.extend(part)
    return bytes(data)


def receive(conn):
    header = exact(conn, 7)
    tid, protocol, length, unit = struct.unpack('!HHHB', header)
    if protocol != 0 or not 2 <= length <= 254:
        raise ValueError('无效 MBAP 协议号或长度')
    return tid, unit, exact(conn, length - 1)


def send(conn, tid, unit, pdu):
    conn.sendall(struct.pack('!HHHB', tid, 0, len(pdu) + 1, unit) + pdu)


def describe(conn, server=False):
    print('TLS 已建立：', conn.version(), '加密算法：', conn.cipher()[0], flush=True)
    if server:
        cert = conn.getpeercert()
        print('主机身份验证通过：', cert['subject'], flush=True)
        print('主机证书 SHA256：', hashlib.sha256(conn.getpeercert(binary_form=True)).hexdigest().upper(), flush=True)
    else:
        print('已进入 TLS 通道；继续读取 Modbus 响应确认通信（从机身份未校验）。', flush=True)


def master(args):
    ctx = context('master', args.cert_dir, args.no_cert)
    print('主动连接 {}:{}，{}'.format(args.host, args.port, '不携带证书（反例）' if args.no_cert else '携带主机证书'), flush=True)
    with socket.create_connection((args.host, args.port), timeout=args.timeout) as raw:
        with ctx.wrap_socket(raw, server_hostname=args.host) as conn:
            describe(conn)
            send(conn, 1, args.unit, struct.pack('!BHH', args.function, args.address, args.count))
            tid, unit, pdu = receive(conn)
            if tid != 1 or unit != args.unit:
                raise ValueError('响应事务号或站号不匹配')
            if pdu[0] == args.function | 0x80 and len(pdu) == 2:
                raise ValueError('收到 Modbus 异常码 {}：TLS 通信成功，但寄存器请求被拒绝'.format(pdu[1]))
            if pdu[0] != args.function or len(pdu) != 2 + args.count * 2 or pdu[1] != args.count * 2:
                raise ValueError('响应功能码、长度或字节数不匹配')
            values = struct.unpack('!{}H'.format(args.count), pdu[2:])
            print('Modbus 读取成功：', dict(enumerate(values, args.address)), flush=True)


def reply(pdu):
    function = pdu[0]
    if function not in (3, 4):
        return bytes([function | 0x80, 1])
    if len(pdu) != 5:
        return bytes([function | 0x80, 3])
    address, count = struct.unpack('!HH', pdu[1:])
    if not 1 <= count <= 125:
        return bytes([function | 0x80, 3])
    if address + count > 65536:
        return bytes([function | 0x80, 2])
    # 模拟值：寄存器地址低 16 位，无设备控制副作用。
    return bytes([function, count * 2]) + struct.pack('!{}H'.format(count), *range(address, address + count))


def slave(args):
    ctx = context('slave', args.cert_dir)
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((args.bind, args.port))
        listener.listen(5)
        print('模拟从机监听 {}:{}；必须通过主机证书验证，Ctrl+C 停止'.format(*listener.getsockname()), flush=True)
        while True:
            raw, address = listener.accept()
            print('收到 TCP 连接：', address, flush=True)
            try:
                with raw:
                    raw.settimeout(args.timeout)
                    with ctx.wrap_socket(raw, server_side=True) as conn:
                        describe(conn, server=True)
                        while True:
                            tid, unit, pdu = receive(conn)
                            response = reply(pdu)
                            send(conn, tid, unit, response)
                            print('已处理 Modbus 请求：站号={} PDU={} 响应={}'.format(unit, pdu.hex(' '), response.hex(' ')), flush=True)
            except (OSError, ValueError) as exc:
                print('连接结束/拒绝：', exc, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='role', required=True)
    for role in ('master', 'slave'):
        p = sub.add_parser(role, help='主动读取寄存器' if role == 'master' else '验证主机身份并返回模拟寄存器')
        p.add_argument('--cert-dir', type=Path, default=Path('/etc/ems/modbus'))
        p.add_argument('--port', type=int, default=18020)
        p.add_argument('--timeout', type=float, default=5)
        if role == 'master':
            p.add_argument('--host', default='127.0.0.1')
            p.add_argument('--no-cert', action='store_true', help='不出示证书，验证对端是否拒绝')
            p.add_argument('--unit', type=int, default=1)
            p.add_argument('--function', type=int, choices=(3, 4), default=3)
            p.add_argument('--address', type=int, default=0, help='协议中的零起始地址，不是 40001 编号')
            p.add_argument('--count', type=int, default=1)
        else:
            p.add_argument('--bind', default='127.0.0.1', help='供设备连接时指定本机网卡 IP')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or args.timeout <= 0:
        parser.error('端口必须为 1～65535，超时必须大于 0')
    if args.role == 'master' and not (0 <= args.unit <= 255 and 0 <= args.address <= 65535 and 1 <= args.count <= 125 and args.address + args.count <= 65536):
        parser.error('检查站号、地址和数量：站号 0～255，地址 0～65535，数量 1～125，不得越界')
    try:
        (master if args.role == 'master' else slave)(args)
    except (OSError, ValueError) as exc:
        print('失败：', exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('\n已停止')
    return 0


if __name__ == '__main__':
    sys.exit(main())
