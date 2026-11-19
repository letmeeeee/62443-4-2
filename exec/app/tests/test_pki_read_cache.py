"""Public-read cache invalidation and concurrency; no service operations."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace
import sys

import pytest
from flask import Flask
from utils import pki_read_cache as cache


@pytest.fixture
def setup(tmp_path, monkeypatch):
    root = tmp_path / 'roots.pem'
    root.write_text('root-v1')
    config = tmp_path / 'device.ini'
    config.write_text('[TLS]\nca_file=' + str(root) + '\n')
    monkeypatch.setitem(sys.modules, 'config', SimpleNamespace(INI_PATH=config))
    app = Flask(__name__)
    app.config.update(MODBUS_CERT_DIR=str(tmp_path / 'modbus'), HTTPS_CERT_DIR=str(tmp_path / 'https'))
    return app, root, config


def test_repeated_reads_share_work_and_return_independent_data(setup):
    app, _, _ = setup
    calls = []
    def collect():
        calls.append(1)
        return [{'valid': True}]
    with app.app_context():
        first = cache.cached_pki_read('certs', collect)
        first[0]['valid'] = False
        assert cache.cached_pki_read('certs', collect) == [{'valid': True}]
    assert len(calls) == 1


@pytest.mark.parametrize('change', ['root', 'key', 'permissions', 'config', 'pending'])
def test_files_and_permissions_immediately_invalidate(setup, change):
    app, root, config = setup
    key = Path(app.config['MODBUS_CERT_DIR']) / 'master.key'
    key.parent.mkdir()
    key.write_text('test placeholder')
    calls = []
    def collect():
        calls.append(1)
        return len(calls)
    with app.app_context():
        assert cache.cached_pki_read('certs', collect) == 1
        if change == 'root':
            root.write_text('root-v2')
        elif change == 'key':
            key.write_text('changed placeholder')
        elif change == 'permissions':
            key.chmod(0o600)
        elif change == 'config':
            config.write_text(config.read_text() + '[HTTPS]\ndevice_ips=192.0.2.1\n')
        else:
            (root.parent / '.tems-apply-required').write_text('pending')
        assert cache.cached_pki_read('certs', collect) == 2


def test_expiry_clock_correction_and_exceptions_are_not_hidden(setup, monkeypatch):
    app, _, _ = setup
    now = [100.0]
    wall = [1000.0]
    monkeypatch.setattr(cache, 'monotonic', lambda: now[0])
    monkeypatch.setattr(cache, 'time', lambda: wall[0])
    calls = []
    def collect():
        calls.append(1)
        return len(calls)
    with app.app_context():
        assert cache.cached_pki_read('certs', collect) == 1
        now[0] += 3
        wall[0] += 3
        assert cache.cached_pki_read('certs', collect) == 2
        wall[0] -= 3600
        assert cache.cached_pki_read('certs', collect) == 3
        def fail():
            raise OSError('unavailable')
        with pytest.raises(OSError):
            cache.cached_pki_read('failed', fail)
        assert cache.cached_pki_read('failed', lambda: 'recovered') == 'recovered'


def test_concurrent_requests_only_collect_once(setup):
    app, _, _ = setup
    entered, release = Event(), Event()
    calls = []
    def collect():
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return {'valid': True}
    def request():
        with app.app_context():
            return cache.cached_pki_read('certs', collect)
    with ThreadPoolExecutor(max_workers=4) as pool:
        first = pool.submit(request)
        assert entered.wait(5)
        remaining = [pool.submit(request) for _ in range(3)]
        release.set()
        assert first.result() == {'valid': True}
        assert all(f.result() == {'valid': True} for f in remaining)
    assert len(calls) == 1


def test_file_change_during_collection_is_not_cached(setup):
    app, root, _ = setup
    with app.app_context():
        def changing():
            root.write_text('changed during check')
            return 'old'
        assert cache.cached_pki_read('certs', changing) == 'old'
        assert cache.cached_pki_read('certs', lambda: 'new') == 'new'


def test_apps_do_not_share_results(setup):
    app, _, _ = setup
    other = Flask('other')
    other.config.update(app.config)
    with app.app_context():
        assert cache.cached_pki_read('certs', lambda: 'first-device') == 'first-device'
    with other.app_context():
        assert cache.cached_pki_read('certs', lambda: 'other-device') == 'other-device'


def test_same_size_write_with_identical_metadata_still_invalidates(setup, monkeypatch):
    app, root, _ = setup
    previous = root.lstat()
    original = Path.lstat
    def frozen_metadata(path):
        return previous if path == root else original(path)
    monkeypatch.setattr(Path, 'lstat', frozen_metadata)
    with app.app_context():
        assert cache.cached_pki_read('certs', lambda: 'old') == 'old'
        root.write_text('root-v2')
        assert cache.cached_pki_read('certs', lambda: 'new') == 'new'
