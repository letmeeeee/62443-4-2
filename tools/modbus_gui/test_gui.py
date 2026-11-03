"""Hidden-window GUI integration test. Requires a working graphical display."""
import tempfile
import time
from datetime import datetime
import tkinter as tk
import unittest
from unittest.mock import patch

from .gui import Window


class GUITests(unittest.TestCase):
    def test_certificate_generation_server_client_and_restart(self):
        root = tk.Tk()
        root.withdraw()
        window = Window(root)
        errors = []
        def wait_until(predicate):
            deadline = time.monotonic() + 15
            while not predicate():
                root.update()
                if time.monotonic() > deadline:
                    self.fail('GUI 操作超时；错误：' + repr(errors))
                time.sleep(0.01)
            root.update()
        try:
            with tempfile.TemporaryDirectory() as parent, \
                    patch('tools.modbus_gui.gui.filedialog.askdirectory', return_value=parent), \
                    patch('tools.modbus_gui.gui.messagebox.showinfo'), \
                    patch('tools.modbus_gui.gui.messagebox.showerror', side_effect=lambda *args: errors.append(args)):
                window.generate(window.send_button)
                wait_until(lambda: bool(window.fields['client']['cert'].get()))
                # Choose an available temporary port for the actual GUI controls.
                import socket
                with socket.socket() as probe:
                    probe.bind(('127.0.0.1', 0))
                    port = probe.getsockname()[1]
                for role in ('client', 'server'):
                    window.fields[role]['port'].set(str(port))
                window.start_server()
                wait_until(lambda: window.server is not None)
                window.fields['server']['values'].set('123, 456')
                window.edit_bank()
                window.fields['client']['count'].set('2')
                window.read_or_send('client')
                wait_until(lambda: '0=123' in window.fields['client']['result'].get())
                self.assertTrue(window.fields['client']['verify_peer'].get())
                window.fields['client']['verify_peer'].set(False)
                window.fields['client']['ca'].set('/missing-ca.crt')
                window.fields['client']['server_name'].set('wrong.example')
                window.fields['client']['function'].set('16 写多个保持寄存器')
                window.fields['client']['values'].set('789, 65535')
                window.read_or_send('client')
                wait_until(lambda: '0=789' in window.fields['client']['result'].get())
                self.assertEqual(window.bank.snapshot(3, 0, 2), [789, 65535])
                window.fields['client']['function'].set('03 保持寄存器')
                window.loop_interval.set('50')
                window.start_loop()
                window.start_loop()  # A second click must not start another worker.
                wait_until(lambda: window.loop_success >= 3)
                self.assertTrue(window.loop_running)
                self.assertIn('disabled', window.send_button.state())
                window.stop_loop()
                wait_until(lambda: not window.client_busy)
                stopped_count = window.loop_count
                deadline = time.monotonic() + 0.2
                while time.monotonic() < deadline:
                    root.update()
                    time.sleep(0.01)
                self.assertEqual(window.loop_count, stopped_count)
                self.assertIsNone(window.loop_timer)
                self.assertEqual(window.loop_failure, 0)
                self.assertNotIn('disabled', window.send_button.state())
                with patch('tools.modbus_gui.gui.datetime') as clock:
                    clock.now.return_value = datetime(2026, 10, 19, 15, 51, 20, 691000)
                    window.log('时间戳测试')
                wait_until(lambda: '2026-10-19 15:51:20.691 时间戳测试' in window.logbox.get('1.0', 'end'))
                window.stop_server()
                wait_until(lambda: window.server is None)
                # Network failures are counted and logged without repeated dialogs.
                window.start_loop()
                wait_until(lambda: window.loop_failure >= 2)
                window.stop_loop()
                wait_until(lambda: not window.client_busy)
                self.assertEqual(window.loop_success, 0)
                log_text = window.logbox.get('1.0', 'end')
                self.assertRegex(log_text, r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} TX 客户端')
                self.assertIn('ADU: 00 01 00 00 00 06 01 03 00 00 00 02', log_text)
                self.assertIn('ADU: 00 01 00 00 00 07 01 03 04 00 7B 01 C8', log_text)
                self.assertIn('TX 客户端', log_text)
                self.assertIn('RX 服务端', log_text)
                self.assertIn('未验证服务端证书及名称', log_text)
                self.assertTrue(window.logbox.tag_ranges('TX'))
                self.assertTrue(window.logbox.tag_ranges('RX'))
                self.assertEqual(int(window.split.panecget(window.logbox.frame.master, 'minsize')), 180)
                # Exercise copy without replacing the user's actual clipboard.
                with patch.object(root, 'clipboard_clear') as clear, patch.object(root, 'clipboard_append') as append:
                    window.logbox.tag_add('sel', '1.0', '1.8')
                    selected = window.logbox.get('sel.first', 'sel.last')
                    window.logbox.event_generate('<<Copy>>')
                    clear.assert_called_once()
                    append.assert_called_once_with(selected)
                    window.select_log()
                    self.assertEqual(window.logbox.get('sel.first', 'sel.last'), window.logbox.get('1.0', 'end-1c'))
                    window.copy_log(all_text=True)
                    append.assert_called_with(window.logbox.get('1.0', 'end-1c'))
                    window.logbox.tag_remove('sel', '1.0', 'end')
                    append.reset_mock()
                    window.copy_log()
                    append.assert_not_called()
                self.assertEqual(str(window.logbox.cget('state')), 'disabled')
                self.assertIn('disabled', window.stop_button.state())
                window.start_server()
                wait_until(lambda: window.server is not None)
                window.stop_server()
                wait_until(lambda: window.server is None)
                self.assertEqual(errors, [])
        finally:
            window.close()


if __name__ == '__main__':
    unittest.main()
