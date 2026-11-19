"""In-process strict X.509/CRL verification for Windows packaging."""
from pathlib import Path
import re

from cryptography import x509
from OpenSSL import crypto

CERT = re.compile(rb'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----', re.S)
CRL = re.compile(rb'-----BEGIN X509 CRL-----.*?-----END X509 CRL-----', re.S)


def verify_certificate(certificate, ca_path, crl_path, chain):
    roots_data, crl_data = Path(ca_path).read_bytes(), Path(crl_path).read_bytes()
    if max(len(roots_data), len(crl_data), len(chain)) > 1024*1024:
        raise ValueError('CA/CRL/证书链文件不能超过 1 MiB')
    roots, crls = CERT.findall(roots_data), CRL.findall(crl_data)
    if not roots or not crls:
        raise ValueError('缺少 PEM 信任根或 CRL')
    store = crypto.X509Store()
    for data in roots:
        root = x509.load_pem_x509_certificate(data)
        if root.subject != root.issuer or not root.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
            raise ValueError('信任锚必须是自签根 CA 证书')
        root.verify_directly_issued_by(root)
        store.add_cert(crypto.X509.from_cryptography(root))
    for data in crls:
        store.add_crl(x509.load_pem_x509_crl(data))
    store.set_flags(crypto.X509StoreFlags.X509_STRICT | crypto.X509StoreFlags.CRL_CHECK |
                    crypto.X509StoreFlags.CRL_CHECK_ALL | crypto.X509StoreFlags.CHECK_SS_SIGNATURE)
    intermediates = [crypto.X509.from_cryptography(x509.load_pem_x509_certificate(data)) for data in CERT.findall(chain)]
    try:
        context = crypto.X509StoreContext(store, crypto.X509.from_cryptography(certificate), intermediates)
        context.verify_certificate()
        if len(context.get_verified_chain()) > 9:
            raise ValueError('证书链超过深度 8')
    except crypto.X509StoreContextError as error:
        raise ValueError('证书链/有效期/CRL 校验失败：'+str(error)) from error
