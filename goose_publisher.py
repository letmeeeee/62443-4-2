#!/usr/bin/env python3
"""在 Linux 隔离联调网络模拟 GSEC1/加密 GOOSE 发布端。"""
import argparse
import ipaddress
from pathlib import Path
import re
import socket
import sys
import time

from tools.goose_publisher.protocol import Publisher


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interface', required=True, help='测试 PC 的有线网卡，需连接设备 net2 所在二层网络')
    parser.add_argument('--target', required=True, help='设备 net2 的 IPv4 地址')
    for part in ('cert', 'key', 'ca', 'crl'):
        parser.add_argument('--'+part, required=True, help='发布端本机 PKI 文件路径')
    parser.add_argument('--values', default='0,0,0,0,0,0,0,0', help='8 个逗号分隔的 int32 数据，默认全零')
    parser.add_argument('--count', type=int, default=10)
    parser.add_argument('--interval', type=float, default=1.0)
    parser.add_argument('--change-state', action='store_true', help='每帧递增 stNum；默认 stNum=1、sqNum 递增')
    parser.add_argument('--mode', choices=['normal','replay','tamper','plaintext','bad-signature'], default='normal')
    args = parser.parse_args()
    if not sys.platform.startswith('linux'):
        parser.error('此模拟器需要 Linux AF_PACKET 网卡发包能力')
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,15}', args.interface):
        parser.error('网卡名称不合法')
    if not 1 <= args.count <= 100000 or not .05 <= args.interval <= 5:
        parser.error('count 范围为 1–100000；interval 范围为 0.05–5 秒')
    target = ipaddress.IPv4Address(args.target)
    if target.is_multicast or target.is_unspecified or target.is_loopback or int(target) == 0xffffffff:
        parser.error('target 必须为设备 net2 的单播 IPv4 地址')
    values = [int(item.strip()) for item in args.values.split(',')]
    if len(values) != 8 or any(value < -(2**31) or value >= 2**31 for value in values):
        parser.error('values 需要 8 个 int32 整数')
    socket.if_nametoindex(args.interface)
    source = bytes.fromhex((Path('/sys/class/net')/args.interface/'address').read_text().strip().replace(':',''))
    publisher = Publisher(args.cert, args.key, args.ca, args.crl)
    print('发布端身份已通过证书/CRL 校验；不打印私钥或会话密钥。', flush=True)
    print('目标=%s interface=%s APPID=0x1000 mode=%s' % (target,args.interface,args.mode), flush=True)
    hello = publisher.hello
    if args.mode == 'bad-signature':
        hello = hello[:-1]+bytes([hello[-1]^1])
    # An identical HELLO is retransmitted, preserving the ephemeral key and salt.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        udp.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, args.interface.encode()+b'\0')
        udp.settimeout(.5)
        udp.connect((str(target),30001))
        ack = None
        for attempt in range(10):
            udp.send(hello)
            try:
                ack = udp.recv(1025)
                break
            except socket.timeout:
                print('等待 ACK：%d/10' % (attempt+1), flush=True)
        if ack is None:
            if args.mode == 'bad-signature':
                print('篡改 HELLO 签名后未收到 ACK；请对照订阅端认证拒绝日志确认，超时本身不能证明通过。')
                return
            raise TimeoutError('未收到 ACK：检查 UDP/30001、PKI 和接收端日志；旧会话需停止发包并空闲超过 30 秒')
        if args.mode == 'bad-signature':
            raise ValueError('异常：错误签名 HELLO 仍收到 ACK，请检查接收端')
        peer = publisher.accept_ack(ack)
        print('ACK 证书链/CRL/签名已验证；ECDHE/HKDF 完成。对端='+peer, flush=True)
    with socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x88b8)) as ethernet:
        ethernet.bind((args.interface,0))
        for index in range(args.count):
            st, sq = (index+1,0) if args.change_state else (1,index)
            packet = publisher.frame(source,values,st,sq,plaintext=args.mode=='plaintext')
            if args.mode == 'tamper':
                damaged = packet[:-1]+bytes([packet[-1]^1])
                ethernet.send(damaged)
                time.sleep(.05)
            ethernet.send(packet)
            if args.mode == 'replay':
                time.sleep(.05)
                ethernet.send(packet)  # Exact bytes: never re-encrypt with a reused nonce.
            print('已发送 stNum=%d sqNum=%d mode=%s bytes=%d' % (st,sq,args.mode,len(packet)), flush=True)
            if index+1 < args.count:
                time.sleep(args.interval)
    print('发送结束；以设备认证/拒绝日志和 Modbus 侧观测为验收依据。')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n已停止。')
    except Exception as exc:
        raise SystemExit('GOOSE 模拟失败：'+str(exc))
