"""Peer telemetry endpoint uses real temporary certificates, no device dependencies."""
import json
import os
from pathlib import Path
import time

import pytest
from test_auth_session import auth_app, login
from test_security_center import security_app
from test_certificate_self_test import identity


@pytest.fixture
def peer_fixture(identity, tmp_path):
    app, certs, _ = identity
    directory = tmp_path / 'peer-state'
    directory.mkdir(mode=0o750)
    app.config['MODBUS_PEER_STATE_DIR'] = str(directory)
    instance = '{}-1-1'.format(os.getpid())
    identifier = instance + '-1'
    name = 'peer-' + identifier + '.pem'
    (directory / name).write_bytes((certs / 'g3.crt').read_bytes())
    (directory / name).chmod(0o640)
    ticks = Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()[19]
    state = dict(schemaVersion=1, instanceId=instance, producerPid=os.getpid(),
                 producerStartTicks=ticks, updatedAt='2026-11-11T10:00:00Z',
                 heartbeatMonotonic=time.monotonic(), tlsEnabled=True, complete=True,
                 peers=[dict(connectionId=identifier, localRole='master', peerIp='192.0.2.10',
                             peerPort=502, transport='tls', connectionStatus='connected',
                             authenticationStatus='verified', connectedAt='2026-11-11T09:59:00Z',
                             certificateFile=name)])
    def save():
        (directory / 'status.json').write_text(json.dumps(state))
        (directory / 'status.json').chmod(0o640)
    save()
    client = app.test_client()
    login(client, 'admin')
    return client, directory, state, save


def test_authenticated_peer_returns_public_identity(peer_fixture):
    client, _, _, _ = peer_fixture
    response = client.get('/api/security/peer-status')
    assert response.status_code == 200
    data = response.json
    assert data['liveAuthenticationTelemetryAvailable'] is True
    assert data['scope'] == 'modbus-tls-active-connections'
    peer = data['data'][0]
    assert peer['peerIp'] == '192.0.2.10' and peer['peerPort'] == 502
    assert peer['authenticationStatus'] == 'verified'
    assert len(peer['peerCertificate']['sha256']) == 64
    assert peer['peerCertificate']['subject'] == 'CN=test'
    assert 'certificateFile' not in peer
    assert 'PRIVATE KEY' not in response.get_data(as_text=True)


def test_no_connections_is_available_empty_list(peer_fixture):
    client, _, state, save = peer_fixture
    state['peers'] = []
    save()
    data = client.get('/api/security/peer-status').json
    assert data['liveAuthenticationTelemetryAvailable'] is True and data['data'] == []


@pytest.mark.parametrize('field,value,reason', [
    ('heartbeatMonotonic', -100, 'PEER_STATE_STALE'),
    ('heartbeatMonotonic', 1e30, 'PEER_STATE_STALE'),
    ('producerStartTicks', 'invalid', 'PEER_PRODUCER_UNAVAILABLE'),
    ('producerPid', 0, 'PEER_PRODUCER_UNAVAILABLE'),
    ('tlsEnabled', False, 'TLS_DISABLED'),
    ('complete', False, 'PEER_COLLECTION_INCOMPLETE'),
    ('schemaVersion', 2, 'PEER_STATE_INVALID'),
    ('peers', {}, 'PEER_STATE_INVALID'),
])
def test_invalid_or_stale_source_never_shows_online(peer_fixture, field, value, reason):
    client, _, state, save = peer_fixture
    state[field] = value
    save()
    data = client.get('/api/security/peer-status').json
    assert data['data'] == [] and data['liveAuthenticationTelemetryAvailable'] is False
    assert data['reason'] == reason


@pytest.mark.parametrize('condition', ['missing', 'invalid', 'symlink', 'reference', 'duplicate'])
def test_unreadable_or_invalid_peer_certificate_is_unavailable(peer_fixture, condition):
    client, directory, state, save = peer_fixture
    path = directory / state['peers'][0]['certificateFile']
    if condition == 'missing':
        path.unlink()
    elif condition == 'invalid':
        path.write_bytes(b'not a certificate')
    elif condition == 'symlink':
        original = directory / 'original.pem'
        path.rename(original)
        path.symlink_to(original)
    elif condition == 'reference':
        state['peers'][0]['certificateFile'] = '../outside.pem'
    else:
        state['peers'].append(dict(state['peers'][0]))
    save()
    data = client.get('/api/security/peer-status').json
    assert data['data'] == [] and data['liveAuthenticationTelemetryAvailable'] is False


def test_closed_peer_not_returned_from_old_certificate(peer_fixture):
    client, directory, state, save = peer_fixture
    # Independent live entries may share certificate contents; deleting one does not hide another.
    first = state['peers'][0]
    second = dict(first, connectionId=state['instanceId']+'-2',
                  certificateFile='peer-'+state['instanceId']+'-2.pem')
    (directory / second['certificateFile']).write_bytes((directory / first['certificateFile']).read_bytes())
    (directory / second['certificateFile']).chmod(0o640)
    state['peers'].append(second)
    save()
    assert len(client.get('/api/security/peer-status').json['data']) == 2
    (directory / first['certificateFile']).unlink()
    state['peers'] = [second]
    save()
    peers = client.get('/api/security/peer-status').json['data']
    assert len(peers) == 1 and peers[0]['connectionId'] == second['connectionId']


def test_no_publisher_or_bad_snapshot(peer_fixture):
    client, directory, _, _ = peer_fixture
    (directory / 'status.json').unlink()
    assert client.get('/api/security/peer-status').json['reason'] == 'PEER_STATE_UNAVAILABLE'
    (directory / 'status.json').write_text('{')
    (directory / 'status.json').chmod(0o640)
    assert client.get('/api/security/peer-status').json['reason'] == 'PEER_STATE_INVALID'


@pytest.mark.parametrize('target', ['directory', 'snapshot', 'certificate'])
def test_writable_state_is_not_treated_as_authenticated(peer_fixture, target):
    client, directory, state, _ = peer_fixture
    path = directory if target == 'directory' else directory / (
        'status.json' if target == 'snapshot' else state['peers'][0]['certificateFile']
    )
    path.chmod(0o770 if target == 'directory' else 0o660)
    assert client.get('/api/security/peer-status').json['reason'] == 'PEER_STATE_INVALID'


def test_low_role_cannot_read_peer_certificates(peer_fixture):
    client, _, _, _ = peer_fixture
    # Use a separate client so login/CSRF behavior does not affect the role check.
    other = client.application.test_client()
    login(other, 'alice')
    assert other.get('/api/security/peer-status').status_code == 403
