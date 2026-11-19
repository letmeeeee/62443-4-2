"""Short-lived, per-app cache for expensive public telemetry only."""
import copy
import threading
import time

from flask import current_app


_setup_lock = threading.Lock()


def cached_public_read(key, collect, ttl=2.0):
    # Never store responses, users, authorization decisions or request metadata.
    with _setup_lock:
        cache = current_app.extensions.setdefault('public_telemetry_cache', {})
        entry = cache.setdefault(key, {'lock': threading.Lock()})
    with entry['lock']:
        now = time.monotonic()
        if 'value' in entry and 0 <= now - entry['sampled_at'] < ttl:
            return copy.deepcopy(entry['value'])
        value = collect()
        # Exceptions and incomplete network collections are retried next time.
        if all(value.get(field, True) for field in ('rulesAvailable', 'interfacesAvailable')):
            entry.update(value=copy.deepcopy(value), sampled_at=time.monotonic())
        return value
