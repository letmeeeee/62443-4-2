"""Real OpenSSL/file rotation checks; no device, TEE, Flask or MySQL required."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'script' / 'rotate_identity_key.sh'


def openssl(*args):
    return subprocess.run(['openssl', *map(str, args)], capture_output=True,
                          check=True, timeout=60).stdout


class RotationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_key = openssl('genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:3072')

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='identity-rotation-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.directory = self.root / 'identities'
        self.directory.mkdir(mode=0o700)
        self.config = self.root / 'device.ini'
        self.config.write_text('[TLS]\nca_file=' + str(self.root / 'trust/roots.crt') +
                               '\n[HTTPS]\ndevice_ips=192.0.2.10\n')
        self.env = dict(os.environ, MODBUS_KEY_BACKEND='file')

    def seed(self, stem):
        key = self.directory / (stem + '.key')
        key.write_bytes(self.original_key)
        key.chmod(0o600)
        openssl('req', '-new', '-key', key, '-subj', '/CN=original-device',
                '-addext', 'subjectAltName=IP:192.0.2.1,DNS:old.example',
                '-out', self.directory / (stem + '.csr'))
        openssl('req', '-x509', '-key', key, '-subj', '/CN=original-device', '-days', '1',
                '-out', self.directory / (stem + '.crt'))
        return {stem + suffix: (self.directory / (stem + suffix)).read_bytes()
                for suffix in ('.key', '.csr', '.crt')}

    def rotate(self, target, *args, success=True, confirm=True):
        command = ['sh', str(SCRIPT), target, '--dir', str(self.directory),
                   '--config', str(self.config), *args]
        if confirm:
            command += ['--confirm', 'ROTATE_IDENTITY_KEY']
        result = subprocess.run(command, env=self.env, capture_output=True, timeout=90)
        self.assertEqual(result.returncode == 0, success, result.stderr.decode())
        self.assertNotIn(b'BEGIN PRIVATE KEY', result.stdout + result.stderr)
        return result

    def test_each_identity_gets_new_key_matching_csr_and_archives_old_certificate(self):
        for target, stem in [('master', 'master'), ('slave', 'slave'), ('https', 'g3')]:
            with self.subTest(target=target):
                old = self.seed(stem)
                unrelated = self.directory / 'other-identity.key'
                unrelated.write_bytes(b'unrelated')
                self.rotate(target)
                key, csr = self.directory / (stem + '.key'), self.directory / (stem + '.csr')
                self.assertNotEqual(key.read_bytes(), self.original_key)
                self.assertFalse((self.directory / (stem + '.crt')).exists())
                openssl('req', '-in', csr, '-verify', '-noout')
                self.assertEqual(openssl('pkey', '-in', key, '-pubout'),
                                 openssl('req', '-in', csr, '-pubkey', '-noout'))
                text = openssl('req', '-in', csr, '-text', '-noout')
                self.assertIn(b'3072 bit', text)
                self.assertIn(b'TLS Web Client Authentication' if target == 'master'
                              else b'TLS Web Server Authentication', text)
                self.assertIn(b'192.0.2.10' if target == 'https' else b'old.example', text)
                self.assertEqual(key.stat().st_mode & 0o777, 0o600)
                self.assertEqual(csr.stat().st_mode & 0o777, 0o644)
                backup, = (self.directory / 'backups').glob(stem + '-rotation-*')
                self.assertEqual(backup.stat().st_mode & 0o777, 0o700)
                for name in (stem + '.key', stem + '.csr', stem + '.crt'):
                    self.assertEqual((backup / name).read_bytes(), old[name])
                    self.assertEqual((backup / name).stat().st_mode & 0o777, 0o600)
                self.assertEqual(unrelated.read_bytes(), b'unrelated')
                self.assertFalse((self.directory / ('.' + stem + '-rotation-incomplete.json')).exists())

    def test_rejected_requests_leave_identity_unchanged(self):
        old = self.seed('master')
        for args, confirm in [((), False), (('--backend', 'tee'), True),
                              (('--name', 'invalid/name'), True), (('--dns', 'bad/name'), True)]:
            with self.subTest(args=args):
                self.rotate('master', *args, success=False, confirm=confirm)
                for name, data in old.items():
                    self.assertEqual((self.directory / name).read_bytes(), data)
                self.assertFalse((self.directory / 'backups').exists())

    def test_https_ignores_modbus_tee_backend_and_clears_stale_reload_state(self):
        self.seed('g3')
        self.env['MODBUS_KEY_BACKEND'] = 'tee'
        for name in ('.reload-required', 'renewal-status.json'):
            (self.directory / name).write_bytes(b'old-state')
        self.rotate('https')
        backup, = (self.directory / 'backups').glob('g3-rotation-*')
        for name in ('.reload-required', 'renewal-status.json'):
            self.assertFalse((self.directory / name).exists())
            self.assertEqual((backup / name).read_bytes(), b'old-state')

    def test_explicit_sans_replace_old_sans(self):
        self.seed('slave')
        self.rotate('slave', '--name', 'new-slave', '--ip', '192.0.2.30')
        text = openssl('req', '-in', self.directory / 'slave.csr', '-text', '-noout')
        self.assertIn(b'new-slave', text)
        self.assertIn(b'192.0.2.30', text)
        self.assertNotIn(b'old.example', text)

    def test_https_generation_failure_keeps_original_files(self):
        old = self.seed('g3')
        self.config.write_text('[HTTPS]\ndevice_ips=invalid\n')
        self.rotate('https', success=False)
        for name, data in old.items():
            self.assertEqual((self.directory / name).read_bytes(), data)
        self.assertFalse((self.directory / 'backups').exists())

    def test_symlink_and_incomplete_rotation_are_rejected(self):
        old = self.seed('master')
        marker = self.directory / '.master-rotation-incomplete.json'
        marker.write_text(json.dumps({'backup': 'previous'}))
        self.rotate('master', success=False)
        marker.unlink()
        key = self.directory / 'master.key'
        key.unlink()
        outside = self.root / 'outside.key'
        outside.write_bytes(self.original_key)
        key.symlink_to(outside)
        self.rotate('master', success=False)
        self.assertEqual(outside.read_bytes(), self.original_key)
        self.assertEqual((self.directory / 'master.crt').read_bytes(), old['master.crt'])

    def test_publication_failure_restores_original_identity(self):
        old = self.seed('master')
        # 在安装 CSR 时模拟一次磁盘写入错误，此时密钥已经替换、旧证书已经撤下。
        injection = self.root / 'injection'
        injection.mkdir()
        (injection / 'sitecustomize.py').write_text(
            'import os\n'
            'original_replace = os.replace\n'
            'failed = False\n'
            'def replace(source, destination, *args, **kwargs):\n'
            '    global failed\n'
            '    if not failed and str(destination) == os.environ["ROTATION_TEST_FAIL_DEST"]:\n'
            '        failed = True\n'
            '        raise OSError("simulated disk error")\n'
            '    return original_replace(source, destination, *args, **kwargs)\n'
            'os.replace = replace\n'
        )
        self.env.update(PYTHONPATH=str(injection),
                        ROTATION_TEST_FAIL_DEST=str(self.directory / 'master.csr'))
        self.rotate('master', success=False)
        for name, data in old.items():
            self.assertEqual((self.directory / name).read_bytes(), data)
        self.assertFalse((self.directory / '.master-rotation-incomplete.json').exists())

    @unittest.skipUnless(shutil.which('cc'), 'C compiler required for existing Modbus tool integration')
    def test_rotated_csrs_can_be_signed_and_imported_by_existing_tools(self):
        from pki_test_helpers import make_ca, sign_csr

        root = SCRIPT.parents[3]
        binary = self.root / 'modbus-identity'
        subprocess.run([
            'cc', '-std=c99', '-Wno-deprecated-declarations', '-DMODBUS_WITH_TEE=0',
            '-I' + str(root / 'logger/lib'), str(root / 'logger/scripts/modbus_tee_identity.c'),
            str(root / 'logger/lib/modbus_identity.c'), '-lcrypto', '-lpthread', '-o', str(binary),
        ], capture_output=True, check=True, timeout=60)
        ca = make_ca(self.root / 'offline-ca')
        trust = self.root / 'trust'
        trust.mkdir()
        (trust / 'roots.crt').write_bytes(ca['root'].read_bytes())
        self.env['MODBUS_TEE_IDENTITY'] = str(binary)
        for target, stem in [('master', 'master'), ('slave', 'slave'), ('https', 'g3')]:
            with self.subTest(target=target):
                self.seed(stem)
                self.rotate(target, *(['--ip', '192.0.2.10'] if target != 'https' else []))
                leaf = sign_csr(self.directory / (stem + '.csr'), self.root / (stem + '-issued.crt'),
                                ca, role='client' if target == 'master' else 'server', ips=['192.0.2.10'])
                tool = SCRIPT.parent / ('https_certificates.py' if target == 'https' else 'modbus_certs.py')
                base = [sys.executable, str(tool), '--config', str(self.config), '--dir', str(self.directory)]
                role = ['--role', target] if target != 'https' else []
                for arguments in [
                    ['identity-import', *role, '--cert', str(leaf), '--chain', str(ca['intermediate'])],
                    ['check', *role],
                ]:
                    result = subprocess.run(base + arguments, env=self.env, capture_output=True, timeout=60)
                    self.assertEqual(result.returncode, 0, result.stderr.decode())


if __name__ == '__main__':
    unittest.main()
