"""Optional real-browser checks: requires Playwright and installed Chromium."""
import importlib.util
import io
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
import zipfile

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from .app import initialize_admin


@unittest.skipUnless(importlib.util.find_spec('playwright'), 'optional Playwright is not installed')
class BrowserTests(unittest.TestCase):
    def test_web_sign_download_and_revoke(self):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory(prefix='ca-web-test-') as temporary:
            folder = Path(temporary)
            data = folder/'data'
            initialize_admin(data, 'browser-admin-password')
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1', 0))
                port = reservation.getsockname()[1]
            root = Path(__file__).resolve().parents[2]
            process = subprocess.Popen([sys.executable, str(root/'ca_server.py'), '--data-dir', str(data), 'serve', '--port', str(port)],
                                       cwd=str(root), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                base = 'http://127.0.0.1:'+str(port)
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                last_error = ''
                for _ in range(30):
                    if process.poll() is not None:
                        self.fail(process.stderr.read().decode())
                    try:
                        with opener.open(base, timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError as exc:
                        last_error = str(exc)
                        time.sleep(.1)
                else:
                    self.fail('CA server did not start: '+last_error)
                # A second CLI instance cannot own the same CA directory.
                duplicate = subprocess.run([sys.executable, str(root/'ca_server.py'), '--data-dir', str(data), 'serve', '--port', str(port)],
                                           capture_output=True, timeout=5)
                self.assertNotEqual(duplicate.returncode, 0)
                self.assertIn('已经有 CA 服务运行', duplicate.stderr.decode())
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True, args=['--no-sandbox'],
                                                         executable_path=os.environ.get('CA_TEST_BROWSER'))
                    try:
                        page = browser.new_page(viewport={'width':1440, 'height':1000}, accept_downloads=True)
                        errors = []
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.goto(base)
                        page.locator('#login-form [name=password]').fill('browser-admin-password')
                        page.locator('#login-form button').click()
                        page.locator('#workspace').wait_for(state='visible')
                        ca_form = page.locator('#ca-form')
                        ca_form.locator('[name=cn]').fill('Browser Root CA')
                        ca_form.locator('[name=password]').fill('browser-ca-password')
                        ca_form.locator('[name=password_confirm]').fill('browser-ca-password')
                        ca_form.locator('button').click()
                        page.locator('#initialize-panel').wait_for(state='hidden')
                        page.locator('#unlock-form [name=password]').fill('browser-ca-password')
                        page.locator('#unlock-form button').click()
                        page.wait_for_function("() => document.querySelector('#lock-state').textContent === '已解锁'")
                        device = page.locator('#device-form')
                        self.assertTrue(device.locator('[name=algorithm]').is_disabled())
                        device.locator('button').click()
                        page.wait_for_function("() => document.querySelectorAll('#devices tr td button').length >= 4")
                        goose_row = page.locator('#devices tr').filter(has_text='LC400-001-goose')
                        with page.expect_download() as download:
                            goose_row.get_by_role('button', name='证书', exact=True).click()
                        downloaded_cert = x509.load_pem_x509_certificate(Path(download.value.path()).read_bytes())
                        goose_row.get_by_role('button', name='私钥与完整包', exact=True).click()
                        page.locator('#export-dialog').wait_for(state='visible')
                        self.assertEqual(page.locator('#export-form [name=key_format]').input_value(), 'plain')
                        with page.expect_download() as download:
                            page.locator('#export-form button.primary').click()
                        archive = zipfile.ZipFile(io.BytesIO(Path(download.value.path()).read_bytes()))
                        self.assertEqual(len(archive.namelist()), 5)
                        serialization.load_pem_private_key(archive.read('enc.key'), None)
                        self.assertEqual(archive.read('enc.crt'), downloaded_cert.public_bytes(serialization.Encoding.PEM))
                        device.locator('[name=profile]').select_option('tls_server')
                        device.locator('[name=algorithm]').select_option('RSA')
                        device.locator('[name=rsa_bits]').select_option('2048')
                        device.locator('[name=cn]').fill('LC400-001-server')
                        device.locator('[name=ip_addresses]').fill('192.168.3.100')
                        device.locator('button').click()
                        tls_row = page.locator('#devices tr').filter(has_text='LC400-001-server')
                        tls_row.wait_for(state='visible')
                        tls_row.get_by_role('button', name='私钥与完整包', exact=True).click()
                        page.locator('#export-form [name=export_password]').fill('browser-export-password')
                        page.locator('#export-form [name=export_password_confirm]').fill('browser-export-password')
                        with page.expect_download() as download:
                            page.locator('#export-form button.primary').click()
                        archive = zipfile.ZipFile(io.BytesIO(Path(download.value.path()).read_bytes()))
                        key = serialization.load_pem_private_key(archive.read('enc.key'), b'browser-export-password')
                        self.assertEqual(key.key_size, 2048)
                        def accept(dialog):
                            dialog.accept('key_compromise' if dialog.type == 'prompt' else None)
                        page.on('dialog', accept)
                        goose_row.get_by_role('button', name='吊销', exact=True).click()
                        page.wait_for_function("() => document.querySelector('#devices').textContent.includes('已吊销')")
                        with page.expect_download() as download:
                            page.locator('#download-crl').click()
                        crl = x509.load_pem_x509_crl(Path(download.value.path()).read_bytes())
                        self.assertIsNotNone(crl.get_revoked_certificate_by_serial_number(downloaded_cert.serial_number))
                        page.locator('#lock-ca').click()
                        page.wait_for_function("() => document.querySelector('#lock-state').textContent === '已锁定'")
                        page.wait_for_function("() => !busy")
                        self.assertTrue(page.locator('#issue-button').is_disabled())
                        self.assertTrue(page.locator('#lock-ca').is_disabled())
                        page.screenshot(path='/tmp/lc400-ca-server-web.png', full_page=True)
                        page.set_viewport_size({'width':390, 'height':844})
                        self.assertTrue(page.evaluate('() => document.documentElement.scrollWidth <= window.innerWidth'))
                        self.assertEqual(errors, [])
                    finally:
                        browser.close()
            finally:
                process.terminate()
                process.wait(timeout=10)
                process.stderr.close()


if __name__ == '__main__':
    unittest.main()
