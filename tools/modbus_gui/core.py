"""Modbus TCP framing over TLS; GUI-independent client and concurrent server."""
import socket
import ssl
import struct
import threading


def tls_context(server, cert='', key='', ca='', mutual=True, password=None, verify_peer=True):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER if server else ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    if server:
        if not cert or not key:
            raise ValueError('服务端必须配置证书和私钥')
        ctx.verify_mode = ssl.CERT_REQUIRED if mutual else ssl.CERT_NONE
    elif not verify_peer:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    # Client identity and server verification are independently configurable.
    if (server and mutual) or (not server and verify_peer):
        if not ca:
            raise ValueError('请选择可信 CA / 对端自签证书')
        ctx.load_verify_locations(cafile=ca)
    # Support directly trusted self-signed leaf certificates on recent OpenSSL.
    if hasattr(ssl, 'VERIFY_X509_PARTIAL_CHAIN'):
        ctx.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
    if (server or mutual) and (cert or key):
        if not cert or not key:
            raise ValueError('身份证书和私钥必须同时配置')
        ctx.load_cert_chain(cert, key, password=password or '')
    elif not server and mutual:
        raise ValueError('双向认证需要客户端证书和私钥')
    return ctx


def exact(conn, count):
    result = bytearray()
    while len(result) < count:
        chunk = conn.recv(count - len(result))
        if not chunk:
            raise EOFError('对端关闭连接')
        result.extend(chunk)
    return bytes(result)


def format_frame(direction, frame, peer='', request=True):
    """Describe the actual application bytes, before interpreting the response."""
    tid, protocol, length, unit = struct.unpack('!HHHB', frame[:7])
    pdu = frame[7:]
    lines = ['{} {} | ADU={} 字节'.format(direction, peer, len(frame)),
             '  ADU: ' + frame.hex(' ').upper(),
             '  MBAP: ' + frame[:7].hex(' ').upper(),
             '  事务号={} (0x{:04X}) 协议号={} 长度={}（站号+PDU） 站号={}'.format(tid, tid, protocol, length, unit),
             '  PDU: ' + pdu.hex(' ').upper()]
    if not pdu:
        lines.append('  PDU 为空 / 报文头无效')
        return '\n'.join(lines)
    function = pdu[0]
    lines.append('  功能码={} (0x{:02X})'.format(function, function))
    if function & 0x80 and len(pdu) == 2:
        names = {1: '非法功能', 2: '非法数据地址', 3: '非法数据值', 4: '服务端设备故障', 11: '网关目标设备无响应'}
        lines.append('  异常码=0x{:02X} {}'.format(pdu[1], names.get(pdu[1], '未知异常')))
    elif function == 6 and len(pdu) == 5:
        address, value = struct.unpack('!HH', pdu[1:])
        lines.append('  地址={} 写入值={} (0x{:04X})'.format(address, value, value))
    elif (request and function in (3, 4, 16)) or (not request and function == 16):
        if len(pdu) >= 5:
            address, count = struct.unpack('!HH', pdu[1:5])
            lines.append('  起始地址={} 数量={}'.format(address, count))
        if request and function == 16 and len(pdu) >= 6:
            lines.append('  字节数={}'.format(pdu[5]))
            data = pdu[6:]
            if len(data) % 2 == 0:
                lines.append('  寄存器值=' + str(list(struct.unpack('!{}H'.format(len(data) // 2), data))))
    elif not request and function in (3, 4) and len(pdu) >= 2:
        lines.append('  字节数={}'.format(pdu[1]))
        data = pdu[2:]
        if len(data) % 2 == 0:
            lines.append('  寄存器值=' + str(list(struct.unpack('!{}H'.format(len(data) // 2), data))))
    return '\n'.join(lines)


def receive(conn, trace=None):
    header = exact(conn, 7)
    tid, protocol, length, unit = struct.unpack('!HHHB', header)
    if protocol != 0 or not 2 <= length <= 254:
        if trace:
            trace(header)
        raise ValueError('无效的 MBAP 协议号或长度')
    pdu = exact(conn, length - 1)
    if trace:
        trace(header + pdu)
    return tid, unit, pdu


def send(conn, tid, unit, pdu, trace=None):
    frame = struct.pack('!HHHB', tid, 0, len(pdu) + 1, unit) + pdu
    conn.sendall(frame)
    if trace:
        trace(frame)


def bounds(address, count, maximum):
    if not 0 <= address <= 65535 or not 1 <= count <= maximum or address + count > 65536:
        raise ValueError('地址范围 0～65535，数量范围 1～{}，末地址不得越界'.format(maximum))


def request_pdu(function, address, count=1, values=()):
    if function in (3, 4):
        bounds(address, count, 125)
        return struct.pack('!BHH', function, address, count)
    if function not in (6, 16):
        raise ValueError('支持功能码 03、04、06、16')
    values = list(values)
    bounds(address, len(values), 1 if function == 6 else 123)
    if any(not 0 <= v <= 65535 for v in values):
        raise ValueError('寄存器值范围 0～65535')
    if function == 6:
        return struct.pack('!BHH', function, address, values[0])
    return struct.pack('!BHHB', function, address, len(values), len(values) * 2) + struct.pack('!{}H'.format(len(values)), *values)


def exchange(ctx, host, port, unit, function, address, count=1, values=(), timeout=5,
             server_name='', log=lambda message: None):
    if not host or not 1 <= port <= 65535 or not 0 <= unit <= 255 or not 0 < timeout <= 120:
        raise ValueError('检查主机、端口、站号及超时（0～120 秒）')
    pdu = request_pdu(function, address, count, values)
    with socket.create_connection((host, port), timeout=timeout) as raw:
        with ctx.wrap_socket(raw, server_hostname=server_name or host) as conn:
            verification = '未验证服务端证书及名称' if ctx.verify_mode == ssl.CERT_NONE else '服务端身份验证通过'
            log('{} / {}，{}'.format(conn.version(), conn.cipher()[0], verification))
            peer = '客户端 → {}:{}'.format(host, port)
            send(conn, 1, unit, pdu, trace=lambda frame: log(format_frame('TX', frame, peer, request=True)))
            tid, response_unit, response = receive(conn, trace=lambda frame: log(
                format_frame('RX', frame, '客户端 ← {}:{}'.format(host, port), request=False)))
    if tid != 1 or response_unit != unit:
        raise ValueError('响应事务号或站号不匹配')
    if response[0] == function | 0x80 and len(response) == 2:
        raise ValueError('Modbus 异常码 0x{:02X}'.format(response[1]))
    if function in (3, 4):
        if len(response) != 2 + count * 2 or response[:2] != bytes([function, count * 2]):
            raise ValueError('响应功能码、字节数或长度错误')
        return list(struct.unpack('!{}H'.format(count), response[2:]))
    expected = pdu if function == 6 else pdu[:5]
    if response != expected:
        raise ValueError('写入响应与请求不匹配')
    return list(values)


class RegisterBank:
    def __init__(self):
        self.lock = threading.Lock()
        self.holding = [0] * 65536
        self.inputs = [0] * 65536

    def snapshot(self, function, address, count):
        bounds(address, count, 125)
        with self.lock:
            return (self.inputs if function == 4 else self.holding)[address:address + count]

    def edit(self, function, address, values):
        values = list(values)
        bounds(address, len(values), 123)
        if any(not 0 <= v <= 65535 for v in values):
            raise ValueError('寄存器值范围 0～65535')
        with self.lock:
            bank = self.inputs if function == 4 else self.holding
            bank[address:address + len(values)] = values

    def reply(self, pdu):
        function = pdu[0]
        def error(code):
            return bytes([function | 0x80, code])
        if function not in (3, 4, 6, 16):
            return error(1)
        if len(pdu) < 5:
            return error(3)
        address, number = struct.unpack('!HH', pdu[1:5])
        if function == 6:
            if len(pdu) != 5:
                return error(3)
            self.edit(3, address, [number])
            return pdu
        if not 1 <= number <= (123 if function == 16 else 125):
            return error(3)
        if address + number > 65536:
            return error(2)
        if function in (3, 4):
            if len(pdu) != 5:
                return error(3)
            values = self.snapshot(function, address, number)
            return bytes([function, number * 2]) + struct.pack('!{}H'.format(number), *values)
        if len(pdu) != 6 + number * 2 or pdu[5] != number * 2:
            return error(3)
        self.edit(3, address, struct.unpack('!{}H'.format(number), pdu[6:]))
        return pdu[:5]


class Server:
    def __init__(self, ctx, host, port, unit=1, bank=None, log=lambda message: None):
        if not 0 <= port <= 65535 or not 0 <= unit <= 255:
            raise ValueError('端口或站号越界')
        self.ctx, self.host, self.port, self.unit = ctx, host, port, unit
        self.bank, self.log = bank or RegisterBank(), log
        self.stopped = threading.Event()
        self.lock = threading.Lock()
        self.connections = set()
        self.workers = set()
        self.listener = None

    def start(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self.host, self.port))
            listener.listen(16)
            listener.settimeout(0.3)
        except BaseException:
            listener.close()
            raise
        self.listener = listener
        self.port = listener.getsockname()[1]
        self.thread = threading.Thread(target=self._accept, daemon=True)
        self.thread.start()
        self.log('TLS 服务端监听 {}:{}，站号 {}'.format(self.host, self.port, self.unit))

    def _accept(self):
        while not self.stopped.is_set():
            try:
                raw, address = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with self.lock:
                if self.stopped.is_set() or len(self.connections) >= 32:
                    raw.close()
                    continue
                raw.settimeout(5)
                self.connections.add(raw)
                worker = threading.Thread(target=self._serve, args=(raw, address), daemon=True)
                self.workers.add(worker)
                worker.start()

    def _serve(self, raw, address):
        conn = raw
        try:
            # Do not hold the lock during the TLS handshake.
            conn = self.ctx.wrap_socket(raw, server_side=True, do_handshake_on_connect=False)
            with self.lock:
                self.connections.discard(raw)
                self.connections.add(conn)
                if self.stopped.is_set():
                    return
            conn.do_handshake()
            self.log('{} 已连接：{} / {}'.format(address, conn.version(), conn.cipher()[0]))
            while not self.stopped.is_set():
                tid, unit, pdu = receive(conn, trace=lambda frame: self.log(
                    format_frame('RX', frame, '服务端 ← {}:{}'.format(*address), request=True)))
                if unit != self.unit:
                    self.log('忽略非本站请求：{}'.format(unit))
                    continue
                response = self.bank.reply(pdu)
                send(conn, tid, unit, response, trace=lambda frame: self.log(
                    format_frame('TX', frame, '服务端 → {}:{}'.format(*address), request=False)))
        except (OSError, ValueError, EOFError) as exc:
            if not self.stopped.is_set():
                self.log('{} 连接结束/拒绝：{}'.format(address, exc))
        finally:
            conn.close()
            raw.close()
            with self.lock:
                self.connections.discard(conn)
                self.connections.discard(raw)
                self.workers.discard(threading.current_thread())

    def stop(self):
        self.stopped.set()
        if self.listener:
            self.listener.close()
        with self.lock:
            for conn in self.connections:
                try:
                    conn.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                conn.close()
            workers = list(self.workers)
        if hasattr(self, 'thread'):
            self.thread.join(1)
        for worker in workers:
            worker.join(0.2)
        self.log('服务端已停止')
