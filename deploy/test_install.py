"""Installer tests use an isolated filesystem and fake services; never SSH."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('device_install', Path(__file__).with_name('install.py'))
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)

REQUIRED = {
    'home/zlg/tems': b'new tems',
    installer.TA: b'new ta',
    'home/zlg/app/main.py': b'# new main',
    'home/zlg/app/bin/modbus_tee_identity': b'new identity',
    'home/zlg/app/bin/crypto_ta_client': b'new client',
    'home/zlg/app/scripts/modbus_certs.py': b'# new cert script',
    'home/zlg/app/script/sign_ini.py': b'# new baseline script',
}


def bundle_at(path, corrupt=False):
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in REQUIRED.items()}
    if corrupt:
        manifest['home/zlg/tems'] = '0' * 64
    with tarfile.open(path, 'w:gz') as archive:
        for name, data in [('manifest.json', json.dumps(manifest).encode())] + [
                ('payload/' + name, data) for name, data in REQUIRED.items()]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


class InstallerTests(unittest.TestCase):
    def test_archive_rejects_checksum_error_and_unsafe_paths(self):
        self.assertFalse(installer.allowed('home/zlg/app/../../etc/shadow'))
        self.assertFalse(installer.allowed('home/zlg/app/instance/session_config.py'))
        self.assertFalse(installer.allowed('/etc/passwd'))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle_at(root / 'bundle.tar.gz', corrupt=True)
            with self.assertRaisesRegex(ValueError, 'Checksum mismatch'):
                installer.unpack(root / 'bundle.tar.gz', root / 'unpacked')

    def exercise(self, fail_start=False, mismatch=False):
        with tempfile.TemporaryDirectory(prefix='installer-test-') as temp:
            root = Path(temp) / 'root'
            root.mkdir()
            for name in REQUIRED:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'old ' + name.encode())
                target.chmod(0o640)
            ini = root / 'home/zlg/lc_data_set.ini'
            ini.write_text('[SYSTEM]\nmodbus_tls_enabled=0\n')
            baseline = root / 'home/zlg/signature/lc_data_set.ini.sha256'
            baseline.parent.mkdir()
            baseline.write_text('0' * 64 if mismatch else hashlib.sha256(ini.read_bytes()).hexdigest())
            session = root / 'home/zlg/instance/session_config.json'
            session.parent.mkdir()
            session.write_text('persistent session configuration')
            bundle = Path(temp) / 'bundle.tar.gz'
            bundle_at(bundle)
            running = {name: True for name in installer.SERVICES}
            failed = False
            mutations = []

            def filesystem_path(value):
                path = Path(value)
                if str(path) == '/' or str(path).startswith(('/home/zlg', '/etc/ems', '/lib/optee_armtz')):
                    return root / str(path).lstrip('/')
                return path

            def subprocess_run(args, **kwargs):
                nonlocal failed
                args = list(map(str, args))
                if args[0] == 'ldd':
                    return SimpleNamespace(returncode=0, stdout='libteec.so.2 => /lib/libteec.so.2', stderr='')
                if args[:2] == ['systemctl', 'show']:
                    output = 'loaded\n'
                    if '--property=ExecStart' in args:
                        output = '/home/zlg/tems' if args[2] == 'tems.service' else '/home/zlg/myenv/bin/python3 /home/zlg/app/main.py'
                    if '--property=WorkingDirectory' in args:
                        output = '/home/zlg/app'
                    return SimpleNamespace(returncode=0, stdout=output, stderr='')
                if args[:2] == ['systemctl', 'is-active']:
                    return SimpleNamespace(returncode=0 if running[args[-1]] else 3)
                if args[:2] == ['systemctl', 'stop']:
                    mutations.append('stop')
                    for service in args[2:]:
                        running[service] = False
                elif args[:2] == ['systemctl', 'start']:
                    if fail_start and not failed:
                        failed = True
                        raise installer.subprocess.CalledProcessError(1, args)
                    running[args[2]] = True
                else:
                    raise AssertionError('Unexpected command: ' + repr(args))
                return SimpleNamespace(returncode=0)

            response = unittest.mock.MagicMock()
            response.__enter__.return_value.status = 200
            with patch.object(installer, 'Path', filesystem_path), \
                 patch.object(installer.os, 'geteuid', return_value=0), \
                 patch.object(installer.os, 'uname', return_value=SimpleNamespace(machine='aarch64')), \
                 patch.object(installer.os, 'chown'), \
                 patch.object(installer.shutil, 'which', return_value='/bin/tool'), \
                 patch.object(installer.subprocess, 'run', side_effect=subprocess_run), \
                 patch.object(installer.time, 'sleep'), \
                 patch.object(installer.urllib.request, 'urlopen', return_value=response), \
                 patch.object(sys, 'argv', ['install.py', '--bundle', str(bundle)]):
                if mismatch:
                    with self.assertRaisesRegex(RuntimeError, 'baseline mismatch'):
                        installer.main()
                    self.assertFalse(mutations)
                elif fail_start:
                    with self.assertRaises(installer.subprocess.CalledProcessError):
                        installer.main()
                else:
                    installer.main()
            for name, data in REQUIRED.items():
                expected = b'old ' + name.encode() if mismatch or fail_start else data
                self.assertEqual((root / name).read_bytes(), expected)
                if fail_start:
                    self.assertEqual((root / name).stat().st_mode & 0o777, 0o640)
            self.assertTrue(all(running.values()))
            self.assertEqual(session.read_text(), 'persistent session configuration')

    def test_install_and_preserve_configuration(self):
        self.exercise()

    def test_restart_failure_restores_original_files_and_services(self):
        self.exercise(fail_start=True)

    def test_ini_mismatch_aborts_before_stopping_services(self):
        self.exercise(mismatch=True)


if __name__ == '__main__':
    unittest.main()
