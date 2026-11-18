"""Bundle tests use fake ELF headers and isolated inputs; no compiler, SSH or device."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('bundle_builder', Path(__file__).with_name('deploy.py'))
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def arm64_elf():
    header = bytearray(20)
    header[:6] = b'\x7fELF\x02\x01'
    header[18:20] = b'\xb7\x00'
    return bytes(header) + b'unit test artifact'


class BundleTests(unittest.TestCase):
    def inputs(self, root):
        sdk = root / 'logger/.deps/optee-arm64'
        sdk.mkdir(parents=True)
        for name, data in {
            'logger/build-deploy/tems': arm64_elf(),
            'logger/build-deploy/modbus_tee_identity': arm64_elf(),
            'exec/app/tee/build-deploy/crypto_ta_client': arm64_elf(),
            'optee_ta_examples/build-deploy/' + builder.UUID + '.ta': b'test ta',
            'goose/goose_test/build-deploy/goose_middle': arm64_elf(),
            'goose/goose_test/deploy/goose_middle.service': b'[Service]\nExecStart=/home/zlg/goose/goose_middle\n',
            'exec/app/main.py': b'# backend',
            'exec/app/script/modbus_certs.py': b'# cert script',
            'exec/app/script/goose_pki.py': b'# goose pki',
            'exec/app/instance/secret.py': b'never ship credentials',
        }.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def test_bundle_contains_goose_identity_and_manifest_checksums(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.inputs(root)
            with patch.object(builder, 'ROOT', root), patch.object(sys, 'argv',
                    ['deploy.py', '--bundle-only', '--skip-build']), patch.object(builder, 'run') as run:
                builder.main()
                run.assert_not_called()
            with tarfile.open(root / 'deploy/build-output/em1000-upgrade.tar.gz') as archive:
                manifest = json.load(archive.extractfile('manifest.json'))
                for name in ('home/zlg/goose/goose_middle', 'etc/systemd/system/goose_middle.service',
                             'home/zlg/app/bin/modbus_tee_identity', 'home/zlg/app/script/goose_pki.py'):
                    self.assertIn(name, manifest)
                    payload = archive.extractfile('payload/' + name).read()
                    self.assertEqual(hashlib.sha256(payload).hexdigest(), manifest[name])
                self.assertFalse(any('instance' in name or 'enc.key' in name for name in manifest))

    def test_normal_build_builds_library_before_secure_bridge(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.inputs(root)
            calls = []
            with patch.object(builder, 'ROOT', root), patch.object(sys, 'argv',
                    ['deploy.py', '--bundle-only']), patch.object(builder, 'run',
                    side_effect=lambda *args: calls.append(list(map(str, args)))):
                builder.main()
            configure = [call for call in calls if call[:2] == ['cmake', '-S']]
            lib = next(call for call in configure if call[2] == str(root / 'goose/libiec61850'))
            bridge = next(call for call in configure if call[2] == str(root / 'goose/goose_test'))
            self.assertLess(calls.index(lib), calls.index(bridge))
            self.assertIn('-DOPENSSL_INCLUDE_DIR=' + str(root / 'logger/.deps/openssl-arm64/include'), bridge)
            self.assertTrue(any('--target' in call and 'goose_middle' in call for call in calls))
            self.assertTrue(any(call[:3] == ['make', '-C', str(root / 'logger')] for call in calls))
            self.assertFalse(any(call[0] in ('ssh', 'scp') for call in calls))

    def test_missing_identity_and_wrong_architecture_goose_fail_packaging(self):
        for failure in ('missing_identity', 'x86_goose'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                self.inputs(root)
                if failure == 'missing_identity':
                    (root / 'logger/build-deploy/modbus_tee_identity').unlink()
                else:
                    (root / 'goose/goose_test/build-deploy/goose_middle').write_bytes(b'not ARM64')
                with patch.object(builder, 'ROOT', root), patch.object(sys, 'argv',
                        ['deploy.py', '--bundle-only', '--skip-build']), self.assertRaises(RuntimeError):
                    builder.main()


if __name__ == '__main__':
    unittest.main()
