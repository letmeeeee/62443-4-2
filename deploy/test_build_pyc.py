"""Real CPython compilation/import tests; no backend/DB/device imports."""
import ast
import hashlib
import importlib.util
import json
import marshal
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('pyc_builder', Path(__file__).with_name('build_pyc.py'))
builder = importlib.util.module_from_spec(SPEC)
with patch.object(sys, 'path', [str(Path(__file__).parent), *sys.path]):
    SPEC.loader.exec_module(builder)


class PycBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='ems-pyc-test-')
        cls.root = Path(cls.temporary.name)
        cls.inventory = builder.sources(builder.APP)
        cls.source_hashes = {r: hashlib.sha256((builder.APP / r).read_bytes()).hexdigest()
                             for r in cls.inventory}
        cls.staged = builder.stage(builder.APP, cls.root / 'work', cls.inventory)
        cls.payload = cls.root / 'release/app'
        builder.compile_app(cls.staged, cls.payload, cls.inventory)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def invoke(self, relative, *args):
        return subprocess.run([sys.executable, self.payload / relative, *map(str, args)],
                              cwd=self.root, text=True, capture_output=True)

    def test_complete_real_bytecode_without_source_mutation(self):
        builder.audit(self.payload, self.inventory)
        self.assertEqual(self.source_hashes,
                         {r: hashlib.sha256((builder.APP / r).read_bytes()).hexdigest()
                          for r in self.inventory})
        self.assertEqual(len(list(self.payload.rglob('*.pyc'))),
                         sum(r.endswith('.py') for r in self.inventory))
        self.assertEqual(list(self.payload.rglob('*.py')), [])

    def test_offline_cli_tools_work_with_no_source_files(self):
        config = self.root / 'device.ini'
        config.write_text('[HTTPS]\ndevice_ips=192.168.1.9,192.168.1.8\n')
        result = self.invoke('script/https_config.pyc', config)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '192.168.1.8 192.168.1.9')
        result = self.invoke('script/manage_upgrade_db.pyc', '--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--set-current', result.stdout)
        result = self.invoke('script/watch_upgrade_status.pyc', 'missing', '--once',
                             '--status-dir', self.root)
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_plain_shell_inline_python_can_import_bytecode_helpers(self):
        result = subprocess.run(['sh', self.payload / 'script/rotate_identity_key.sh', '--help'],
                                cwd=self.root, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ROTATE_IDENTITY_KEY', result.stdout)

    def test_all_shell_syntax_and_python_call_paths(self):
        for path in self.payload.rglob('*.sh'):
            result = subprocess.run(['bash', '-n', path], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        https = (self.payload / 'script/enable_https.sh').read_text()
        self.assertIn('/home/zlg/app/main.pyc', https)
        self.assertIn('python3 "$SCRIPT_DIR/https_config.pyc"', https)
        self.assertIn('/usr/local/lib/g3-https/https_certificates.pyc', https)
        upgrade = (self.payload / 'script/upgrade.sh').read_text()
        self.assertNotIn('python3 -c "$PACKAGE_DB_TOOL"', upgrade)
        self.assertIn('python3 "$PACKAGE_DB_TOOL"', upgrade)
        route = (self.staged / 'routes/route_cert.py').read_text()
        self.assertIn('modbus_certs.pyc', route)
        self.assertIn("folder / 'https_certificates.pyc'", route)

    def test_regular_and_namespace_packages_import_without_source(self):
        result = subprocess.run([sys.executable, '-c',
                                 'from constent.common import SYSTEM_SPC_VERSION_ADDR; '
                                 'from script.https_config import read_device_ips; '
                                 'print(SYSTEM_SPC_VERSION_ADDR, callable(read_device_ips))'],
                                cwd=self.payload, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '5 True')

    def test_frozen_definitions_and_assertions_are_preserved(self):
        tree = ast.parse((self.staged / 'script/generate_point_labels.py').read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                        and n.name == 'extract_definitions')
        self.assertEqual(ast.literal_eval(function.body[0].value), builder.point_definitions(builder.APP))
        fixture = self.root / 'assert-source'
        fixture.mkdir()
        (fixture / 'sentinel.py').write_text('"""docstring survives"""\nassert False, "assert survives"\n')
        output = self.root / 'assert-output'
        builder.compile_app(fixture, output, ['sentinel.py'])
        result = subprocess.run([sys.executable, output / 'sentinel.pyc'], text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('assert survives', result.stderr)
        with (output / 'sentinel.pyc').open('rb') as stream:
            stream.read(16)
            code = marshal.load(stream)
        self.assertIn('docstring survives', code.co_consts)

    def test_version_and_magic_mismatches_stop_before_output(self):
        output = self.root / 'must-not-exist'
        for arguments in (['--target-python', '3.999'],
                          ['--target-python', f'{sys.version_info.major}.{sys.version_info.minor}',
                           '--target-magic', '00000000']):
            with patch.object(sys, 'argv', ['build_pyc.py', '--output', str(output), *arguments]):
                with self.assertRaises(SystemExit):
                    builder.main()
            self.assertFalse(output.exists())

    def test_verifier_checks_magic_integrity_and_source_leaks(self):
        release = self.root / 'verify-release'
        app = release / 'app'
        app.mkdir(parents=True)
        bytecode = self.payload / 'script/watch_upgrade_status.pyc'
        (app / 'tool.pyc').write_bytes(bytecode.read_bytes())
        manifest = dict(implementation='cpython',
                        python_minor=f'{sys.version_info.major}.{sys.version_info.minor}',
                        magic=importlib.util.MAGIC_NUMBER.hex(),
                        artifacts={'tool.pyc': hashlib.sha256(bytecode.read_bytes()).hexdigest()})
        metadata = release / 'manifest.json'
        metadata.write_text(json.dumps(manifest))
        self.assertEqual(builder.verify_release(release), 1)
        metadata.write_text(json.dumps(dict(manifest, magic='00000000')))
        with self.assertRaisesRegex(ValueError, 'Incompatible'):
            builder.verify_release(release)
        metadata.write_text(json.dumps(manifest))
        (app / 'tool.pyc').write_bytes(b'corrupted')
        with self.assertRaisesRegex(ValueError, 'Checksum'):
            builder.verify_release(release)
        (app / 'tool.pyc').write_bytes(bytecode.read_bytes())
        (app / 'leak.py').write_text('print("source")')
        with self.assertRaisesRegex(ValueError, 'Plaintext'):
            builder.verify_release(release)


if __name__ == '__main__':
    unittest.main()
