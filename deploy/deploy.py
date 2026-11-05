#!/usr/bin/env python3
"""Build/package an upgrade for an already provisioned EM-1000."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
UUID = '5319e0a0-0001-4e2a-9c01-0c34da100001'


def run(*args):
    subprocess.run(list(map(str, args)), check=True, cwd=ROOT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', help='SSH target, e.g. root@192.168.2.136')
    parser.add_argument('--bundle-only', action='store_true')
    parser.add_argument('--skip-build', action='store_true', help='Package existing build-deploy outputs')
    parser.add_argument('--with-frontend', action='store_true')
    parser.add_argument('--initialize-ini-baseline', action='store_true', help='Accept current INI only if no baseline exists')
    parser.add_argument('--master-name', help='Create/migrate master certificate with this CN')
    parser.add_argument('--slave-name', help='Create/migrate slave certificate with this CN')
    parser.add_argument('--slave-ip', action='append', default=[])
    parser.add_argument('--trust-master', type=Path, help='Import this public master certificate on the device')
    parser.add_argument('--trust-master-fingerprint', help='SHA-256 fingerprint obtained through a trusted channel')
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--batch-mode', action='store_true', help='Use SSH keys/agent; never prompt for passwords')
    args = parser.parse_args()
    if not args.bundle_only and not args.host:
        parser.error('--host or --bundle-only is required')
    if args.host and not re.fullmatch(r'(?:[A-Za-z0-9_]+@)?[A-Za-z0-9][A-Za-z0-9.-]*', args.host):
        parser.error('Invalid SSH host')
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    if args.slave_ip and not args.slave_name:
        parser.error('--slave-ip requires --slave-name')
    if bool(args.trust_master) != bool(args.trust_master_fingerprint):
        parser.error('--trust-master and --trust-master-fingerprint must be supplied together')
    ssh_options = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10'] if args.batch_mode else []
    if args.batch_mode:
        os.environ['DEPLOY_SSH_BATCH'] = '1'
        if args.host and (not args.bundle_only or not (ROOT / 'logger/.deps/optee-arm64').exists()):
            run('ssh', *ssh_options, args.host, 'test "$(id -u)" -eq 0')
    # An SDK import is read-only on the device. Never silently replace a cache.
    sdk = ROOT / 'logger/.deps/optee-arm64'
    if not sdk.exists() and not args.skip_build:
        if not args.host:
            parser.error('Import the OP-TEE SDK first, or supply --host for the initial import')
        run('sh', ROOT / 'logger/scripts/prepare_optee_client.sh', '--device', args.host)
    if not args.skip_build:
        run('sh', ROOT / 'logger/scripts/prepare_optee_client.sh', '--check')
        run('make', '-C', ROOT / 'logger', '-j' + str(args.jobs),
            'BUILD_DIR=' + str(ROOT / 'logger/build-deploy'))
        run('make', '-C', ROOT / 'optee_ta_examples/ta/crypto_ta',
            'O=' + str(ROOT / 'optee_ta_examples/build-deploy'),
            'TA_DEV_KIT_DIR=' + str(ROOT / 'optee_ta_examples/dev_kit'),
            'CROSS_COMPILE=aarch64-linux-gnu-')
        run('cmake', '-S', ROOT / 'exec/app/tee', '-B', ROOT / 'exec/app/tee/build-deploy',
            '-DCMAKE_TOOLCHAIN_FILE=' + str(ROOT / 'exec/app/tee/cmake/aarch64-linux-gnu.cmake'))
        run('cmake', '--build', ROOT / 'exec/app/tee/build-deploy', '-j', str(args.jobs))

    files = {
        'home/zlg/tems': ROOT / 'logger/build-deploy/tems',
        'home/zlg/app/bin/modbus_tee_identity': ROOT / 'logger/build-deploy/modbus_tee_identity',
        'home/zlg/app/bin/crypto_ta_client': ROOT / 'exec/app/tee/build-deploy/crypto_ta_client',
        'lib/optee_armtz/' + UUID + '.ta': ROOT / ('optee_ta_examples/build-deploy/' + UUID + '.ta'),
        'home/zlg/app/script/modbus_certs.py': ROOT / 'exec/app/script/modbus_certs.py',
    }
    if args.trust_master:
        files['inputs/trusted-master.crt'] = args.trust_master.resolve()
    # Ship code only. Device credentials, keys, instances and runtime files stay local.
    for path in (ROOT / 'exec/app').rglob('*'):
        relative = path.relative_to(ROOT / 'exec/app')
        if any(part in {'tests', 'instance', 'keys', '__pycache__', 'tee', 'bin', 'scripts'}
               or part.startswith('.') for part in relative.parts):
            continue
        if path.is_file() and path.suffix in {'.py', '.sh'}:
            files['home/zlg/app/' + relative.as_posix()] = path
    if args.with_frontend:
        for path in (ROOT / 'exec/dist').rglob('*'):
            if path.is_file() and not path.is_symlink():
                files['home/zlg/dist/' + path.relative_to(ROOT / 'exec/dist').as_posix()] = path
    manifest = {}
    for destination, source in sorted(files.items()):
        if not source.is_file() or source.is_symlink():
            raise RuntimeError('Missing/invalid build artifact: ' + str(source))
        if destination.endswith(('/tems', '/modbus_tee_identity', '/crypto_ta_client')):
            elf = source.read_bytes()[:20]
            if len(elf) < 20 or elf[:6] != b'\x7fELF\x02\x01' or elf[18:20] != b'\xb7\x00':
                raise RuntimeError('Not an AArch64 ELF: ' + str(source))
        manifest[destination] = hashlib.sha256(source.read_bytes()).hexdigest()
    output = ROOT / 'deploy/build-output'
    output.mkdir(parents=True, exist_ok=True)
    bundle = output / 'em1000-upgrade.tar.gz'
    with tempfile.TemporaryDirectory(prefix='em1000-package-') as temporary:
        metadata = Path(temporary) / 'manifest.json'
        metadata.write_text(json.dumps(manifest, sort_keys=True), encoding='utf-8')
        with tarfile.open(bundle, 'w:gz') as archive:
            archive.add(metadata, arcname='manifest.json')
            for destination, source in sorted(files.items()):
                archive.add(source, arcname='payload/' + destination, recursive=False)
    print('Bundle ready: ' + str(bundle), flush=True)
    if args.bundle_only:
        return
    # Fixed, private staging directory; no shell-supplied arbitrary remote commands.
    import secrets
    remote = '/home/zlg/deploy-incoming/' + secrets.token_hex(8)
    run('ssh', *ssh_options, args.host, 'umask 077; mkdir -p ' + shlex.quote(remote))
    run('scp', *ssh_options, bundle, ROOT / 'deploy/install.py', args.host + ':' + remote + '/')
    command = ['python3', remote + '/install.py', '--bundle', remote + '/' + bundle.name]
    if args.initialize_ini_baseline:
        command += ['--initialize-ini-baseline']
    for field in ('master_name', 'slave_name'):
        if getattr(args, field):
            command += ['--' + field.replace('_', '-'), getattr(args, field)]
    for address in args.slave_ip:
        command += ['--slave-ip', address]
    if args.trust_master_fingerprint:
        command += ['--trust-master-fingerprint', args.trust_master_fingerprint]
    run('ssh', *ssh_options, args.host, shlex.join(command))


if __name__ == '__main__':
    main()
