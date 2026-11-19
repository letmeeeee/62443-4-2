"""Exercise the real launcher with device imports and system operations replaced."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize('package_sha256', ['b0' * 32, None])
def test_launcher_passes_package_identity_before_service_restart(tmp_path, monkeypatch, package_sha256):
    config = ModuleType('config')
    for name in ('ROLLBACK_SCRIPT', 'SSH_KEY_PATH', 'REMOTE_PORT', 'REMOTE_PASSWORD',
                 'REMOTE_PASSWORD_TEST', 'FIXED_DEVICE_ID', 'READ_INPUT_REGISTER'):
        setattr(config, name, None)
    config.UPGRADE_SCRIPT = tmp_path / 'upgrade.sh'
    config.UPGRADE_SCRIPT.write_text('#!/bin/bash\n')
    config.UPLOAD_DIR = tmp_path
    config.STATE_ERROR = -1
    method = ModuleType('utils.method')
    method._write_status = Mock()
    logging = ModuleType('utils.utils')
    logging.DPrint = logging.debug_log = Mock()
    logging.now_str = lambda: ''
    common = ModuleType('constent.common')
    common.PCS_UPGRADE_STATUS_BASE_ADDRESS = common.PCS_FAULT_STEP = 0
    for name, module in [('config', config), ('utils.method', method),
                         ('utils.utils', logging), ('constent.common', common)]:
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location(
        'upgrade_launcher_under_test', Path(__file__).parents[1] / 'utils/systemctl.py')
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    monkeypatch.setattr(launcher.threading, 'Thread',
                        lambda target, daemon: SimpleNamespace(start=target))
    monkeypatch.setattr(launcher.time, 'sleep', lambda delay: None)
    (tmp_path / 'package_sha256').write_text('stale hash')

    def restart(cmd, **kwargs):
        assert cmd == ['systemctl', 'restart', 'python_upgrade.service']
        assert (tmp_path / 'job_id').read_text() == 'job-1'
        assert (tmp_path / 'release_version').read_text() == '109'
        assert (tmp_path / 'package_sha256').read_text() == (package_sha256 or '')

    popen = Mock(side_effect=restart)
    monkeypatch.setattr(launcher.subprocess, 'Popen', popen)
    if package_sha256 is None:
        launcher.run_upgrade_async('job-1', '109', delay_sec=0)
    else:
        launcher.run_upgrade_async('job-1', '109', delay_sec=0, package_sha256=package_sha256)
    popen.assert_called_once()
    method._write_status.assert_not_called()
