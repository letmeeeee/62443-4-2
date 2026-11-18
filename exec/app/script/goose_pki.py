"""Independent GOOSE file-key PKI, using TLS staging/validate/apply conventions.

Four imported parts: P-256 identity, its private key, CA roots and CRLs. Complete
validated generations are published atomically; no TLS files/services are touched.
Private keys are never returned, exported or logged. No peer certificate pin file.
"""
import contextlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid

from . import pki_common as pki
from . import crl_store
from .custom_pki import Conflict, secure_directory, read

FILES = {'identity': 'enc.crt', 'key': 'enc.key', 'ca': 'ca-roots.crt', 'crl': 'crls.pem'}
DEFAULT_DIRECTORY = '/etc/ems/goose'


def private_key(data):
    if not data or len(data) > 1024 * 1024 or not re.fullmatch(
        rb'\s*-----BEGIN (PRIVATE KEY|EC PRIVATE KEY)-----[A-Za-z0-9+/=\r\n]+-----END \1-----\s*', data
    ):
        raise ValueError('one unencrypted PEM P-256 private key is required (TLS file-key format)')
    key = pki.run('pkey', '-passin', 'pass:', data=data)
    pki.run('pkey', '-check', '-noout', '-passin', 'pass:', data=key)
    public = pki.run('pkey', '-pubout', '-outform', 'DER', '-passin', 'pass:', data=key)
    require_p256(public)
    return key, public


def require_p256(public):
    description = pki.run('pkey', '-pubin', '-inform', 'DER', '-text', '-noout', data=public)
    if b'ASN1 OID: prime256v1' not in description:
        raise ValueError('GOOSE requires an EC prime256v1 (P-256) key')


class GoosePKI:
    def __init__(self, directory=DEFAULT_DIRECTORY):
        self.home = Path(directory)
        if not self.home.is_absolute():
            raise ValueError('GOOSE_PKI_DIR must be absolute')

    @contextlib.contextmanager
    def locked(self):
        secure_directory(self.home, private=True)
        with pki.locked(self.home):
            yield

    def active(self):
        link = self.home / 'current'
        if not link.is_symlink():
            if link.exists():
                raise Conflict('current must be a managed generation link')
            return None
        target = os.readlink(link)
        if not re.fullmatch(r'releases/[0-9a-f]{32}', target):
            raise Conflict('invalid current generation')
        return secure_directory(self.home / target, private=True)

    def batch(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch('[0-9a-f]{32}', identifier):
            raise ValueError('valid batch_id required')
        folder = secure_directory(self.home / 'batches', private=True) / identifier
        if not folder.is_dir() or folder.is_symlink():
            raise ValueError('unknown batch_id')
        secure_directory(folder, private=True)
        return folder, json.loads(read(folder / 'state.json'))

    def save(self, folder, state):
        pki.atomic_write(folder / 'state.json', json.dumps(state).encode())

    def upload(self, part, data, batch_id=None, actor='-'):
        if part not in FILES or not data or len(data) > 1024 * 1024:
            raise ValueError('invalid GOOSE PKI part or size')
        if part == 'key':
            data, _ = private_key(data)
        elif part == 'identity':
            data = b''.join(pki.certificates(data))
            require_p256(pki.public_key(pki.certificates(data)[0]))
        elif part == 'ca':
            data = pki.validate_roots(data)
        else:
            # Full issuer/signature/freshness/rollback verification occurs on apply,
            # so the four parts can be uploaded in any order.
            crl_store._parse(data, allow_der=True)
        with self.locked():
            if batch_id:
                folder, state = self.batch(batch_id)
                if state['status'] != 'staged' or (self.active() and self.active().name == batch_id):
                    raise Conflict('installed batch is immutable; create a new batch')
            else:
                identifier = uuid.uuid4().hex
                parent = secure_directory(self.home / 'batches', private=True)
                folder = secure_directory(parent / identifier, private=True)
                active = self.active()
                state = dict(batch_id=identifier, status='staged', parts=[],
                             base_generation=active.name if active else None, actor=actor)
                # Snapshot the existing generation for partial updates.
                if active:
                    for name in FILES.values():
                        pki.atomic_write(folder / name, read(active / name))
            pki.atomic_write(folder / FILES[part], data)
            state['parts'] = sorted(set(state['parts']) | {part})
            self.save(folder, state)
            return self.public(state)

    @staticmethod
    def public(state):
        return {key: state[key] for key in ('batch_id', 'status', 'parts', 'pending') if key in state}

    def validate(self, folder, previous=None):
        """Validate without altering active files. Match C runtime's strict chain policy."""
        missing = [part for part, name in FILES.items() if not (folder / name).is_file()]
        if missing:
            raise ValueError('missing GOOSE PKI parts: ' + ', '.join(missing))
        roots = pki.validate_roots(read(folder / FILES['ca']))
        certificates = pki.certificates(read(folder / FILES['identity']))
        leaf, chain = certificates[0], b''.join(certificates[1:])
        key, public = private_key(read(folder / FILES['key']))
        if public != pki.public_key(leaf):
            raise ValueError('GOOSE certificate does not match private key')
        if 'CA:FALSE' not in pki.run('x509', '-noout', '-ext', 'basicConstraints', data=leaf).decode():
            raise ValueError('GOOSE identity must declare CA:FALSE')
        if 'Digital Signature' not in pki.run('x509', '-noout', '-ext', 'keyUsage', data=leaf).decode():
            raise ValueError('GOOSE identity requires digitalSignature')
        root_path = folder / FILES['ca']
        crl_data = read(folder / FILES['crl'])
        previous_path = previous / FILES['crl'] if previous else folder / 'no-previous-crl'
        bundle = crl_store.build_bundle(crl_data, chain, root_path, previous_path)
        # Normalize staged inputs only; published generations are immutable.
        pki.atomic_write(root_path, roots)
        pki.atomic_write(folder / FILES['key'], key)
        pki.atomic_write(folder / FILES['crl'], bundle)
        leaf_path = folder / '.verify-leaf.pem'
        chain_path = folder / '.verify-chain.pem'
        pki.atomic_write(leaf_path, leaf)
        pki.atomic_write(chain_path, chain)
        try:
            command = ['verify', '-no-CAfile', '-no-CApath', '-trusted', root_path,
                       '-x509_strict', '-verify_depth', '8', '-purpose', 'any',
                       '-CRLfile', folder / FILES['crl'], '-crl_check_all']
            if chain:
                command += ['-untrusted', chain_path]
            pki.run(*command, leaf_path)
            status = crl_store.certificate_status(leaf + chain, root_path, folder / FILES['crl'])
            if status['revocationStatus'] != 'good':
                raise ValueError('GOOSE revocation validation failed: ' + status['revocationStatus'])
        finally:
            leaf_path.unlink(missing_ok=True)
            chain_path.unlink(missing_ok=True)
        # Keep HELLO/ACK within the fixed 1024-byte limit (72-byte DER signature max).
        der = pki.run('x509', '-outform', 'DER', data=leaf)
        if len(der) + 21 + 5 + 1 + 2 + 65 + 32 + 72 > 1024:
            raise ValueError('GOOSE leaf certificate exceeds GSEC1 handshake size budget')
        return dict(sha256=pki.fingerprint(leaf), revocationStatus='good')

    def apply(self, identifier, service_runner):
        with self.locked():
            folder, state = self.batch(identifier)
            active = self.active()
            if active and active.name == identifier:
                if state['status'] == 'applied':
                    return self.public(state)
                # Recover a crash between publishing current and saving state.
                state['status'] = 'installed'
            elif state['status'] != 'staged':
                raise Conflict('batch was superseded; create a new batch')
            if state['status'] == 'staged':
                if (active.name if active else None) != state['base_generation']:
                    raise Conflict('active GOOSE PKI changed; create a new batch')
                if not state['parts']:
                    raise ValueError('empty batch')
                self.validate(folder, active)
                releases = secure_directory(self.home / 'releases', private=True)
                release = releases / identifier
                # A prior interrupted copy was never published and may be replaced safely.
                if release.exists():
                    secure_directory(release, private=True)
                    shutil.rmtree(release)
                secure_directory(release, private=True)
                for part, name in FILES.items():
                    pki.atomic_write(release / name, read(folder / name), 0o600 if part == 'key' else 0o644)
                temporary = self.home / ('.current-' + uuid.uuid4().hex)
                try:
                    temporary.symlink_to('releases/' + identifier)
                    os.replace(temporary, self.home / 'current')
                    descriptor = os.open(self.home, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
                finally:
                    temporary.unlink(missing_ok=True)
                state['status'] = 'installed'
            state['pending'] = ['goose']
            self.save(folder, state)
            try:
                service_runner('goose')
            except (OSError, subprocess.SubprocessError):
                self.save(folder, state)
            else:
                state.update(status='applied', pending=[])
                self.save(folder, state)
            return self.public(state)

    def status(self, identifier=None):
        with self.locked():
            if identifier:
                _, state = self.batch(identifier)
                active = self.active()
                if active and active.name == identifier and state['status'] == 'staged':
                    state.update(status='installed', pending=['goose'])
                return self.public(state)
            active = self.active()
            if not active:
                return dict(installed=False)
            certificate = pki.certificates(read(active / FILES['identity']))[0]
            return dict(installed=True, generation=active.name,
                        sha256=pki.fingerprint(certificate),
                        crls=crl_store.inventory(dict(ca_file=active / FILES['ca'], crl_file=active / FILES['crl'])))
