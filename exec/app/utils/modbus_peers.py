"""Read the logger's bounded, read-only Modbus TLS peer snapshot."""
import json
import os
from pathlib import Path
import re
import stat
import time

from flask import current_app

MAX_SNAPSHOT_BYTES = 1024 * 1024
MAX_CERTIFICATE_BYTES = 64 * 1024
MAX_PEERS = 256
MAX_AGE_SECONDS = 5


def _read_file(directory, name, limit):
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        metadata = os.fstat(descriptor)
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit or
                metadata.st_mode & 0o022):
            raise ValueError('Invalid peer state file')
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError('Peer state file too large')
        return data
    finally:
        os.close(descriptor)


def _producer_alive(pid, start_ticks):
    if type(pid) is not int or pid <= 0 or not isinstance(start_ticks, str):
        return False
    try:
        # Field 2 may contain spaces/parentheses; remaining fields begin with state (3).
        fields = Path('/proc/{}/stat'.format(pid)).read_text().rsplit(')', 1)[1].split()
        return fields[0] not in ('Z', 'X') and fields[19] == start_ticks
    except (OSError, IndexError):
        return False


def _unavailable(reason):
    return dict(ok=True, data=[], liveAuthenticationTelemetryAvailable=False,
                reason=reason, scope='modbus-tls-active-connections')


def peer_status():
    """Certificates describe active authenticated TLS connections, never historic trust."""
    path = (current_app.config.get('MODBUS_PEER_STATE_DIR') or
            os.environ.get('MODBUS_PEER_STATE_DIR') or '/run/lc400/modbus-peers')
    directory = None
    try:
        directory = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        if os.fstat(directory).st_mode & 0o022:
            raise ValueError('Writable peer state directory')
        snapshot = json.loads(_read_file(directory, 'status.json', MAX_SNAPSHOT_BYTES))
        if not isinstance(snapshot, dict) or snapshot.get('schemaVersion') != 1:
            raise ValueError('Invalid peer state schema')
        heartbeat = snapshot.get('heartbeatMonotonic')
        if type(heartbeat) not in (int, float):
            raise ValueError('Invalid peer heartbeat')
        age = time.monotonic() - heartbeat
        if not 0 <= age <= MAX_AGE_SECONDS:
            return _unavailable('PEER_STATE_STALE')
        if not _producer_alive(snapshot.get('producerPid'), snapshot.get('producerStartTicks')):
            return _unavailable('PEER_PRODUCER_UNAVAILABLE')
        if snapshot.get('tlsEnabled') is not True:
            return _unavailable('TLS_DISABLED')
        if snapshot.get('complete') is not True:
            return _unavailable('PEER_COLLECTION_INCOMPLETE')
        entries = snapshot.get('peers')
        instance = snapshot.get('instanceId')
        if not isinstance(instance, str) or not re.fullmatch(r'[0-9]+-[0-9]+-[0-9]+', instance):
            raise ValueError('Invalid peer instance')
        if not isinstance(entries, list) or len(entries) > MAX_PEERS:
            raise ValueError('Invalid peer list')
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes
        data = []
        seen = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError('Invalid peer entry')
            identifier = entry.get('connectionId')
            if (not isinstance(identifier, str) or
                    not re.fullmatch(re.escape(instance) + r'-[1-9][0-9]*', identifier) or
                    identifier in seen):
                raise ValueError('Invalid peer connection identifier')
            seen.add(identifier)
            name = entry.get('certificateFile')
            if name != 'peer-' + identifier + '.pem':
                raise ValueError('Invalid peer certificate reference')
            if (entry.get('localRole') not in ('master', 'slave') or
                    entry.get('connectionStatus') != 'connected' or
                    entry.get('authenticationStatus') != 'verified' or
                    entry.get('transport') != 'tls' or
                    not isinstance(entry.get('peerIp'), str) or
                    type(entry.get('peerPort')) is not int or not 1 <= entry['peerPort'] <= 65535):
                raise ValueError('Invalid peer connection state')
            certificate = x509.load_pem_x509_certificate(_read_file(directory, name, MAX_CERTIFICATE_BYTES))
            if hasattr(certificate, 'not_valid_before_utc'):
                start, end = certificate.not_valid_before_utc, certificate.not_valid_after_utc
            else:
                from datetime import timezone
                start = certificate.not_valid_before.replace(tzinfo=timezone.utc)
                end = certificate.not_valid_after.replace(tzinfo=timezone.utc)
            item = {key: entry.get(key) for key in (
                'connectionId', 'localRole', 'peerIp', 'peerPort', 'transport',
                'connectionStatus', 'authenticationStatus', 'connectedAt',
            )}
            item['peerCertificate'] = dict(
                sha256=certificate.fingerprint(hashes.SHA256()).hex(),
                subject=certificate.subject.rfc4514_string(),
                issuer=certificate.issuer.rfc4514_string(),
                notBefore=start.isoformat(), notAfter=end.isoformat(),
            )
            data.append(item)
        # A concurrent close may remove a PEM between atomic snapshot publications.
        # Such read races return unavailable rather than stale authenticated identities.
        return dict(ok=True, data=data, liveAuthenticationTelemetryAvailable=True,
                    sampledAt=snapshot.get('updatedAt'), scope='modbus-tls-active-connections')
    except FileNotFoundError:
        return _unavailable('PEER_STATE_UNAVAILABLE')
    except ImportError:
        return _unavailable('PEER_CERTIFICATE_READER_UNAVAILABLE')
    except (OSError, ValueError, TypeError, UnicodeError):
        return _unavailable('PEER_STATE_INVALID')
    finally:
        if directory is not None:
            os.close(directory)
