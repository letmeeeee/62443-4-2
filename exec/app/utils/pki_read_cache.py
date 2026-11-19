"""Short, file-versioned cache of public PKI read results; no private key bytes."""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import stat
from threading import RLock
from time import monotonic, time

from flask import current_app

TTL_SECONDS = 2.0


def _version():
    import config
    from script import pki_common as pki

    settings = pki.read_config(config.INI_PATH)
    modbus = Path(current_app.config.get('MODBUS_CERT_DIR', '/etc/ems/modbus'))
    https = Path(current_app.config.get('HTTPS_CERT_DIR', '/etc/ssl/g3'))
    executable = Path(os.environ.get('MODBUS_TEE_IDENTITY', '/home/zlg/app/bin/modbus_tee_identity'))
    paths = {Path(config.INI_PATH), settings['ca_file'], settings['crl_file'], modbus, https, executable}
    for directory, stems in ((modbus, ('master', 'slave')), (https, ('g3',))):
        for stem in stems:
            paths.update(directory / (stem + suffix) for suffix in
                         ('.crt', '.key', '.csr', '.intermediates.pem'))
            paths.add(directory / ('.' + stem + '-pki-source.json'))
    paths.update((https / '.reload-required', https / 'renewal-status.json'))
    paths.update(pki.pending_path(settings, service) for service in ('nginx', 'tems'))
    versions = []
    for path in sorted(paths, key=str):
        try:
            st = path.lstat()
            version = (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns,
                       st.st_mode, st.st_uid, st.st_gid)
            # Some device filesystems give consecutive same-size writes identical
            # timestamps. Hash small PKI files as well, without retaining their bytes.
            if stat.S_ISREG(st.st_mode) and st.st_size <= 1024 * 1024 and path != executable:
                try:
                    fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                    with os.fdopen(fd, 'rb') as stream:
                        info = os.fstat(stream.fileno())
                        digest = hashlib.sha256()
                        if stat.S_ISREG(info.st_mode) and info.st_size <= 1024 * 1024:
                            remaining = 1024 * 1024 + 1
                            while remaining:
                                block = stream.read(min(65536, remaining))
                                if not block:
                                    break
                                digest.update(block)
                                remaining -= len(block)
                            version += (digest.digest(),)
                except OSError as error:
                    version += (('unreadable', error.errno),)
        except FileNotFoundError:
            version = None
        versions.append((str(path), version))
    return (tuple(versions), os.environ.get('MODBUS_KEY_BACKEND', 'file'))


def cached_pki_read(key, collect):
    """Deduplicate concurrent queries; writes/explicit verify never use this cache."""
    entry = current_app.extensions.setdefault('pki_public_read_cache',
                                              {'lock': RLock(), 'entries': {}})
    with entry['lock']:
        version = _version()
        old = entry['entries'].get(key)
        if (old and old[0] == version and monotonic() < old[1]
                and abs((time() - old[3]) - (monotonic() - old[4])) < 0.25):
            return deepcopy(old[2])
        result = collect()
        # Never cache a result assembled while files were changing; don't cache exceptions.
        if version == _version():
            entry['entries'][key] = (version, monotonic() + TTL_SECONDS, deepcopy(result),
                                     time(), monotonic())
        return result
