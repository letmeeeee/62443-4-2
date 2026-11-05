"""Portable public CA delivery record for the PC deployment GUI."""
import json
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from .common import digest, public_package, read_file


def load_record(filename):
    path = Path(filename).absolute()
    record = json.loads(read_file(path))
    bundle = path.parent
    manifest = public_package(bundle, 'lc400-certificates')
    if path.name != 'manifest.json':
        if (record.get('version') != 1 or record.get('kind') != 'lc400-deployment'
                or record.get('manifest_sha256') != digest(read_file(bundle/'manifest.json'))
                or record.get('device_id') != manifest['device_id']
                or record.get('root_fingerprints') != manifest.get('root_fingerprints')):
            raise ValueError('部署记录与证书包不匹配')
    roots = x509.load_pem_x509_certificates(read_file(bundle/'roots.pem'))
    actual = [cert.fingerprint(hashes.SHA256()).hex().upper() for cert in roots]
    expected = manifest.get('root_fingerprints')
    if (not actual or not isinstance(expected, list)
            or any(not isinstance(value, str) for value in expected)
            or set(actual) != {value.replace(':', '').upper() for value in expected}):
        raise ValueError('根证书与记录指纹不匹配')
    return dict(bundle=str(bundle), device_id=manifest['device_id'], root_fingerprints=actual)
