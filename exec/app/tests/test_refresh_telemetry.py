"""Refresh requests share expensive samples without caching authorization."""
from concurrent.futures import ThreadPoolExecutor
import threading

from flask import Flask
import pytest

from utils import system_usage
from utils.public_read_cache import cached_public_read


def test_cpu_concurrent_queries_share_sample_and_expire(monkeypatch):
    clock = [10.0]
    calls = []
    monkeypatch.setattr(system_usage, '_cpu_sample', None)
    monkeypatch.setattr(system_usage.time, 'monotonic', lambda: clock[0])
    def measure():
        calls.append(1)
        return dict(usedPercent=25, sampleSeconds=0.2)
    monkeypatch.setattr(system_usage, '_measure_cpu_usage', measure)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: system_usage.cpu_usage(), range(16)))
    assert len(calls) == 1
    results[0]['usedPercent'] = 100
    assert system_usage.cpu_usage()['usedPercent'] == 25
    clock[0] += 1.1
    system_usage.cpu_usage()
    assert len(calls) == 2


def test_cpu_failure_is_not_cached(monkeypatch):
    monkeypatch.setattr(system_usage, '_cpu_sample', None)
    monkeypatch.setattr(system_usage, '_measure_cpu_usage', lambda: (_ for _ in ()).throw(ValueError()))
    with pytest.raises(ValueError):
        system_usage.cpu_usage()
    monkeypatch.setattr(system_usage, '_measure_cpu_usage', lambda: {'usedPercent': 5})
    assert system_usage.cpu_usage()['usedPercent'] == 5


def test_public_collection_shared_expiring_and_isolated(monkeypatch):
    from utils import public_read_cache as cache
    clock = [20.0]
    monkeypatch.setattr(cache.time, 'monotonic', lambda: clock[0])
    app = Flask(__name__)
    calls = []
    barrier = threading.Barrier(8)
    def collect():
        calls.append(1)
        return {'rulesAvailable': True, 'interfacesAvailable': True, 'rules': [1]}
    def read(_):
        with app.app_context():
            barrier.wait()
            return cached_public_read('network', collect)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(read, range(8)))
    assert len(calls) == 1
    results[0]['rules'].append(2)
    with app.app_context():
        assert cached_public_read('network', collect)['rules'] == [1]
        clock[0] += 2.1
        cached_public_read('network', collect)
    assert len(calls) == 2
    with Flask('other').app_context():
        cached_public_read('network', collect)
    assert len(calls) == 3


def test_incomplete_collection_is_retried():
    calls = []
    def collect():
        calls.append(1)
        return {'rulesAvailable': False}
    with Flask(__name__).app_context():
        cached_public_read('network', collect)
        cached_public_read('network', collect)
    assert len(calls) == 2
