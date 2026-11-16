"""Signed complete CRLs, stored atomically with their untrusted issuer chains.

The PEM bundle is also consumed by OpenSSL in tems. It is the single durable
source of CRL numbers: replacing it commits both the list and rollback floor.
Expired, authentic lists remain useful for rejecting already revoked serials.
"""
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
import re
import tempfile

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

try:
    from . import pki_common as pki
except ImportError:
    import pki_common as pki

LOG = logging.getLogger(__name__)
CRL_PEM = re.compile(rb'-----BEGIN X509 CRL-----\s+.*?-----END X509 CRL-----', re.S)
MAX_BYTES = 1024 * 1024


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _dates(crl):
    if hasattr(crl, 'last_update_utc'):
        return crl.last_update_utc, crl.next_update_utc
    return _utc(crl.last_update), _utc(crl.next_update) if crl.next_update else None


def _extension(item, kind):
    try:
        return item.extensions.get_extension_for_class(kind).value
    except x509.ExtensionNotFound as exc:
        raise ValueError('Required CRL extension missing: ' + kind.__name__) from exc


def _parse(data, allow_der=False):
    if not data or len(data) > MAX_BYTES:
        raise ValueError('CRL input must be 1 byte to 1 MiB')
    crls = CRL_PEM.findall(data)
    certs = pki.PEM.findall(data)
    remainder = pki.PEM.sub(b'', CRL_PEM.sub(b'', data)).strip()
    if not crls and allow_der:
        crl = x509.load_der_x509_crl(data, default_backend())
        return [crl], []
    if not crls or remainder or len(crls) > 32 or len(certs) > 64:
        raise ValueError('Expected complete CRLs and optional issuer certificates only')
    return ([x509.load_pem_x509_crl(block, default_backend()) for block in crls],
            [x509.load_pem_x509_certificate(block, default_backend()) for block in certs])


def _read_store(path):
    path = Path(path)
    if (path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES
            or path.stat().st_mode & 0o022):
        raise ValueError('Invalid CRL store file')
    return _parse(path.read_bytes())


def _cert_pem(cert):
    return cert.public_bytes(serialization.Encoding.PEM)


def _key(crl):
    # Same-name CAs using different keys must never share serial/number state.
    aki = _extension(crl, x509.AuthorityKeyIdentifier).key_identifier
    if not aki:
        raise ValueError('CRL requires an AKI key identifier')
    return crl.issuer.public_bytes(default_backend()).hex() + ':' + aki.hex()


def _validate(crl, candidates, roots_path):
    number = _extension(crl, x509.CRLNumber).crl_number
    if number < 0 or number.bit_length() > 160:
        raise ValueError('Invalid CRL number')
    for extension in crl.extensions:
        if isinstance(extension.value, (x509.DeltaCRLIndicator, x509.IssuingDistributionPoint)):
            raise ValueError('Delta, indirect and partitioned CRLs are unsupported')
        if extension.critical and not isinstance(extension.value, (x509.CRLNumber, x509.AuthorityKeyIdentifier)):
            raise ValueError('Unsupported critical CRL extension')
    start, end = _dates(crl)
    if end is None or end <= start or start > datetime.now(timezone.utc):
        raise ValueError('Invalid CRL thisUpdate/nextUpdate')
    if crl.signature_hash_algorithm is None or crl.signature_hash_algorithm.name not in ('sha256', 'sha384', 'sha512'):
        raise ValueError('CRL requires a SHA-256 or stronger supported signature')
    aki = _extension(crl, x509.AuthorityKeyIdentifier).key_identifier
    signer = None
    for cert in candidates:
        if cert.subject != crl.issuer:
            continue
        try:
            ski = _extension(cert, x509.SubjectKeyIdentifier).digest
        except ValueError:
            ski = x509.SubjectKeyIdentifier.from_public_key(cert.public_key()).digest
        if ski == aki and crl.is_signature_valid(cert.public_key()):
            signer = cert
            break
    if signer is None:
        raise ValueError('CRL signature/issuer/AKI verification failed; provide the issuer chain')
    if not _extension(signer, x509.BasicConstraints).ca or not _extension(signer, x509.KeyUsage).crl_sign:
        raise ValueError('CRL issuer requires CA:TRUE and cRLSign')
    with tempfile.TemporaryDirectory(prefix='crl-issuer-') as folder:
        issuer = Path(folder) / 'issuer.pem'
        chain = Path(folder) / 'chain.pem'
        issuer.write_bytes(_cert_pem(signer))
        chain.write_bytes(b''.join(_cert_pem(cert) for cert in candidates))
        pki.run('verify', '-no-CAfile', '-no-CApath', '-trusted', roots_path,
                '-untrusted', chain, '-auth_level', '2', '-purpose', 'any', issuer)
    serials = set()
    for entry in crl:
        if entry.serial_number in serials:
            raise ValueError('Duplicate revoked serial')
        serials.add(entry.serial_number)
        for extension in entry.extensions:
            if isinstance(extension.value, x509.CertificateIssuer) or extension.critical:
                raise ValueError('Indirect or critical revoked-entry extensions unsupported')
            if isinstance(extension.value, x509.CRLReason) and extension.value.reason in (
                    x509.ReasonFlags.remove_from_crl, x509.ReasonFlags.certificate_hold):
                raise ValueError('Temporary suspension/removal is unsupported')
    return signer


def _roots(roots_path):
    return [x509.load_pem_x509_certificate(block, default_backend())
            for block in pki.certificates(Path(roots_path).read_bytes())]


def import_crls(settings, data, chain=b''):
    """Validate before commit; a revoked local identity does not block import."""
    incoming, included = _parse(data, allow_der=True)
    extra = [x509.load_pem_x509_certificate(block, default_backend()) for block in pki.certificates(chain)] if chain else []
    path = settings['crl_file']
    with pki.operation_lock(settings), pki.locked(settings['ca_file'].parent):
        old_crls, old_certs = _read_store(path) if path.exists() or path.is_symlink() else ([], [])
        candidates = included + extra + old_certs + _roots(settings['ca_file'])
        merged = {_key(crl): crl for crl in old_crls}
        seen = set()
        for crl in incoming:
            _validate(crl, candidates, settings['ca_file'])
            key = _key(crl)
            if key in seen:
                raise ValueError('Duplicate issuer CRLs in upload')
            seen.add(key)
            previous = merged.get(key)
            if previous is not None:
                number = _extension(crl, x509.CRLNumber).crl_number
                old_number = _extension(previous, x509.CRLNumber).crl_number
                if number < old_number or (number == old_number and
                        crl.public_bytes(serialization.Encoding.DER) != previous.public_bytes(serialization.Encoding.DER)):
                    raise ValueError('CRL number rollback or conflicting same-number content')
                if _dates(crl)[0] < _dates(previous)[0]:
                    raise ValueError('CRL publication time rollback')
                # This implementation supports permanent revocations only.
                if not {r.serial_number for r in previous}.issubset({r.serial_number for r in crl}):
                    raise ValueError('New CRL removes previously revoked serials')
            merged[key] = crl
        unique = {_cert_pem(cert): cert for cert in candidates}
        bundle = b''.join(crl.public_bytes(serialization.Encoding.PEM) for crl in merged.values())
        bundle += b''.join(unique)
        if len(bundle) > MAX_BYTES:
            raise ValueError('Combined CRL store exceeds 1 MiB')
        _parse(bundle)  # Enforce merged issuer/certificate limits before any write.
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        # Mark before replacing: interruption may cause a harmless extra restart,
        # never an unmarked CRL update. The same lock protects service application.
        pki.mark_pending(settings, 'tems', 'crl')
        pki.atomic_write(path, bundle, 0o644)
        LOG.info('CRL import committed path=%s issuers=%d sha256=%s', path, len(merged), hashlib.sha256(bundle).hexdigest())
    return dict(imported=True, restart_required=True, crls=inventory(settings))


def inventory(settings):
    path = settings['crl_file']
    if not path.exists() and not path.is_symlink():
        return []
    crls, certs = _read_store(path)
    candidates = certs + _roots(settings['ca_file'])
    result = []
    for crl in crls:
        validation_error = None
        try:
            _validate(crl, candidates, settings['ca_file'])
        except ValueError as error:
            validation_error = str(error)
        start, end = _dates(crl)
        result.append(dict(issuer=crl.issuer.rfc4514_string(),
                           issuerKeyId=_extension(crl, x509.AuthorityKeyIdentifier).key_identifier.hex(),
                           crlNumber=str(_extension(crl, x509.CRLNumber).crl_number),
                           thisUpdate=start.isoformat(), nextUpdate=end.isoformat(),
                           status='invalid' if validation_error else ('stale' if end <= datetime.now(timezone.utc) else 'valid'),
                           reason=validation_error,
                           revokedCount=len(crl)))
    return result


def _issued_by(cert, issuer):
    if cert.issuer != issuer.subject:
        return False
    try:
        if hasattr(cert, 'verify_directly_issued_by'):
            cert.verify_directly_issued_by(issuer)
        else:
            # Device maintenance Python may carry an older cryptography build.
            # OpenSSL still verifies the direct signature; time is checked by the
            # caller's normal chain validation, independently of revocation state.
            with tempfile.TemporaryDirectory(prefix='crl-direct-issuer-') as folder:
                leaf_path, issuer_path = Path(folder) / 'leaf.pem', Path(folder) / 'issuer.pem'
                leaf_path.write_bytes(_cert_pem(cert))
                issuer_path.write_bytes(_cert_pem(issuer))
                pki.run('verify', '-no-CAfile', '-no-CApath', '-no_check_time', '-partial_chain',
                        '-trusted', issuer_path, leaf_path)
        return True
    except (ValueError, TypeError, InvalidSignature):
        return False


def certificate_status(data, roots_path, crl_path):
    result = dict(revocationStatus='unavailable', revocationReason='CRL_NOT_CONFIGURED',
                  revocationCheckedAt=datetime.now(timezone.utc).isoformat())
    if not Path(crl_path).exists() and not Path(crl_path).is_symlink():
        return result
    crls, issuers = _read_store(crl_path)
    certificates = [x509.load_pem_x509_certificate(block, default_backend()) for block in pki.certificates(data)]
    candidates = issuers + certificates + _roots(roots_path)
    by_issuer = {}
    for crl in crls:
        if not any(cert.issuer == crl.issuer for cert in certificates):
            continue
        # Ignore retained CRLs from a different key with the same issuer DN.
        signers = [issuer for issuer in candidates if issuer.subject == crl.issuer
                   and crl.is_signature_valid(issuer.public_key())]
        if not any(_issued_by(cert, issuer) for cert in certificates for issuer in signers):
            continue
        signer = _validate(crl, candidates, roots_path)
        by_issuer[(_key(crl))] = (crl, signer)
    matched_leaf = False
    stale = False
    for index, cert in enumerate(certificates):
        if cert.subject == cert.issuer:
            continue
        for crl, signer in by_issuer.values():
            if cert.issuer != signer.subject:
                continue
            if not _issued_by(cert, signer):
                continue
            matched_leaf |= index == 0
            start, end = _dates(crl)
            stale |= end <= datetime.now(timezone.utc)
            result.update(crlNumber=str(_extension(crl, x509.CRLNumber).crl_number),
                          crlNextUpdate=end.isoformat())
            if crl.get_revoked_certificate_by_serial_number(cert.serial_number) is not None:
                result.update(revocationStatus='revoked', revocationReason='CERTIFICATE_REVOKED')
                return result
    result.update(revocationStatus=('stale' if stale else 'good') if matched_leaf else 'unknown',
                  revocationReason=('CRL_EXPIRED' if stale else 'CRL_CHECKED') if matched_leaf else 'ISSUER_CRL_MISSING')
    return result
