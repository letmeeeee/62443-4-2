"""Offline builder tests; these do not claim to run licensed PyArmor itself."""
import ast
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('pyarmor_builder', Path(__file__).with_name('build_pyarmor.py'))
builder = importlib.util.module_from_spec(SPEC)
with patch.object(sys, 'path', [str(Path(__file__).parent), *sys.path]):
    SPEC.loader.exec_module(builder)


class PyArmorBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='ems-pyarmor-test-')
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def test_stage_preserves_python_entry_semantics_and_readable_shell(self):
        inventory = builder.sources(builder.APP)
        staged = builder.stage(builder.APP, self.root / 'work', inventory)
        for relative in inventory:
            target = staged / relative
            self.assertTrue(target.is_file(), relative)
            if relative.endswith('.py'):
                ast.parse(target.read_text(), filename=relative)
                if relative != 'script/generate_point_labels.py':
                    self.assertEqual(target.read_text(), (builder.APP / relative).read_text(encoding='utf-8-sig'))
            else:
                result = subprocess.run(['bash', '-n', target], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                if relative not in {'script/upgrade.sh', 'script/enable_https.sh'}:
                    self.assertEqual(target.read_bytes(), (builder.APP / relative).read_bytes())
        upgrade = (staged / 'script/upgrade.sh').read_text()
        self.assertNotIn('python3 -c "$PACKAGE_DB_TOOL"', upgrade)
        self.assertIn('python3 "$PACKAGE_DB_TOOL"', upgrade)
        self.assertIn('PACKAGE_DB_RUNTIME_FOUND', upgrade)
        https = (staged / 'script/enable_https.sh').read_text()
        self.assertIn('python3 "$SCRIPT_DIR/https_config.py"', https)
        self.assertIn('cp -a -- "$runtime" /usr/local/lib/g3-https/', https)

    def runtime_fixture(self):
        generated = self.root / 'generated'
        runtime = generated / 'pyarmor_runtime_demo'
        runtime.mkdir(parents=True)
        # Loader fixture, not real encryption. Test import search paths only.
        (runtime / '__init__.py').write_text('def __pyarmor__(*args):\n    print("runtime-found")\n')
        header = bytearray(20)
        header[:6] = b'\x7fELF\x02\x01'
        header[18:20] = b'\xb7\x00'
        (runtime / 'pyarmor_runtime.so').write_bytes(header)
        return generated

    def test_runtime_available_for_direct_nested_entry_without_pythonpath(self):
        generated = self.runtime_fixture()
        payload = self.root / 'app'
        inventory = ['main.py', 'script/tool.py', 'upgrade/upgrade.py']
        for relative in inventory:
            target = payload / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('from pyarmor_runtime_demo import __pyarmor__\n'
                              '__pyarmor__(__name__, __file__, b"fixture")\n')
        runtime_name = builder.distribute_runtime(generated, payload, inventory)
        builder.audit(payload, inventory, runtime_name, 'linux.aarch64')
        for relative in inventory:
            result = subprocess.run([sys.executable, payload / relative], cwd=self.root,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'runtime-found')
        with self.assertRaisesRegex(ValueError, 'Wrong runtime architecture'):
            builder.audit(payload, inventory, runtime_name, 'linux.x86_64')
        (payload / 'main.py').write_text('# __pyarmor__\nprint("plaintext")\n')
        with self.assertRaisesRegex(ValueError, 'Unprotected Python'):
            builder.audit(payload, inventory, runtime_name, 'linux.aarch64')

    def test_runtime_is_required_and_multiple_build_runtimes_rejected(self):
        generated = self.root / 'no-runtime'
        generated.mkdir()
        with self.assertRaisesRegex(ValueError, 'Expected one PyArmor runtime'):
            builder.distribute_runtime(generated, self.root / 'app', ['main.py'])
        for name in ('pyarmor_runtime_one', 'pyarmor_runtime_two'):
            (generated / name).mkdir()
        with self.assertRaisesRegex(ValueError, 'Expected one PyArmor runtime'):
            builder.distribute_runtime(generated, self.root / 'app', ['main.py'])

    def test_license_failure_retains_log_and_stops(self):
        command = [sys.executable, '-c',
                   'print("INFO obfuscating file method.py", flush=True); '
                   'print("ERROR out of license", flush=True); raise SystemExit(2)']
        with self.assertRaises(SystemExit) as failed:
            builder.run_obfuscation(command, self.root, self.root)
        self.assertEqual(failed.exception.code, 2)
        report = json.loads((self.root / 'build-failure.json').read_text())
        self.assertEqual(report['reason'], 'license_limit')
        self.assertFalse(report['publishable'])
        self.assertIn('out of license', (self.root / 'pyarmor.log').read_text())

    def test_successful_obfuscation_retains_log_without_failure_report(self):
        builder.run_obfuscation([sys.executable, '-c', 'print("INFO done")'], self.root, self.root)
        self.assertIn('INFO done', (self.root / 'pyarmor.log').read_text())
        self.assertFalse((self.root / 'build-failure.json').exists())


if __name__ == '__main__':
    unittest.main()
