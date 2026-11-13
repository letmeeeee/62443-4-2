"""Protocol and real loopback TLS tests; no display or device required."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import socket
import ssl
import struct
import tempfile
import time
import threading
import unittest
from unittest.mock import patch

from .certificates import export_certificate, generate_demo, generate_device, inspect
from .core import RegisterBank, Server, TLSClient, exchange, format_frame, receive, request_pdu, send, tls_context


class ProtocolTests(unittest.TestCase):
    def test_trace_preserves_wire_bytes_and_received_invalid_header(self):
        sent, received = [], []
        left, right = socket.socketpair()
        frame = bytes.fromhex('12 34 00 00 00 06 07 03 00 10 00 02')
        with left, right:
            send(left, 0x1234, 7, frame[7:], trace=sent.append)
            self.assertEqual(receive(right, trace=received.append), (0x1234, 7, frame[7:]))
            bad_header = bytes.fromhex('12 34 00 01 00 06 07')
            left.sendall(bad_header)
            with self.assertRaises(ValueError):
                receive(right, trace=received.append)
        self.assertEqual(sent, [frame])
        self.assertEqual(received, [frame, bad_header])
        text = format_frame('TX', frame, '客户端 → 127.0.0.1:18020')
        self.assertIn('ADU: 12 34 00 00 00 06 07 03 00 10 00 02', text)
        self.assertIn('事务号=4660', text)
        self.assertIn('起始地址=16 数量=2', text)
        maximum = struct.pack('!HHHB', 1, 0, 253, 1) + bytes([3, 250]) + b'\xff\xff' * 125
        self.assertIn(maximum.hex(' ').upper(), format_frame('RX', maximum, request=False))
        self.assertIn('异常码=0x02 非法数据地址', format_frame('RX', bytes.fromhex('00 01 00 00 00 03 01 83 02'), request=False))

    def test_register_read_write_and_boundaries(self):
        bank = RegisterBank()
        for function, address, data in [(6, 65535, [65535]), (16, 20, [0, 123, 65535])]:
            pdu = request_pdu(function, address, values=data)
            self.assertEqual(bank.reply(pdu), pdu if function == 6 else pdu[:5])
            self.assertEqual(bank.snapshot(3, address, len(data)), data)
        bank.edit(4, 0, [42])
        self.assertEqual(bank.reply(request_pdu(4, 0)), b'\x04\x02\x00\x2a')
        self.assertEqual(bank.snapshot(3, 0, 1), [0])

    def test_invalid_requests_return_modbus_exceptions(self):
        bank = RegisterBank()
        for request, response in [
            (b'\x01', b'\x81\x01'),
            (b'\x03', b'\x83\x03'),
            (struct.pack('!BHH', 3, 0, 0), b'\x83\x03'),
            (struct.pack('!BHH', 3, 65535, 2), b'\x83\x02'),
            (struct.pack('!BHH', 4, 0, 126), b'\x84\x03'),
            (b'\x10\x00\x00\x00\x02\x02\x00\x01', b'\x90\x03'),
            (b'\x06\x00\x00\x00\x01\x00', b'\x86\x03'),
        ]:
            with self.subTest(request=request):
                self.assertEqual(bank.reply(request), response)
        self.assertEqual(bank.snapshot(3, 0, 2), [0, 0])

    def test_client_rejects_invalid_ranges(self):
        for function, address, count, data in [(3, 65535, 2, []), (3, 0, 126, []),
                                              (6, 0, 1, [1, 2]), (16, 0, 1, []),
                                              (16, 0, 1, [-1]), (16, 0, 1, [65536])]:
            with self.assertRaises(ValueError):
                request_pdu(function, address, count, data)

    def test_framing_fragmentation_and_multiple_messages(self):
        left, right = socket.socketpair()
        with left, right:
            frame = struct.pack('!HHHB', 10, 0, 6, 1) + b'\x03\x00\x00\x00\x01'
            for octet in frame:
                left.sendall(bytes([octet]))
            send(left, 11, 1, b'\x06\x00\x00\x00\x42')
            self.assertEqual(receive(right), (10, 1, frame[7:]))
            self.assertEqual(receive(right)[0], 11)
        for protocol, length in [(1, 6), (0, 1), (0, 255)]:
            left, right = socket.socketpair()
            with left, right:
                left.sendall(struct.pack('!HHHB', 1, protocol, length, 1))
                with self.assertRaises(ValueError):
                    receive(right)


class TLSTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = generate_demo(cls.temp.name)
        cls.foreign = generate_demo(cls.temp.name)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def context(self, server=False, mutual=True, folder=None):
        folder = folder or self.folder
        role = 'server' if server else 'client'
        return tls_context(server, str(folder / (role + '.crt')), str(folder / (role + '.key')),
                           str(folder / 'ca.crt'), mutual)

    def setUp(self):
        self.logs = []
        self.server = Server(self.context(True), '127.0.0.1', 0, log=self.logs.append)
        self.server.start()

    def tearDown(self):
        self.server.stop()

    def call(self, function=3, address=0, count=1, values=(), ctx=None, **kwargs):
        return exchange(ctx or self.context(), '127.0.0.1', self.server.port, 1,
                        function, address, count, values, timeout=2, **kwargs)

    def test_packaged_runtime_persistent_connection(self):
        import os
        import subprocess
        executable = os.environ.get('LC400_MODBUS_TEST_EXECUTABLE')
        if not executable:self.skipTest('set LC400_MODBUS_TEST_EXECUTABLE')
        base = Path(executable).resolve().parent
        site = next((base/'runtime/lib').glob('python*/site-packages'))
        env = dict(os.environ, PYTHONHOME=str(base/'runtime'),
            PYTHONPATH=str(base/'app')+os.pathsep+str(site), LD_LIBRARY_PATH=str(base/'runtime/lib'),
            PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1')
        script = ("import sys;from tools.modbus_gui.core import TLSClient,tls_context;"
            "c=TLSClient(tls_context(False,sys.argv[1],sys.argv[2],sys.argv[3]),'127.0.0.1',int(sys.argv[4]));"
            "assert c.request(1,3,0)==[0];assert c.request(1,4,0)==[0];"
            "assert c.transaction==2;c.close()")
        result = subprocess.run([str(base/'runtime/bin/python3'), '-c', script,
            str(self.folder/'client.crt'), str(self.folder/'client.key'), str(self.folder/'ca.crt'),
            str(self.server.port)], cwd=self.temp.name, env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sum('已连接' in line for line in self.logs), 1)

    def test_persistent_requests_use_one_tls_handshake(self):
        client = TLSClient(self.context(), '127.0.0.1', self.server.port, timeout=2)
        try:
            self.assertEqual(client.request(1, 6, 0, values=[321]), [321])
            self.assertEqual(client.request(1, 3, 0), [321])
            self.assertEqual(client.request(1, 4, 0), [0])
            self.assertEqual(client.transaction, 3)
        finally:
            client.close()
        self.assertEqual(sum('已连接' in line for line in self.logs), 1)
        self.assertTrue(any('事务号=3 ' in line for line in self.logs))

    def test_close_notify_and_bounded_missing_peer_reply(self):
        for reply_close in (True, False):
            with self.subTest(reply_close=reply_close):
                listener = socket.socket()
                listener.bind(('127.0.0.1', 0)); listener.listen(1); listener.settimeout(3)
                port = listener.getsockname()[1]
                release = threading.Event(); errors = []; clean_eof = []
                def peer():
                    try:
                        raw, _ = listener.accept()
                        with self.context(True).wrap_socket(raw, server_side=True, suppress_ragged_eofs=False) as conn:
                            tid, unit, pdu = receive(conn)
                            send(conn, tid, unit, bytes.fromhex('03 02 00 2A'))
                            # A bare TCP close raises SSLEOFError with suppression disabled.
                            clean_eof.append(conn.recv(1) == b'')
                            if reply_close:
                                conn.unwrap().close()
                            else:
                                release.wait(3)
                    except BaseException as exc:
                        errors.append(exc)
                worker = threading.Thread(target=peer); worker.start()
                try:
                    begin = time.monotonic()
                    self.assertEqual(exchange(self.context(), '127.0.0.1', port, 1, 3, 0, timeout=.5), [42])
                    self.assertLess(time.monotonic()-begin, 2)
                finally:
                    release.set(); worker.join(4); listener.close()
                self.assertFalse(worker.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual(clean_eof, [True])

    def test_failed_write_is_not_replayed_and_next_request_reconnects(self):
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0)); listener.listen(2); listener.settimeout(3)
        port = listener.getsockname()[1]
        requests = []; errors = []
        def peer():
            try:
                for index in range(2):
                    raw, _ = listener.accept()
                    with self.context(True).wrap_socket(raw, server_side=True) as conn:
                        tid, unit, pdu = receive(conn); requests.append(pdu)
                        if index == 0:
                            continue  # Write may have executed, but its response is lost.
                        send(conn, tid, unit, pdu)
                        if conn.recv(1) == b'':conn.unwrap().close()
            except BaseException as exc:
                errors.append(exc)
        worker = threading.Thread(target=peer); worker.start()
        client = TLSClient(self.context(), '127.0.0.1', port, timeout=.5)
        try:
            with self.assertRaises((OSError, EOFError)):
                client.request(1, 6, 0, values=[123])
            self.assertEqual(len(requests), 1)
            self.assertIsNone(client.conn)
            self.assertEqual(client.request(1, 6, 0, values=[456]), [456])
        finally:
            client.close(); worker.join(4); listener.close()
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(requests), 2)

    def test_mutual_tls_read_write_and_input_register(self):
        self.assertEqual(self.call(16, 5, values=[123, 456]), [123, 456])
        self.assertEqual(self.call(3, 5, 2), [123, 456])
        self.call(6, 65535, values=[0xABCD])
        self.assertEqual(self.call(3, 65535), [0xABCD])
        self.server.bank.edit(4, 5, [77])
        self.assertEqual(self.call(4, 5), [77])

    def test_both_peers_log_complete_requests_and_responses(self):
        client_logs = []
        self.assertEqual(self.call(3, 0, 2, log=client_logs.append), [0, 0])
        # The response can arrive before the server's send callback has run.
        deadline = time.monotonic() + 2
        while not any('TX 服务端' in line for line in self.logs) and time.monotonic() < deadline:
            time.sleep(0.01)
        for logs in (client_logs, self.logs):
            text = '\n'.join(logs)
            self.assertIn('ADU: 00 01 00 00 00 06 01 03 00 00 00 02', text)
            self.assertIn('ADU: 00 01 00 00 00 07 01 03 04 00 00 00 00', text)
            self.assertIn('MBAP:', text)
            self.assertIn('寄存器值=[0, 0]', text)

    def test_missing_client_certificate_is_rejected(self):
        ctx = tls_context(False, ca=str(self.folder / 'ca.crt'), mutual=False)
        with self.assertRaises((OSError, EOFError)):
            self.call(ctx=ctx)

    def test_wrong_ca_and_server_name_are_rejected(self):
        with self.assertRaises(ssl.SSLCertVerificationError):
            self.call(ctx=self.context(folder=self.foreign))
        with self.assertRaises(ssl.SSLCertVerificationError):
            self.call(server_name='wrong.example')

    def test_skip_server_verification_still_sends_client_identity(self):
        logs = []
        ctx = tls_context(False, str(self.folder / 'client.crt'), str(self.folder / 'client.key'),
                          ca='/missing-ca.crt', verify_peer=False)
        self.assertEqual(self.call(ctx=ctx, server_name='wrong.example', log=logs.append), [0])
        self.assertIn('未验证服务端证书及名称', '\n'.join(logs))
        self.assertNotIn('服务端身份验证通过', '\n'.join(logs))
        # Disabling server verification must not bypass the peer's client checks.
        untrusted = tls_context(False, str(self.foreign / 'client.crt'), str(self.foreign / 'client.key'), verify_peer=False)
        with self.assertRaises((OSError, EOFError)):
            self.call(ctx=untrusted)

    def test_tls_without_verifying_either_peer(self):
        self.server.stop()
        self.server = Server(self.context(True, mutual=False), '127.0.0.1', 0)
        self.server.start()
        ctx = tls_context(False, mutual=False, verify_peer=False)
        self.assertEqual(self.call(ctx=ctx), [0])

    def test_untrusted_client_certificate_is_rejected(self):
        ctx = tls_context(False, str(self.foreign / 'client.crt'), str(self.foreign / 'client.key'), str(self.folder / 'ca.crt'))
        with self.assertRaises((OSError, EOFError)):
            self.call(ctx=ctx)

    def test_server_authentication_only(self):
        self.server.stop()
        self.server = Server(self.context(True, mutual=False), '127.0.0.1', 0)
        self.server.start()
        self.assertEqual(self.call(ctx=tls_context(False, ca=str(self.folder / 'ca.crt'), mutual=False)), [0])

    def test_concurrent_clients(self):
        def request(index):
            self.call(6, index, values=[index + 100])
            return self.call(3, index)
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(list(pool.map(request, range(8))), [[i + 100] for i in range(8)])

    def test_stop_closes_stalled_handshake_and_releases_port(self):
        stalled = socket.create_connection(('127.0.0.1', self.server.port), timeout=2)
        try:
            time.sleep(0.05)
            started = time.monotonic()
            port = self.server.port
            self.server.stop()
            self.assertLess(time.monotonic() - started, 2)
            replacement = Server(self.context(True), '127.0.0.1', port)
            replacement.start()
            replacement.stop()
        finally:
            stalled.close()

    def test_certificate_export_and_import(self):
        destination = Path(self.temp.name) / 'exported.crt'
        export_certificate(self.folder / 'ca.crt', destination)
        self.assertEqual(destination.read_bytes(), (self.folder / 'ca.crt').read_bytes())
        ctx = tls_context(False, str(self.folder / 'client.crt'), str(self.folder / 'client.key'), str(destination))
        self.assertEqual(self.call(ctx=ctx), [0])
        self.assertIn('SHA256', inspect(self.folder / 'server.crt'))
        with self.assertRaises(ValueError):
            export_certificate(self.folder / 'client.key', destination)
        with self.assertRaises(ssl.SSLError):
            tls_context(False, str(self.folder / 'client.crt'), str(self.foreign / 'client.key'), str(destination))

    def test_legacy_self_signed_trust_add_is_rejected_by_current_manager(self):
        import subprocess
        import sys
        folder = generate_device(self.temp.name)
        manager = Path(__file__).resolve().parents[2] / 'exec/app/script/modbus_certs.py'
        trust_dir = Path(self.temp.name) / 'device-trust'
        result = subprocess.run([sys.executable, str(manager), '--dir', str(trust_dir),
                                 'trust-add', '--cert', str(folder / 'client.crt')],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('invalid choice', result.stderr.decode())

    def test_windows_certificate_backend_without_openssl_executable(self):
        import subprocess
        import sys
        for device in (True, False):
            with self.subTest(device=device):
                # Exercise Windows dispatch and ensure generation/inspection never spawn OpenSSL.
                with patch('tools.modbus_gui.certificates.sys.platform', 'win32'), \
                        patch('tools.modbus_gui.certificates.subprocess.run', side_effect=AssertionError('external OpenSSL')):
                    folder = generate_device(self.temp.name) if device else generate_demo(self.temp.name)
                    self.assertIn('SHA256=', inspect(folder / 'server.crt'))
                if device:
                    manager = Path(__file__).resolve().parents[2] / 'exec/app/script/modbus_certs.py'
                    result = subprocess.run([sys.executable, str(manager), '--dir', str(folder / 'trust'),
                                             'trust-add', '--cert', str(folder / 'client.crt')],
                                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
                    self.assertNotEqual(result.returncode, 0)
                server_trust = folder / ('client.crt' if device else 'ca.crt')
                client_trust = folder / ('server.crt' if device else 'ca.crt')
                server = Server(tls_context(True, str(folder / 'server.crt'), str(folder / 'server.key'), str(server_trust)),
                                '127.0.0.1', 0)
                server.start()
                try:
                    client = tls_context(False, str(folder / 'client.crt'), str(folder / 'client.key'), str(client_trust))
                    self.assertEqual(exchange(client, '127.0.0.1', server.port, 1, 3, 0), [0])
                finally:
                    server.stop()


if __name__ == '__main__':
    unittest.main()
