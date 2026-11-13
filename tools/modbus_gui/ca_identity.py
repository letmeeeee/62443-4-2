"""PC-only independent RSA identities and public single-role CA exchange packages."""
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import tempfile
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def read(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024*1024:
        raise ValueError('文件不存在、过大或为符号链接: '+str(path))
    return path.read_bytes()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write(path, data, private=False):
    with open(path, 'xb') as stream:
        if os.name == 'posix': os.fchmod(stream.fileno(), 0o600 if private else 0o644)
        stream.write(data)


def generate(parent, role, identity, host='127.0.0.1'):
    if role not in ('master','slave') or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,39}',identity):
        raise ValueError('角色需为 master/slave；PC 身份编号限1–40位字母数字点横线下划线')
    san = None
    if role == 'slave':
        address = ipaddress.ip_address(host.strip())
        if address.is_unspecified or address.is_multicast:
            raise ValueError('请填写实际可连接的 PC IP，不是0.0.0.0')
        san = x509.IPAddress(address)
    folder = Path(tempfile.mkdtemp(prefix=identity+'-'+role+'-',dir=parent))
    folder.chmod(0o700)
    try:
        key = rsa.generate_private_key(public_exponent=65537,key_size=3072)
        csr = (x509.CertificateSigningRequestBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,identity+'-'+role)]))
            .add_extension(x509.BasicConstraints(False,None),True)
            .add_extension(x509.KeyUsage(True,False,True,False,False,False,False,False,False),True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH if role=='master' else ExtendedKeyUsageOID.SERVER_AUTH]),False))
        if san: csr=csr.add_extension(x509.SubjectAlternativeName([san]),False)
        data=csr.sign(key,hashes.SHA256()).public_bytes(serialization.Encoding.PEM)
        write(folder/(role+'.key'),key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()),True)
        request=folder/'request';request.mkdir(mode=0o700)
        write(request/(role+'.csr'),data)
        manifest=dict(version=1,kind='lc400-role-csr',device_id=identity,role=role,files={role+'.csr':digest(data)})
        write(request/'manifest.json',json.dumps(manifest,indent=2).encode())
        return folder
    except BaseException:
        shutil.rmtree(folder);raise


def import_bundle(identity_folder, bundle, fingerprints):
    """Validate public package, role, original request/key and CA chain before installing locally."""
    folder,bundle=Path(identity_folder),Path(bundle)
    request=json.loads(read(folder/'request/manifest.json'))
    role=request.get('role')
    manifest=json.loads(read(bundle/'manifest.json'))
    names={'roots.pem','intermediates.pem',str(role)+'-leaf.pem'}
    if (role not in ('master','slave') or manifest.get('kind')!='lc400-role-certificates'
            or manifest.get('version')!=1 or manifest.get('role')!=role
            or manifest.get('device_id')!=request.get('device_id') or set(manifest.get('files',{}))!=names):
        raise ValueError('请选择与本地 PC 身份/角色对应的单角色签发包')
    material={name:read(bundle/name) for name in names}
    if any(digest(data)!=manifest['files'][name] for name,data in material.items()):
        raise ValueError('证书包摘要不匹配')
    roots=x509.load_pem_x509_certificates(material['roots.pem'])
    actual={c.fingerprint(hashes.SHA256()).hex().upper() for c in roots}
    pins={v.strip().replace(':','').upper() for v in fingerprints if v.strip()}
    if not pins or pins!=actual: raise ValueError('请填写并核对全部可信根 CA SHA-256 指纹')
    leafs=x509.load_pem_x509_certificates(material[role+'-leaf.pem'])
    if len(leafs)!=1: raise ValueError('签发包必须含单份叶证书')
    leaf=leafs[0]
    csr_data=read(folder/'request'/(role+'.csr'))
    if digest(csr_data)!=request['files'][role+'.csr']: raise ValueError('本地 CSR 摘要不匹配')
    csr=x509.load_pem_x509_csr(csr_data)
    key_path=folder/(role+'.key')
    if os.name=='posix':
        for path in (folder,key_path):
            info=path.stat()
            if path.is_symlink() or info.st_uid!=os.geteuid() or info.st_mode&0o077:
                raise ValueError('本地身份目录/私钥需归当前用户且禁止组和其他用户访问')
    key=serialization.load_pem_private_key(read(folder/(role+'.key')),None)
    def public(k):return k.public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
    if (not csr.is_signature_valid or public(key.public_key())!=public(csr.public_key())
            or public(key.public_key())!=public(leaf.public_key()) or csr.subject!=leaf.subject):
        raise ValueError('证书与本地 CSR / 私钥不匹配')
    expected=ExtendedKeyUsageOID.CLIENT_AUTH if role=='master' else ExtendedKeyUsageOID.SERVER_AUTH
    if (leaf.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
            or set(leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value)!={expected}
            or not leaf.extensions.get_extension_for_class(x509.KeyUsage).value.digital_signature):
        raise ValueError('叶证书用途与角色不匹配')
    def sans(obj):
        try:return obj.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        except x509.ExtensionNotFound:return None
    if sans(csr)!=sans(leaf):raise ValueError('证书 SAN 与本地 CSR 不匹配')
    chain=x509.load_pem_x509_certificates(material['intermediates.pem'])
    certificates=[leaf]+chain
    now=datetime.now(timezone.utc)
    for cert in certificates+roots:
        if cert.signature_hash_algorithm.name not in ('sha256','sha384','sha512'):
            raise ValueError('证书签名摘要强度不足')
        if not cert.not_valid_before_utc<=now<cert.not_valid_after_utc:raise ValueError('证书未生效或已过期')
    # OpenSSL performs full path, purpose and critical-extension checks at handshake.
    # Preflight also checks ordered signatures, CA usage and path-length constraints.
    for index,cert in enumerate(certificates):
        candidates=chain[index:index+1] if index<len(chain) else roots
        issuer=next((c for c in candidates if c.subject==cert.issuer),None)
        if issuer is None:raise ValueError('签发链不完整或顺序错误')
        bc=issuer.extensions.get_extension_for_class(x509.BasicConstraints).value
        ku=issuer.extensions.get_extension_for_class(x509.KeyUsage).value
        if not bc.ca or not ku.key_cert_sign or (bc.path_length is not None and index>bc.path_length):
            raise ValueError('CA 用途或路径长度无效')
        cert.verify_directly_issued_by(issuer)
    for root in roots:
        if (not root.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
                or not root.extensions.get_extension_for_class(x509.KeyUsage).value.key_cert_sign):
            raise ValueError('根信任必须为 CA 证书')
        root.verify_directly_issued_by(root)
    fullchain=material[role+'-leaf.pem']+b'\n'+material['intermediates.pem']
    # Load via the same SSL implementation used by the transport before publishing.
    with tempfile.TemporaryDirectory(dir=folder) as stage:
        stage=Path(stage);write(stage/'identity.pem',fullchain);write(stage/'roots.pem',material['roots.pem'])
        ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER if role=='slave' else ssl.PROTOCOL_TLS_CLIENT)
        ctx.load_cert_chain(str(stage/'identity.pem'),str(folder/(role+'.key')))
        ctx.load_verify_locations(cafile=str(stage/'roots.pem'))
        installed=folder/('issued-'+digest(fullchain)[:16])
        if installed.exists():raise ValueError('该证书已导入，请直接使用已有身份目录')
        os.rename(stage,installed)
    return dict(role=role,cert=str(installed/'identity.pem'),key=str(folder/(role+'.key')),ca=str(installed/'roots.pem'))


def inspect_local_identity(folder):
    """Read a local request's public metadata without trusting the folder name."""
    folder=Path(folder)
    manifest=json.loads(read(folder/'request/manifest.json'))
    role=manifest.get('role')
    if (manifest.get('version')!=1 or manifest.get('kind')!='lc400-role-csr'
            or role not in ('master','slave')
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,39}',str(manifest.get('device_id','')))
            or set(manifest.get('files',{}))!={str(role)+'.csr'}):
        raise ValueError('请选择含 request 子目录和角色私钥的 PC 身份目录')
    data=read(folder/'request'/(role+'.csr'))
    if digest(data)!=manifest['files'][role+'.csr']:raise ValueError('本地 CSR 摘要不匹配')
    csr=x509.load_pem_x509_csr(data)
    if not csr.is_signature_valid:raise ValueError('CSR 签名无效')
    cn=csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    if len(cn)!=1 or cn[0].value!=manifest['device_id']+'-'+role:
        raise ValueError('CSR 身份与本地清单不匹配')
    key=folder/(role+'.key')
    if key.is_symlink() or not key.is_file():raise ValueError('本地角色私钥不存在或为符号链接')
    ips=[]
    try:ips=csr.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)
    except x509.ExtensionNotFound:pass
    return dict(role=role,identity=manifest['device_id'],folder=str(folder),host=str(ips[0]) if ips else '')
