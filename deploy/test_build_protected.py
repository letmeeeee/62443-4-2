"""Offline tests: do not import/start Flask, MySQL, Modbus or device services."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('protected_builder', Path(__file__).with_name('build_protected.py'))
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class ProtectedBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='ems-protected-test-')
        cls.root = Path(cls.temporary.name)
        cls.inventory = builder.sources(builder.APP)
        cls.original_hashes = {r: hashlib.sha256((builder.APP / r).read_bytes()).hexdigest()
                               for r in cls.inventory}
        cls.staged, cls.entries = builder.stage(builder.APP, cls.root / 'work', cls.inventory)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def invoke(self, entry, *args):
        """Exercise the exact generated dispatcher using source, in a subprocess.

        Simulate Standalone's executable location; this does not claim to test
        Nuitka compilation itself. Only select standard-library offline tools.
        """
        runtime = self.root / 'app/.runtime/ems.dist'
        runtime.mkdir(parents=True, exist_ok=True)
        (runtime / 'logical-root.txt').write_text(str(self.staged))
        bootstrap = (
            'import runpy,sys; '
            f'sys.path[:0] = {[str(self.staged), str(self.staged / "script")]!r}; '
            f'sys.executable={str(runtime / "ems-runtime")!r}; '
            f'sys.argv={["ems-runtime", entry, *map(str, args)]!r}; '
            f'runpy.run_path({str(self.staged / "_ems_dispatch.py")!r}, run_name="__main__")'
        )
        return subprocess.run([sys.executable, '-c', bootstrap], text=True, capture_output=True)

    def test_complete_inventory_and_no_source_mutation(self):
        self.assertIn('main.py', self.inventory)
        self.assertIn('upgrade/upgrade.py', self.inventory)
        self.assertIn('script/upgrade.sh', self.inventory)
        self.assertFalse(any('tests/' in p or '/keys/' in p for p in self.inventory))
        self.assertEqual(self.original_hashes,
                         {r: hashlib.sha256((builder.APP / r).read_bytes()).hexdigest()
                          for r in self.inventory})
        for relative in self.inventory:
            self.assertTrue((self.staged / relative).is_file(), relative)
            if relative.endswith('.py') and relative != '__init__.py':
                self.assertIn(relative, self.entries)

    def test_all_generated_python_and_shell_syntax(self):
        for path in self.staged.rglob('*.py'):
            ast.parse(path.read_text(), filename=str(path))
        for path in self.staged.rglob('*.sh'):
            result = subprocess.run(['bash', '-n', path], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_future_import_docstring_and_global_cli_scope(self):
        source = ('"""Example."""\nfrom __future__ import annotations\n'
                  'def result():\n    return argument\n'
                  'if __name__ == "__main__":\n    argument = 7\n    assert result() == 7\n')
        adapted = builder.adapt_python(source, 'example.py')
        tree = ast.parse(adapted)
        self.assertEqual(ast.get_docstring(tree), 'Example.')
        self.assertEqual(tree.body[1].module, '__future__')
        self.assertTrue(isinstance(tree.body[-1], ast.If))

    def test_bootstrap_has_no_device_imports(self):
        result = self.invoke('--ems-info')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['mode'], 'standalone')

    def test_plan_does_not_force_uncompiled_distribution_metadata(self):
        output = self.root / 'metadata-plan'
        with patch.object(sys, 'argv', ['build_protected.py', '--plan', '--output', str(output)]):
            builder.main()
        command = json.loads((output / 'build-plan.json').read_text())['command']
        self.assertFalse(any(arg.startswith('--include-distribution-metadata=') for arg in command))
        self.assertIn('--include-module=sqlalchemy.dialects.mysql.pymysql', command)

    def test_dependency_versions_remain_discoverable_without_importable_code(self):
        runtime = self.root / 'metadata-runtime'
        record = dict(name='build-only-example', version='1.2.3', metadata=(
            'Metadata-Version: 2.1\nName: build-only-example\nVersion: 1.2.3\n'))
        builder.publish_distribution_metadata(runtime, [record])
        found = {d.metadata['Name']: d.version
                 for d in builder.importlib.metadata.distributions(path=[str(runtime)])}
        self.assertEqual(found, {'build-only-example': '1.2.3'})
        self.assertEqual(list(runtime.rglob('*.py')), [])
        builder.audit(runtime, [])

    def test_existing_nuitka_metadata_is_preserved_and_conflicts_rejected(self):
        runtime = self.root / 'metadata-existing'
        directory = runtime / 'Some_Package-1.0.dist-info'
        directory.mkdir(parents=True)
        metadata = 'Metadata-Version: 2.1\nName: Some-Package\nVersion: 1.0\n'
        (directory / 'METADATA').write_text(metadata)
        (directory / 'entry_points.txt').write_text('[existing]\n')
        record = dict(name='some_package', version='1.0', metadata='should not overwrite')
        builder.publish_distribution_metadata(runtime, [record])
        self.assertEqual((directory / 'METADATA').read_text(), metadata)
        self.assertEqual((directory / 'entry_points.txt').read_text(), '[existing]\n')
        with self.assertRaisesRegex(ValueError, 'Conflicting runtime distribution version'):
            builder.publish_distribution_metadata(runtime, [dict(record, version='2.0')])

    def test_https_config_relative_and_absolute_entry(self):
        config = self.root / 'device.ini'
        config.write_text('[HTTPS]\ndevice_ips=192.168.1.9,192.168.1.8\n')
        for entry in ('script/https_config.py', str(self.staged / 'script/https_config.py')):
            result = self.invoke(entry, config)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), '192.168.1.8 192.168.1.9')

    def test_status_tool_exit_status_and_no_backend_imports(self):
        status = self.root / 'status'
        status.mkdir(exist_ok=True)
        result = self.invoke('script/watch_upgrade_status.py', 'missing', '--once', '--status-dir', status)
        self.assertEqual(result.returncode, 1, result.stderr)
        (status / 'job.json').write_text('{"progress": 100, "state": 3, "msg": "ok"}')
        result = self.invoke('script/watch_upgrade_status.py', 'job', '--once', '--status-dir', status)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('progress=100%', result.stdout)

    def test_rotation_help_imports_compiled_module_names(self):
        result = self.invoke('script/_rotate_identity_key.py', self.staged / 'script', '--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ROTATE_IDENTITY_KEY', result.stdout)

    def test_frozen_point_definitions_equal_original(self):
        path = self.staged / 'script/generate_point_labels.py'
        body = next(n for n in ast.parse(path.read_text()).body
                    if isinstance(n, ast.FunctionDef) and n.name == 'extract_definitions')
        self.assertEqual(ast.literal_eval(body.body[0].value), builder.point_definitions(builder.APP))

    def test_session_default_stays_outside_versioned_release(self):
        stable = self.root / 'logical-app'
        stable.symlink_to(self.staged, target_is_directory=True)
        bootstrap = (
            'import sys; from pathlib import Path; '
            f'sys.path.insert(0, {str(self.staged)!r}); '
            'import _ems_runtime; '
            f'_ems_runtime.logical_root=Path({str(stable)!r}); '
            'from script.session_config import DEFAULT_CONFIG_PATH; '
            'print(DEFAULT_CONFIG_PATH)'
        )
        result = subprocess.run([sys.executable, '-c', bootstrap], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(self.root / 'instance/session_config.json'))

    def test_failed_database_snapshot_aborts_before_upgrade(self):
        base = self.root / 'snapshot-failure'
        script = base / 'app/script/manage_upgrade_db.py'
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text('#!/bin/sh\nexit 0\n')
        script.chmod(0o755)
        # Deliberately omit .runtime. The legacy shell does not use set -e, so
        # snapshot failure must explicitly stop rather than continue an upgrade.
        text = (self.staged / 'script/upgrade.sh').read_text()
        block = text[text.index('PACKAGE_DB_TOOL=""'):text.index('\nUPGRADE_STATUS_DIR=')]
        result = subprocess.run(['bash', '-c', 'set -u\nBASE_DIR="$1"\n' + block
                                 + '\necho SHOULD_NOT_CONTINUE\n', 'snapshot-test', str(base)],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotIn('SHOULD_NOT_CONTINUE', result.stdout)
        self.assertIn('Cannot preserve database runtime', result.stderr)

    def test_shell_python_call_and_snapshot_adaptations(self):
        https = (self.staged / 'script/enable_https.sh').read_text()
        self.assertNotIn('python3 "$SCRIPT_DIR/', https)
        self.assertIn('cp -a -- "$SCRIPT_DIR/../.runtime"', https)
        self.assertIn('ExecStart=/usr/local/lib/g3-https/script/enable_https.sh', https)
        self.assertIn('${BASH_SOURCE[0]}', https)
        self.assertIn("sed -n '2,8p' \"$0\"", https)
        upgrade = (self.staged / 'script/upgrade.sh').read_text()
        self.assertNotIn('python3 -c "$PACKAGE_DB_TOOL"', upgrade)
        self.assertIn('cp -a -- "$BASE_DIR/app/.runtime"', upgrade)
        route = (self.staged / 'routes/route_cert.py').read_text()
        self.assertIn("['bash', str(folder / 'enable_https.sh')", route)

    def test_shell_published_readable_and_executable(self):
        payload = self.root / 'shell-release'
        for relative in (r for r in self.inventory if r.endswith('.sh')):
            builder.publish_shell(self.staged / relative, payload / relative)
        builder.audit(payload, [r for r in self.inventory if r.endswith('.sh')])
        # Execute the packaged HTTPS help through bash: no root/device operations.
        result = subprocess.run(['bash', payload / 'script/enable_https.sh', '--help'],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--install-service', result.stdout)

    def test_unknown_and_traversal_entries_are_rejected(self):
        for entry in ('../main.py', '/tmp/main.py', 'unknown.py'):
            result = self.invoke(entry)
            self.assertNotEqual(result.returncode, 0)

    def test_audit_rejects_missing_and_plaintext_sources(self):
        payload = self.root / 'audit'
        payload.mkdir(exist_ok=True)
        with self.assertRaises(ValueError):
            builder.audit(payload, ['main.py'])
        (payload / 'main.py').write_text('print("source leak")')
        with self.assertRaises(ValueError):
            builder.audit(payload, ['main.py'])
        (payload / 'main.py').write_bytes(b'\x7fELFfixture')
        builder.audit(payload, ['main.py'])
        (payload / 'leak.pyc').write_bytes(b'bytecode')
        with self.assertRaises(ValueError):
            builder.audit(payload, ['main.py'])

    @unittest.skipUnless(shutil.which('cc'), 'C compiler unavailable')
    def test_native_launcher_arguments_and_exit_code(self):
        app = self.root / 'native app'
        runtime = app / '.runtime/ems.dist/ems-runtime'
        runtime.parent.mkdir(parents=True, exist_ok=True)
        fake = self.root / 'fake_runtime.c'
        fake.write_text('#include <stdio.h>\nint main(int n,char **v){'
                        'for(int i=1;i<n;i++) puts(v[i]);return 7;}\n')
        subprocess.run(['cc', '-o', runtime, fake], check=True, capture_output=True)
        entry = app / 'script/watch_upgrade_status.py'
        entry.parent.mkdir(parents=True, exist_ok=True)
        source = self.root / 'launcher.c'
        source.write_text(builder.launcher_source('script/watch_upgrade_status.py'))
        subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-o', entry, source],
                       check=True, capture_output=True)
        result = subprocess.run([entry, 'two words', '--once'], text=True, capture_output=True)
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stdout.splitlines(), ['script/watch_upgrade_status.py', 'two words', '--once'])


if __name__ == '__main__':
    unittest.main()
