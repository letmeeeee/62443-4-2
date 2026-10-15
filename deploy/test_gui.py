"""Headless GUI command mapping and noninteractive SSH tests."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import gui
import deploy as deployment


class GuiTests(unittest.TestCase):
    def test_normal_deployment_uses_cli_and_batch_ssh(self):
        command = gui.build_command(gui.Options())
        self.assertEqual(command[:3], [sys.executable, '-u', str(gui.ROOT / 'deploy/deploy.py')])
        self.assertIn('--batch-mode', command)
        self.assertIn('root@192.168.2.136', command)
        self.assertNotIn('--master-name', command)
        self.assertNotIn('--initialize-ini-baseline', command)

    def test_migration_arguments_are_separate_argv_values(self):
        command = gui.build_command(gui.Options(
            master_enabled=True, master_name='master-001',
            slave_enabled=True, slave_name='slave-001',
            slave_ips='192.168.2.136, 192.168.3.136', frontend=True))
        self.assertEqual(command.count('--slave-ip'), 2)
        self.assertIn('--with-frontend', command)
        self.assertEqual(command[command.index('--master-name') + 1], 'master-001')

    def test_invalid_target_and_migration_options_are_rejected(self):
        for options in (gui.Options(host='root@host; echo bad'),
                        gui.Options(jobs='invalid'), gui.Options(jobs='0'),
                        gui.Options(slave_enabled=True, slave_name='slave', slave_ips=''),
                        gui.Options(master_enabled=True, master_name='$(echo bad)')):
            with self.subTest(options=options), self.assertRaises(ValueError):
                gui.build_command(options)

    def test_certificate_selection_requires_public_pem_and_fingerprint(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'public cert.crt'
            path.write_text('-----BEGIN CERTIFICATE-----\nTEST\n-----END CERTIFICATE-----\n')
            fingerprint = ':'.join(['AB'] * 32)
            options = gui.Options(trust_enabled=True, certificate=str(path), fingerprint=fingerprint)
            command = gui.build_command(options)
            self.assertEqual(command[command.index('--trust-master') + 1], str(path))
            self.assertEqual(command[command.index('--trust-master-fingerprint') + 1], 'AB' * 32)
            path.write_text('-----BEGIN PRIVATE KEY-----\nTEST\n')
            with self.assertRaises(ValueError):
                gui.build_command(options)

    def test_bundle_only_can_omit_device(self):
        self.assertIn('--bundle-only', gui.build_command(gui.Options(host=''), True))
        with self.assertRaises(ValueError):
            gui.build_command(gui.Options(host=''))

    def test_cli_batch_mode_checks_ssh_before_building(self):
        with patch.dict(os.environ), \
             patch.object(sys, 'argv', ['deploy.py', '--host', 'root@192.168.2.136', '--batch-mode']), \
             patch.object(deployment, 'run', side_effect=RuntimeError('stop before SSH')) as run:
            with self.assertRaisesRegex(RuntimeError, 'stop before SSH'):
                deployment.main()
            arguments = run.call_args.args
            self.assertEqual(arguments[0], 'ssh')
            self.assertIn('BatchMode=yes', arguments)
            self.assertEqual(os.environ['DEPLOY_SSH_BATCH'], '1')


if __name__ == '__main__':
    unittest.main()
