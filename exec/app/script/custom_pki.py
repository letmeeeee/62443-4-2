"""External file-key PKI: private staging batches, validation, journaled installation.

No CSR is read or generated here. OpenSSL and the existing PKI policy validate
the imported identity. This module never starts services without an explicit
apply call and a service callback supplied by the HTTP layer.
"""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import uuid

try:
    from . import pki_common as pki
    from .https_config import read_device_ips
    from .modbus_certs import locked as modbus_locked
except ImportError:
    import pki_common as pki
    from https_config import read_device_ips
    from modbus_certs import locked as modbus_locked

ROLES = ('master', 'slave', 'https')
PARTS = ('key', 'chain', 'identity')
LIMIT = 1024 * 1024


class Conflict(ValueError):
    """A batch needs recovery, is immutable, or no longer matches live files."""


def secure_directory(path, private=False):
    path = Path(path)
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ValueError('symbolic link directory rejected')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if info.st_uid != os.geteuid() or info.st_mode & (0o077 if private else 0o022):
        raise ValueError('directory ownership/permissions are unsuitable')
    return path


def read(path, optional=False):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('symbolic link file rejected')
    if optional and not path.exists():
        return None
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > LIMIT or info.st_uid != os.geteuid():
        raise ValueError('file ownership/type/size is unsuitable')
    return path.read_bytes()


def private_key(data):
    if not data or len(data) > LIMIT or not re.fullmatch(
        rb'\s*-----BEGIN (PRIVATE KEY|RSA PRIVATE KEY)-----[A-Za-z0-9+/=\r\n]+-----END \1-----\s*', data
    ):
        raise ValueError('one unencrypted PEM RSA private key is required')
    normalized = pki.run('pkey', '-passin', 'pass:', data=data)
    public = pki.run('pkey', '-pubout', '-outform', 'DER', '-passin', 'pass:', data=normalized)
    # Inspect the SPKI AlgorithmIdentifier, not the certificate's CA signature
    # algorithm. RSA-PSS keys also pass `openssl rsa -check` and have RSA bit sizes,
    # but the Modbus file backend accepts only rsaEncryption (ordinary RSA).
    description = pki.run('asn1parse', '-inform', 'DER', data=public)
    algorithm = re.search(
        rb'^\s*\d+:d=2\s+hl=\d+\s+l=\s*\d+\s+prim:\s+OBJECT\s*:([^\r\n]+)',
        description, re.M,
    )
    oid = algorithm.group(1).strip() if algorithm else None
    if oid != b'rsaEncryption':
        kind = 'RSA-PSS' if oid == b'rsassaPss' else 'non-RSA or unrecognized'
        raise ValueError(kind + ' private key rejected; only ordinary RSA-2048/3072 is supported')
    pki.run('rsa', '-check', '-noout', '-passin', 'pass:', data=normalized)
    description = pki.run('pkey', '-text_pub', '-noout', '-passin', 'pass:', data=normalized)
    if not re.search(rb'Public-Key:\s*\((2048|3072) bit\)', description):
        raise ValueError('private key must be RSA-2048 or RSA-3072')
    return normalized, public


def fingerprints(data):
    return sorted(pki.fingerprint(cert) for cert in pki.certificates(data))


def digest(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def stage_crls(settings, data, chain):
    """Called under the global lock by the existing CRL upload endpoint.

    Only explicitly pinned staged roots can authorize deferred CRLs. Attach to
    every matching staged batch, never promote an uploaded issuer to a root.
    """
    try:
        from . import crl_store
    except ImportError:
        import crl_store
    home = settings['ca_file'].parent / '.custom-pki'
    if (home / 'recovery.json').exists():
        raise Conflict('unfinished installation; recover before importing CRLs')
    parent = home / 'batches'
    if not parent.exists():
        return None
    secure_directory(home, private=True)
    secure_directory(parent, private=True)
    matches = []
    for directory in parent.iterdir():
        secure_directory(directory, private=True)
        state = json.loads(read(directory / 'state.json'))
        if state.get('pki_mode') == 'custom':
            state['pki_mode'] = 'trina'
        if state['status'] != 'staged' or not state.get('ca'):
            continue
        try:
            previous = directory / 'crls.pem'
            baseline = previous if previous.exists() else settings['crl_file']
            bundle = crl_store.build_bundle(data, chain, directory / 'roots.pem', baseline)
        except ValueError:
            continue
        matches.append((directory, state, bundle))
    if not matches:
        return None
    for directory, state, bundle in matches:
        pki.atomic_write(directory / 'crls.pem', bundle, 0o644)
        state['crl'] = True
        pki.atomic_write(directory / 'state.json', json.dumps(state).encode())
    first = matches[0][0]
    inventory_settings = dict(settings, ca_file=first / 'roots.pem', crl_file=first / 'crls.pem')
    return dict(imported=True, restart_required=True, crls=crl_store.inventory(inventory_settings), staged=True,
                batch_ids=[state['batch_id'] for _, state, _ in matches])


class CustomPKI:
    def __init__(self, config, modbus_dir, https_dir, backend='file'):
        self.settings = pki.read_config(config)
        self.modbus = Path(modbus_dir).absolute()
        self.https = Path(https_dir).absolute()
        self.backend = backend
        if backend not in ('file', 'tee'):
            raise ValueError('unknown Modbus key backend')
        self.home = self.settings['ca_file'].parent / '.custom-pki'
        self.guard = self.home / 'recovery.json'

    @contextlib.contextmanager
    def locked(self, recovery=False):
        secure_directory(self.settings['ca_file'].parent)
        with pki.operation_lock(self.settings):
            secure_directory(self.home, private=True)
            if not recovery and (self.guard.exists() or self.guard.is_symlink()):
                raise Conflict('unfinished installation; run custom_pki.py recover before continuing')
            yield

    def batch(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch('[0-9a-f]{32}', identifier):
            raise ValueError('valid batch_id required')
        directory = self.home / 'batches' / identifier
        if not directory.is_dir():
            raise ValueError('batch not found')
        secure_directory(directory, private=True)
        state = json.loads(read(directory / 'state.json'))
        # Keep historical batch files usable; no deletion or identity rewrite.
        if state.get('pki_mode') == 'custom':
            state['pki_mode'] = 'trina'
        return directory, state

    def save(self, directory, state):
        pki.atomic_write(directory / 'state.json', json.dumps(state).encode())

    def baseline(self):
        return {name: digest(read(path, optional=True)) for name, path in self.registry().items()
                if not name.startswith('pending.') and name not in ('https.reload', 'https.renewal')
                and not name.endswith('.csr') and name != 'crl'}

    def paths(self, role):
        directory = self.https if role == 'https' else self.modbus
        stem = 'g3' if role == 'https' else role
        paths = {part: directory / (stem + suffix) for part, suffix in (
            ('key', '.key'), ('identity', '.crt'), ('chain', '.intermediates.pem'), ('csr', '.csr')
        )}
        paths['source'] = pki.identity_source_path(directory, role)
        return paths

    def upload(self, part, data, role=None, batch_id=None, expected=(), actor='-'):
        if part not in (*PARTS, 'ca') or (part != 'ca' and role not in ROLES):
            raise ValueError('invalid material kind or role')
        if part != 'ca' and role != 'https' and self.backend != 'file':
            raise ValueError('external Modbus private identities require the file backend')
        if len(data) > LIMIT:
            raise ValueError('upload exceeds 1 MiB')
        if part == 'key':
            data, _ = private_key(data)
        elif part == 'ca':
            data = pki.validate_roots(data)
            wanted = [value.replace(':', '').strip().upper() for value in expected]
            if not wanted or any(not re.fullmatch('[0-9A-F]{64}', value) for value in wanted):
                raise ValueError('full trusted-channel CA SHA-256 fingerprints required')
            if set(wanted) != set(fingerprints(data)):
                raise ValueError('CA root fingerprints do not match')
        elif part == 'identity':
            certificates = pki.certificates(data)
            if len(certificates) != 1:
                raise ValueError('upload one leaf certificate; use the separate chain endpoint')
            data = certificates[0]
            if 'CA:FALSE' not in pki.run('x509', '-noout', '-ext', 'basicConstraints', data=data).decode():
                raise ValueError('leaf certificate must explicitly declare CA:FALSE')
        elif data:
            certificates = pki.certificates(data)
            for cert in certificates:
                pki.check_ca(cert)
                subject = pki.run('x509', '-subject', '-noout', '-nameopt', 'RFC2253', data=cert).partition(b'=')[2].strip()
                issuer = pki.run('x509', '-issuer', '-noout', '-nameopt', 'RFC2253', data=cert).partition(b'=')[2].strip()
                if subject == issuer:
                    raise ValueError('root certificates belong in the CA endpoint, not the intermediate chain')
            data = b''.join(certificates)
        with self.locked():
            if batch_id is None:
                parent = secure_directory(self.home / 'batches', private=True)
                batch_id = uuid.uuid4().hex
                directory = secure_directory(parent / batch_id, private=True)
                state = dict(batch_id=batch_id, pki_mode='trina', status='staged', roles={}, ca=False,
                             created_by=actor, base_hashes=self.baseline())
            else:
                directory, state = self.batch(batch_id)
            if state['status'] != 'staged':
                raise Conflict('installed batches are immutable; create a new batch')
            name = 'roots.pem' if part == 'ca' else role + '.' + part
            pki.atomic_write(directory / name, data)
            if part == 'ca':
                state['ca'] = True
                state['fingerprints'] = fingerprints(data)
            else:
                state['roles'][role] = sorted(set(state['roles'].get(role, [])) | {part})
            state['updated_by'] = actor
            self.save(directory, state)
            return state

    def status(self, identifier):
        with self.locked():
            directory, state = self.batch(identifier)
            self.refresh_services(directory, state)
            return state

    def refresh_services(self, directory, state):
        if state['status'] != 'installed':
            return
        if any(digest(read(self.registry()[label], optional=True)) != expected
               for label, expected in state['active_hashes'].items()):
            return
        for service in list(state['pending']):
            if not pki.pending_path(self.settings, service).exists():
                state['services'][service] = 'success'
                state['pending'].remove(service)
        state['status'] = 'installed' if state['pending'] else 'applied'
        self.save(directory, state)

    def sync_service_states(self):
        """Caller holds the global operation lock (legacy service apply)."""
        parent = self.home / 'batches'
        if not parent.exists():
            return
        secure_directory(parent, private=True)
        for entry in parent.iterdir():
            directory, state = self.batch(entry.name)
            self.refresh_services(directory, state)

    def validate_role(self, role, key, certificate, chain, roots, crl_path=None):
        normalized, public = private_key(key)
        leaf, intermediates = pki.validate_identity(
            certificate, chain or None, roots, 'sslclient' if role == 'master' else 'sslserver',
            csr=None, crl_path=crl_path or self.settings['crl_file'], require_fresh_crl=True,
        )
        if pki.public_key(leaf) != public:
            raise ValueError('certificate does not match private key: ' + role)
        cn = pki.subject_cn(leaf)
        sans = pki.san_values(leaf)
        if role == 'https':
            expected = {('IP', value) for value in read_device_ips(self.settings['config_file'])}
            if not cn.startswith('LC400-') or not expected.issubset(sans):
                raise ValueError('HTTPS CN/SAN does not match current device configuration')
        elif not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', cn):
            raise ValueError('invalid Modbus identity CN')
        elif role == 'slave' and not any(kind == 'IP' for kind, _ in sans):
            raise ValueError('slave identity requires an IP SAN')
        return normalized, leaf + intermediates, intermediates, public

    def prepare(self, directory, state):
        """Validate selected identities and all active identities affected by root replacement."""
        updates, services, public_keys = {}, set(), {}
        if state.get('base_hashes') is not None and state['base_hashes'] != self.baseline():
            raise Conflict('live PKI changed since this batch was created; create a new batch')
        roots_data = read(directory / 'roots.pem') if state['ca'] else read(self.settings['ca_file'])
        pki.validate_roots(roots_data)
        root_changed = state['ca'] and roots_data != read(self.settings['ca_file'], optional=True)
        if root_changed:
            updates['ca'] = (self.settings['ca_file'], roots_data, 0o644)
        crl_path = directory / 'crls.pem' if state.get('crl') else self.settings['crl_file']
        with tempfile.TemporaryDirectory(prefix='verify-', dir=self.home) as temporary:
            roots = Path(temporary) / 'roots.pem'
            pki.atomic_write(roots, roots_data, 0o644)
            if state.get('crl'):
                try:
                    from . import crl_store
                except ImportError:
                    import crl_store
                bundle = crl_store.build_bundle(read(crl_path), b'', roots,
                                               self.settings['crl_file'], retained_bundle=True)
                crl_path = Path(temporary) / 'crls.pem'
                pki.atomic_write(crl_path, bundle, 0o644)
                updates['crl'] = (self.settings['crl_file'], bundle, 0o644)
            for role in ROLES:
                paths = self.paths(role)
                selected = role in state['roles']
                certificate = read(paths['identity'], optional=True)
                if not selected and (not root_changed or certificate is None):
                    # Still prevent cross-role key reuse, without changing unrelated validation rules.
                    key = read(paths['key'], optional=True)
                    if key is not None:
                        _, public_keys[role] = private_key(key)
                    continue
                if role != 'https' and self.backend != 'file':
                    raise ValueError('root replacement affecting active TEE identities is unsupported')
                parts = state['roles'].get(role, [])
                key = read(directory / (role + '.key')) if 'key' in parts else read(paths['key'])
                if 'chain' in parts:
                    chain = read(directory / (role + '.chain'))
                elif certificate is not None:
                    # A new leaf upload must not discard an unchanged, already installed chain.
                    chain = b''.join(pki.certificates(certificate)[1:])
                else:
                    chain = read(paths['chain'], optional=True) or b''
                if 'identity' in parts:
                    certificate = read(directory / (role + '.identity'))
                if certificate is None:
                    raise ValueError('leaf certificate missing for ' + role)
                certificates = pki.certificates(certificate)
                # A directly-root-signed replacement needs no inherited old chain.
                if 'identity' in parts and 'chain' not in parts and chain:
                    try:
                        with tempfile.TemporaryDirectory(prefix='direct-', dir=self.home) as direct:
                            leaf_path = Path(direct) / 'leaf.pem'
                            leaf_path.write_bytes(certificates[0])
                            pki.run('verify', '-no-CAfile', '-no-CApath', '-trusted', roots, leaf_path)
                        chain = b''
                    except ValueError:
                        pass
                try:
                    key, fullchain, chain, public = self.validate_role(
                        role, key, certificates[0], chain, roots, crl_path)
                except ValueError as error:
                    raise ValueError('role=' + role + ': ' + str(error)
                                     + '; chain_source=' + ('batch' if 'chain' in parts else 'active')) from error
                public_keys[role] = public
                service = 'nginx' if role == 'https' else 'tems'
                services.add(service)
                if selected:
                    for part, data, mode in (('key', key, 0o600), ('identity', fullchain, 0o644),
                                             ('chain', chain, 0o644), ('csr', None, 0o644)):
                        updates[role + '.' + part] = (paths[part], data, mode)
                    marker = json.dumps(dict(pki_mode='trina', role=role, batch_id=state['batch_id'])).encode()
                    updates[role + '.source'] = (paths['source'], marker, 0o600)
            if len(set(public_keys.values())) != len(public_keys):
                raise ValueError('master, slave and HTTPS must use independent private keys')
        if not updates:
            raise ValueError('batch has no identity or changed CA to install')
        for service in services:
            marker = json.dumps(dict(reason='custom-pki', batch_id=state['batch_id'])).encode()
            updates['pending.' + service] = (pki.pending_path(self.settings, service), marker, 0o600)
        if 'https' in state['roles']:
            updates['https.reload'] = (self.https / '.reload-required', b'External identity imported\n', 0o600)
            updates['https.renewal'] = (self.https / 'renewal-status.json', None, 0o644)
        return updates, sorted(services)

    def registry(self):
        paths = {'ca': self.settings['ca_file'], 'crl': self.settings['crl_file']}
        for role in ROLES:
            paths.update({role + '.' + part: path for part, path in self.paths(role).items()})
        paths.update({'pending.' + service: pki.pending_path(self.settings, service) for service in ('nginx', 'tems')})
        paths.update({'https.reload': self.https / '.reload-required', 'https.renewal': self.https / 'renewal-status.json'})
        return paths

    def restore(self, record):
        if not re.fullmatch('[0-9a-f]{32}', record['backup_id']):
            raise ValueError('invalid recovery backup')
        backup = secure_directory(self.home / 'backups' / record['backup_id'], private=True)
        registry = self.registry()
        for label, item in record['files'].items():
            path = registry[label]
            if path.is_symlink():
                raise ValueError('recovery target is a symbolic link')
            if item['exists']:
                pki.atomic_write(path, read(backup / label), item['mode'])
            else:
                path.unlink(missing_ok=True)

    def install(self, directory, state, updates, services):
        backup_id = uuid.uuid4().hex
        parent = secure_directory(self.home / 'backups', private=True)
        backup = secure_directory(parent / backup_id, private=True)
        record = dict(batch_id=state['batch_id'], backup_id=backup_id, files={})
        for label, (path, _, _) in updates.items():
            secure_directory(path.parent)
            old = read(path, optional=True)
            mode = stat.S_IMODE(path.stat().st_mode) if old is not None else 0o600
            record['files'][label] = dict(exists=old is not None, mode=mode)
            if old is not None:
                pki.atomic_write(backup / label, old)
        pki.atomic_write(backup / 'recovery.json', json.dumps(record).encode())
        pki.atomic_write(self.guard, json.dumps(record).encode())
        try:
            for path, data, mode in updates.values():
                if data is None:
                    path.unlink(missing_ok=True)
                else:
                    pki.atomic_write(path, data, mode)
            state.update(status='installed', backup_id=backup_id, pending=services, services={})
            state['active_hashes'] = {label: digest(data) for label, (_, data, _) in updates.items()
                                      if not label.startswith('pending.') and label not in ('https.reload', 'https.renewal')
                                      and not label.endswith('.csr')}
            # Also bind retries to the root used for validation when no root was uploaded/changed.
            state['active_hashes']['ca'] = digest(read(self.settings['ca_file']))
            state['active_hashes']['crl'] = digest(read(self.settings['crl_file'], optional=True))
            self.save(directory, state)
            self.guard.unlink()
        except BaseException:
            self.restore(record)
            for name in ('backup_id', 'pending', 'services', 'active_hashes'):
                state.pop(name, None)
            state['status'] = 'staged'
            self.save(directory, state)
            self.guard.unlink()
            raise

    def apply(self, identifier, service_runner):
        with self.locked():
            directory, state = self.batch(identifier)
            self.refresh_services(directory, state)
            if state['status'] == 'staged':
                secure_directory(self.modbus)
                secure_directory(self.https)
                # Same order as import tools: global operation lock, then identity directory locks.
                with modbus_locked(self.modbus), pki.locked(self.https):
                    updates, services = self.prepare(directory, state)
                    self.install(directory, state, updates, services)
            else:
                for label, expected in state['active_hashes'].items():
                    if digest(read(self.registry()[label], optional=True)) != expected:
                        raise Conflict('active identity changed after installation; create a new batch')
            # Release directory locks before invoking HTTPS reconciliation; keep the global lock.
            for service in list(state['pending']):
                try:
                    service_runner(service)
                except (OSError, subprocess.SubprocessError):
                    state['services'][service] = 'failed'
                else:
                    state['services'][service] = 'success'
                    state['pending'].remove(service)
                    pki.pending_path(self.settings, service).unlink(missing_ok=True)
                self.save(directory, state)
            state['status'] = 'applied' if not state['pending'] else 'installed'
            self.save(directory, state)
            return state

    def recover(self):
        """Offline recovery only; never start services with automatically restored old credentials."""
        with self.locked(recovery=True):
            record = json.loads(read(self.guard))
            directory, state = self.batch(record['batch_id'])
            secure_directory(self.modbus)
            secure_directory(self.https)
            with modbus_locked(self.modbus), pki.locked(self.https):
                self.restore(record)
                for name in ('backup_id', 'pending', 'services', 'active_hashes'):
                    state.pop(name, None)
                state['status'] = 'staged'
                self.save(directory, state)
                self.guard.unlink()
            return dict(recovered=True, batch_id=record['batch_id'])


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Offline custom PKI recovery; stop affected services first.')
    parser.add_argument('command', choices=['recover'])
    parser.add_argument('--config', default=os.environ.get('LC_INI_PATH', pki.DEFAULT_CONFIG))
    parser.add_argument('--modbus-dir', default='/etc/ems/modbus')
    parser.add_argument('--https-dir', default='/etc/ssl/g3')
    arguments = parser.parse_args()
    print(json.dumps(CustomPKI(arguments.config, arguments.modbus_dir, arguments.https_dir).recover()))
