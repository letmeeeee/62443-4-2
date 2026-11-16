#!/bin/sh
# 文件身份密钥轮换。先停止使用该身份的服务；详见 rotate_identity_key.md。
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "${PYTHON:-python3}" - "$SCRIPT_DIR" "$@" <<'PY'
import argparse
import contextlib
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, sys.argv.pop(1))
import pki_common as pki
from https_certificates import generate_csr
from modbus_certs import locked as modbus_locked


def log(message):
    print('[identity-rotation] ' + message, flush=True)


def trusted_path(path):
    """拒绝路径中的符号链接，避免写入意外位置。"""
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ValueError('symbolic links are not accepted: ' + str(item))


def existing_file(path):
    trusted_path(path)
    if not path.exists():
        return None
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
        raise ValueError('file must be regular and owned by the running user: ' + str(path))
    return path.read_bytes()


def modbus_csr(args, staging, old):
    """默认保留原身份的 CN/SAN，也允许显式指定新名称和 SAN。"""
    source = old.get(args.target + '.csr') or old.get(args.target + '.crt')
    is_csr = bool(old.get(args.target + '.csr'))
    name = args.name or (pki.subject_cn(source, csr=is_csr) if source else None)
    if not name or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', name):
        raise ValueError('provide --name with a valid identity name (1..64 characters)')
    ips, dns = args.ip, args.dns
    if ips is None and dns is None and source:
        sans = pki.san_values(source, csr=is_csr)
        ips = sorted(value for kind, value in sans if kind == 'IP')
        dns = sorted(value for kind, value in sans if kind == 'DNS')
    ips = [str(ipaddress.ip_address(value)) for value in (ips or [])]
    dns = dns or []
    if len(ips) > 32 or len(dns) > 32:
        raise ValueError('each SAN list is limited to 32 entries')
    for value in dns:
        if len(value) > 253 or not all(
            re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', part)
            for part in value.split('.')
        ):
            raise ValueError('invalid DNS SAN')
    key = staging / (args.target + '.key')
    pki.atomic_write(key, pki.run('genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:3072'))
    command = [
        'req', '-new', '-key', key, '-passin', 'pass:', '-sha256', '-subj', '/CN=' + name,
        '-addext', 'basicConstraints=critical,CA:FALSE',
        '-addext', 'keyUsage=critical,digitalSignature,keyEncipherment',
        '-addext', 'extendedKeyUsage=' + ('clientAuth' if args.target == 'master' else 'serverAuth'),
    ]
    sans = ['IP:' + value for value in ips] + ['DNS:' + value for value in dns]
    if sans:
        command += ['-addext', 'subjectAltName=' + ','.join(sans)]
    pki.atomic_write(staging / (args.target + '.csr'), pki.run(*command), 0o644)


def main():
    parser = argparse.ArgumentParser(prog='rotate_identity_key.sh', description=(
        'Rotate a FILE-backed RSA-3072 identity and generate its new CSR. '
        'Stop tems/nginx first. Old key/CSR/certificate are backed up; '
        'the old certificate is removed. No service is stopped or restarted automatically.'
    ))
    parser.add_argument('target', choices=('master', 'slave', 'https'))
    parser.add_argument('--config', default=os.environ.get('LC_INI_PATH', pki.DEFAULT_CONFIG))
    parser.add_argument('--dir', type=Path, help='override the selected identity directory')
    parser.add_argument('--backend', choices=('file', 'tee'),
                        default=os.environ.get('MODBUS_KEY_BACKEND', 'file'),
                        help='actual Modbus backend (default: MODBUS_KEY_BACKEND or file)')
    parser.add_argument('--name', help='Modbus CN; defaults to the existing CSR/certificate CN')
    parser.add_argument('--ip', action='append', help='Modbus IP SAN; repeat for multiple values')
    parser.add_argument('--dns', action='append', help='Modbus DNS SAN; repeat for multiple values')
    parser.add_argument('--confirm', help='required literal: ROTATE_IDENTITY_KEY')
    args = parser.parse_args()
    if args.confirm != 'ROTATE_IDENTITY_KEY':
        parser.error('explicit --confirm ROTATE_IDENTITY_KEY is required')
    if args.target != 'https' and args.backend != 'file':
        raise ValueError('Modbus TEE slot rotation is not supported by the current TA; '
                         'generic rotate-rsa does NOT rotate master/slave slots')
    if args.target == 'https' and any(value is not None for value in (args.name, args.ip, args.dns)):
        parser.error('HTTPS CN/SAN come from the existing HTTPS configuration; omit --name/--ip/--dns')
    default_dir = (os.environ.get('HTTPS_CERT_DIR', '/etc/ssl/g3') if args.target == 'https'
                   else os.environ.get('MODBUS_CERT_DIR', '/etc/ems/modbus'))
    directory = Path(os.path.abspath(str(args.dir or default_dir)))
    trusted_path(directory)
    info = directory.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise ValueError('identity directory must be owned by the running user and not group/world writable')
    settings = pki.read_config(args.config)
    stem = 'g3' if args.target == 'https' else args.target
    key_name, csr_name, cert_name = (stem + suffix for suffix in ('.key', '.csr', '.crt'))
    marker = directory / ('.' + stem + '-rotation-incomplete.json')
    lock = pki.locked if args.target == 'https' else modbus_locked
    with pki.operation_lock(settings), lock(directory):
        if marker.exists() or marker.is_symlink():
            raise ValueError('unfinished rotation detected; inspect recovery record: ' + str(marker))
        names = [key_name, csr_name, cert_name]
        if args.target == 'https':
            names += ['.reload-required', 'renewal-status.json']
        old = {name: existing_file(directory / name) for name in names}
        if old[key_name] is None:
            raise ValueError('existing file key is missing; use initial provisioning instead: ' + key_name)
        if (directory / key_name).stat().st_mode & 0o077:
            raise ValueError('existing private key must have mode 0600')
        # 所有生成及校验先在临时目录完成，失败时不替换现有身份。
        with tempfile.TemporaryDirectory(prefix='.key-rotation-', dir=directory) as temporary:
            staging = Path(temporary)
            log('generating new RSA-3072 key and CSR: target=' + args.target)
            if args.target == 'https':
                generate_csr(staging, settings['config_file'])
            else:
                modbus_csr(args, staging, old)
            pki.run('pkey', '-in', staging / key_name, '-passin', 'pass:', '-check', '-noout')
            public = pki.run('pkey', '-in', staging / key_name, '-passin', 'pass:', '-pubout', '-outform', 'DER')
            csr = (staging / csr_name).read_bytes()
            if public != pki.csr_public_key(csr):
                raise ValueError('new CSR does not match the new key')
            previous = pki.run('pkey', '-in', directory / key_name, '-passin', 'pass:', '-pubout', '-outform', 'DER')
            if public == previous:
                raise ValueError('new public key unexpectedly matches the old key')
            backups = directory / 'backups'
            trusted_path(backups)
            backups.mkdir(mode=0o700, exist_ok=True)
            backup_info = backups.stat()
            if backup_info.st_uid != os.geteuid() or backup_info.st_mode & 0o077:
                raise ValueError('backup directory must be owned by the running user with mode 0700')
            backup = Path(tempfile.mkdtemp(prefix=stem + '-rotation-', dir=backups))
            for name, data in old.items():
                if data is not None:
                    pki.atomic_write(backup / name, data)
            record = dict(target=args.target, backup=str(backup),
                          created_at=datetime.now(timezone.utc).isoformat(),
                          public_key_sha256=hashlib.sha256(public).hexdigest(),
                          restore_files={name: data is not None for name, data in old.items()})
            pki.atomic_write(backup / 'rotation.json', json.dumps(record, indent=2).encode())
            pki.atomic_write(marker, json.dumps(record, indent=2).encode())
            log('backup ready: ' + str(backup))
            try:
                # 先撤下旧证书，避免新私钥与旧证书一起被加载。
                for name in names:
                    if name not in (key_name, csr_name):
                        (directory / name).unlink(missing_ok=True)
                pki.atomic_write(directory / key_name, (staging / key_name).read_bytes())
                pki.atomic_write(directory / csr_name, csr, 0o644)
                marker.unlink()
            except BaseException:
                log('publication failed; restoring the previous on-disk identity')
                # 若恢复也失败，保留 marker 和备份，阻止下一次轮换。
                for name, data in old.items():
                    if data is None:
                        (directory / name).unlink(missing_ok=True)
                    else:
                        pki.atomic_write(directory / name, data, 0o644 if name in (csr_name, cert_name) else 0o600)
                marker.unlink()
                raise
    log('rotation complete: target=' + args.target + ' csr=' + str(directory / csr_name))
    log('new public-key SHA-256=' + hashlib.sha256(public).hexdigest())
    log('old certificate is archived. Export this CSR, obtain a new CA-signed certificate, '
        'import it with the existing certificate tool/API, then restart/apply the selected service.')


if __name__ == '__main__':
    os.umask(0o077)
    try:
        main()
    except Exception as error:
        print('[identity-rotation] ERROR: ' + str(error), file=sys.stderr)
        sys.exit(1)
PY
