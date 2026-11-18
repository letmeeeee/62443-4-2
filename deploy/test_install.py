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
    'home/zlg/app/script/modbus_certs.py': b'# new cert script',
    'home/zlg/app/script/sign_ini.py': b'# new baseline script',
}


def bundle_at(path, corrupt=False, files=None):
    files = REQUIRED if files is None else files
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    if corrupt:
        manifest['home/zlg/tems'] = '0' * 64
    with tarfile.open(path, 'w:gz') as archive:
        for name, data in [('manifest.json', json.dumps(manifest).encode())] + [
                ('payload/' + name, data) for name, data in files.items()]:
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

    def exercise(self, fail_start=False, mismatch=False, goose=False, new_goose=False, goose_active=True, fail_goose=False):
        with tempfile.TemporaryDirectory(prefix='installer-test-') as temp:
            root = Path(temp) / 'root'
            root.mkdir()
            files = dict(REQUIRED)
            if goose:
                files.update({installer.GOOSE_BINARY: b'new goose', installer.GOOSE_UNIT: b'new GOOSE unit'})
            for name in files:
                if new_goose and name == installer.GOOSE_UNIT:
                    continue
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
            bundle_at(bundle, files=files)
            running = {name: True for name in installer.SERVICES}
            if goose:
                running[installer.GOOSE_SERVICE] = goose_active and not new_goose
            original_running = dict(running)
            pki = root / 'etc/ems/goose/current/enc.key'
            pki.parent.mkdir(parents=True)
            pki.write_bytes(b'unchanged private key')
            gooselog = root / 'mnt/nvme/goose_log/previous.log'
            gooselog.parent.mkdir(parents=True)
            gooselog.write_bytes(b'unchanged log')
            failed = False
            mutations = []

            def filesystem_path(value):
                path = Path(value)
                if str(path) == '/' or str(path).startswith(('/home/zlg', '/etc/ems', '/lib/optee_armtz', '/etc/systemd/system')):
                    return root / str(path).lstrip('/')
                return path

            def subprocess_run(args, **kwargs):
                nonlocal failed
                args = list(map(str, args))
                if args[0] == 'ldd':
                    return SimpleNamespace(returncode=0, stdout='libteec.so.2 => /lib/libteec.so.2', stderr='')
                if args[:2] == ['systemctl', 'show']:
                    output = 'not-found\n' if new_goose and args[2] == installer.GOOSE_SERVICE else 'loaded\n'
                    if '--property=ExecStart' in args:
                        output = ('/home/zlg/goose/goose_middle' if args[2] == installer.GOOSE_SERVICE else
                                  '/home/zlg/tems' if args[2] == 'tems.service' else '/home/zlg/myenv/bin/python3 /home/zlg/app/main.py')
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
                    if (fail_start or (fail_goose and args[2] == installer.GOOSE_SERVICE)) and not failed:
                        failed = True
                        raise installer.subprocess.CalledProcessError(1, args)
                    running[args[2]] = True
                elif args[:2] == ['systemctl', 'daemon-reload']:
                    mutations.append('daemon-reload')
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
                elif fail_start or fail_goose:
                    with self.assertRaises(installer.subprocess.CalledProcessError):
                        installer.main()
                else:
                    installer.main()
            for name, data in files.items():
                if name == installer.GOOSE_UNIT:
                    if new_goose and (fail_start or fail_goose or mismatch):
                        self.assertFalse((root / name).exists())
                        continue
                    if not new_goose:
                        self.assertEqual((root / name).read_bytes(), b'old ' + name.encode())
                        continue
                expected = b'old ' + name.encode() if mismatch or fail_start or fail_goose else data
                self.assertEqual((root / name).read_bytes(), expected)
                if fail_start or fail_goose:
                    self.assertEqual((root / name).stat().st_mode & 0o777, 0o640)
            self.assertEqual(running, original_running)
            if goose and not (mismatch or fail_start or fail_goose):
                self.assertEqual((root / installer.GOOSE_BINARY).stat().st_mode & 0o777, 0o755)
                self.assertEqual((root / 'home/zlg/app/bin/modbus_tee_identity').stat().st_mode & 0o777, 0o755)
            self.assertEqual(pki.read_bytes(), b'unchanged private key')
            self.assertEqual(gooselog.read_bytes(), b'unchanged log')
            self.assertEqual(session.read_text(), 'persistent session configuration')

    def test_install_and_preserve_configuration(self):
        self.exercise()

    def test_restart_failure_restores_original_files_and_services(self):
        self.exercise(fail_start=True)

    def test_ini_mismatch_aborts_before_stopping_services(self):
        self.exercise(mismatch=True)

    def test_existing_goose_service_is_upgraded_and_preserves_unit(self):
        self.exercise(goose=True)

    def test_inactive_goose_service_is_not_started(self):
        self.exercise(goose=True, goose_active=False)

    def test_first_goose_install_creates_unit_without_starting(self):
        self.exercise(goose=True, new_goose=True)

    def test_goose_restart_failure_rolls_back_all_binaries(self):
        self.exercise(goose=True, fail_goose=True)

    def test_failed_first_install_removes_new_service_unit(self):
        self.exercise(goose=True, new_goose=True, fail_start=True)

    def test_archive_rejects_partial_goose_and_pki_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for extra in ({installer.GOOSE_BINARY: b'goose'},
                          {installer.GOOSE_UNIT: b'unit'},
                          {'etc/ems/goose/current/enc.key': b'private key'}):
                with self.subTest(extra=list(extra)):
                    archive = root / ('bundle-' + str(len(list(root.glob('*.tar.gz')))) + '.tar.gz')
                    bundle_at(archive, files=dict(REQUIRED, **extra))
                    with self.assertRaises(ValueError):
                        installer.unpack(archive, root / (archive.stem + '-unpacked'))


if __name__ == '__main__':
    unittest.main()
