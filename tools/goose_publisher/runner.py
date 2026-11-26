"""Thread-safe GUI runner using Npcap/Scapy for Ethernet, UDP for GSEC1."""
from dataclasses import dataclass
import ipaddress
import socket
import struct
import sys

from .protocol import Publisher


@dataclass(frozen=True)
class Adapter:
    name: str
    description: str
    network_name: str
    address: str
    mac: str
    index: int

    @property
    def label(self):
        return '%s · %s · %s' % (self.description or self.name, self.address, self.mac)


def collect_adapters(interfaces, log=None):
    """Do not rely on pcap UP flags, which may be absent/stale on Windows."""
    log = log or (lambda message:None)
    result = []
    seen = set()
    for interface in interfaces:
        name = getattr(interface,'description','') or getattr(interface,'name','') or '(unnamed)'
        ip_map = getattr(interface,'ips',{}) or {}
        addresses = list(ip_map.get(4,[]))
        primary = getattr(interface,'ip',None)
        if primary and primary not in addresses:
            addresses.append(primary)
        mac = getattr(interface,'mac','') or ''
        log('网卡：%s IPv4=%s MAC=%s flags=%s' % (name,','.join(map(str,addresses)) or '(无)',mac or '(无)',getattr(interface,'flags','?')))
        try:
            raw_mac = bytes.fromhex(mac.replace(':','').replace('-',''))
        except ValueError:
            raw_mac = b''
        if len(raw_mac) != 6 or not any(raw_mac):
            log('排除 %s：缺少有效的以太网 MAC，可能是回环或 Npcap 未关联到系统网卡。' % name)
            continue
        if not addresses:
            log('排除 %s：没有 IPv4 地址；请检查 Windows IPv4 配置。' % name)
            continue
        for address in addresses:
            try:
                ip = ipaddress.IPv4Address(address)
            except (ValueError,TypeError):
                log('排除地址 %s：不是有效 IPv4。' % address)
                continue
            if ip.is_unspecified or ip.is_loopback or ip.is_multicast:
                continue
            key = interface.network_name,str(ip)
            if key not in seen:
                result.append(Adapter(interface.name,name,interface.network_name,str(ip),mac,interface.index))
                seen.add(key)
    return result


def adapters(log=None):
    from scapy.all import conf
    log = log or (lambda message:None)
    log('网卡检测：platform=%s use_pcap=%s use_npcap=%s' % (sys.platform,conf.use_pcap,getattr(conf,'use_npcap',False)))
    if sys.platform == 'win32' and not conf.use_pcap:
        raise RuntimeError('未检测到 Npcap。请安装 Npcap 后重启工具；若驱动限制管理员访问，请以管理员身份运行。')
    conf.ifaces.reload()
    interfaces = list(conf.ifaces.values())
    log('Scapy/Npcap 枚举到 %d 张网卡；不按 UP 标记预先过滤。' % len(interfaces))
    result = collect_adapters(interfaces,log)
    if not result:
        raise RuntimeError('没有可选的 IPv4 以太网地址（枚举到 %d 张网卡）。具体排除原因见窗口日志。'
                           '请确认 Npcap、管理员权限及网卡 IPv4 配置，安装驱动后需退出并重新打开本工具。' % len(interfaces))
    return result


def bind_udp(sock, adapter):
    sock.bind((adapter.address, 0))
    if sys.platform == 'win32':
        # IP_UNICAST_IF takes the Windows interface index in network byte order.
        sock.setsockopt(socket.IPPROTO_IP, 31, struct.pack('!I',adapter.index))
    elif sys.platform.startswith('linux'):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, adapter.name.encode()+b'\0')


class Ethernet:
    def __init__(self, adapter):
        from scapy.all import conf
        self.socket = conf.L2socket(iface=adapter.network_name)

    def send(self, data):
        from scapy.all import Ether
        # Parse as Ethernet so Npcap's L2 socket uses ETH_P_GOOSE metadata too.
        self.socket.send(Ether(data))

    def close(self):
        self.socket.close()


def validate(data):
    ip = ipaddress.IPv4Address(data['target'])
    if ip.is_unspecified or ip.is_loopback or ip.is_multicast or int(ip) == 0xffffffff:
        raise ValueError('请输入目标设备 net2 的单播 IPv4 地址')
    if data['mode'] not in ('normal','replay','tamper','tamper-recover','plaintext','bad-signature'):
        raise ValueError('测试模式不合法')
    count, interval = int(data['count']), float(data['interval'])
    if not 1 <= count <= 100000 or not .05 <= interval <= 5:
        raise ValueError('帧数须为 1–100000；发送间隔为 0.05–5 秒')
    values = [int(item.strip()) for item in data['values'].replace('，',',').split(',')]
    if len(values) != 8 or any(not -(2**31) <= value < 2**31 for value in values):
        raise ValueError('数据集必须是 8 个逗号分隔的 int32 整数')
    return str(ip), count, interval, values


def run(data, adapter, stop, log, *, publisher_factory=None, udp_factory=None, ethernet_factory=Ethernet):
    target, count, interval, values = validate(data)
    if publisher_factory is None:
        from .trust import verify_certificate
        publisher_factory = lambda cert,key,ca,crl: Publisher(cert,key,ca,crl,verifier=verify_certificate)
    if udp_factory is None:
        udp_factory = lambda: socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    source = bytes.fromhex(adapter.mac.replace(':','').replace('-',''))
    if len(source) != 6:
        raise ValueError('网卡 MAC 地址不合法')
    if stop.is_set():
        return 'stopped'
    publisher = publisher_factory(*(data[name] for name in ('cert','key','ca','crl')))
    log('本端证书、私钥及 CA/CRL 校验通过。')
    # Open the injection driver before establishing a remote session. Fail early
    # when Npcap is missing or the user lacks permission.
    ethernet = ethernet_factory(adapter)
    try:
        hello = publisher.hello
        if data['mode'] == 'bad-signature':
            hello = hello[:-1]+bytes([hello[-1]^1])
        with udp_factory() as udp:
            bind_udp(udp,adapter)
            udp.settimeout(.5)
            udp.connect((target,30001))
            log('开始握手：%s → %s:30001，网卡=%s' % (adapter.address,target,adapter.name))
            ack = None
            for attempt in range(10):
                if stop.is_set():
                    return 'stopped'
                udp.send(hello)
                try:
                    ack = udp.recv(1025)
                    break
                except socket.timeout:
                    log('等待 ACK：%d/10' % (attempt+1))
            if ack is None:
                if data['mode'] == 'bad-signature':
                    log('错误签名 HELLO 未收到 ACK；须结合设备拒绝日志判断，超时本身不能证明测试通过。')
                    return 'negative-unconfirmed'
                raise TimeoutError('握手超时。检查 UDP 30001 放行、设备日志和旧会话；两次独立测试间需空闲超过 30 秒。')
            if data['mode'] == 'bad-signature':
                raise ValueError('错误签名 HELLO 仍收到 ACK，请检查接收端')
            peer = publisher.accept_ack(ack)
            log('ACK 证书链、CRL、签名验证通过；ECDHE/HKDF 完成。对端='+peer)
        for index in range(count):
            if stop.is_set():
                return 'stopped'
            st,sq = (index+1,0) if data.get('change_state') else (1,index)
            packet = publisher.frame(source,values,st,sq,plaintext=data['mode']=='plaintext')
            if data['mode'] in ('tamper','tamper-recover'):
                ethernet.send(packet[:-1]+bytes([packet[-1]^1]))
                log('已发送错误 GCM tag 帧 stNum=%d sqNum=%d' % (st,sq))
                if stop.wait(.05):
                    return 'stopped'
            if data['mode'] != 'tamper':
                ethernet.send(packet)
            if data['mode'] == 'replay':
                if stop.wait(.05):
                    return 'stopped'
                ethernet.send(packet)
                log('已重发完全相同帧 stNum=%d sqNum=%d；原合法帧允许首次业务转发。' % (st,sq))
            if index < 10 or (index+1) % 100 == 0 or index+1 == count:
                log('已发送 %d/%d：stNum=%d sqNum=%d mode=%s bytes=%d' % (index+1,count,st,sq,data['mode'],len(packet)))
            if index+1 < count and stop.wait(interval):
                return 'stopped'
        return 'finished'
    finally:
        ethernet.close()
