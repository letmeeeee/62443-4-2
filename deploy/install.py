#!/usr/bin/env python3
"""Device-side bounded upgrade with file backups and failure rollback."""
import argparse
import configparser
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import uuid

SERVICES = ('tems.service', 'python_app.service')
TA = 'lib/optee_armtz/5319e0a0-0001-4e2a-9c01-0c34da100001.ta'


def run(*args):
    subprocess.run(list(map(str, args)), check=True)


def allowed(name):
    if not isinstance(name, str):
        return False
    path = PurePosixPath(name)
    return (path.as_posix() == name and not path.is_absolute() and '..' not in path.parts and
            (name in {'home/zlg/tems', TA} or
             name in {'home/zlg/app/bin/modbus_tee_identity', 'home/zlg/app/bin/crypto_ta_client',
                      'inputs/trusted-master.crt'} or
             (name.startswith('home/zlg/app/') and path.suffix in {'.py', '.sh'} and
              not set(path.parts[3:]) & {'instance', 'keys', 'tests', '__pycache__'}) or
             name.startswith('home/zlg/dist/')))


def target_for(name):
    target = Path('/') / name
    if name.startswith('home/zlg/app/'):
        base = Path('/home/zlg/app').resolve()
    elif name.startswith('home/zlg/dist/'):
        base = Path('/home/zlg/dist').resolve()
    elif name.startswith('etc/ems/modbus/'):
        base = Path('/etc/ems/modbus').resolve()
    elif name == TA:
        base = Path('/lib/optee_armtz').resolve()
    else:
        base = Path('/home/zlg').resolve()
    parent = target.parent.resolve()
    if parent != base and base not in parent.parents:
        raise ValueError('Deployment path escapes its installation directory: ' + name)
    return target


def unpack(bundle, directory):
    with tarfile.open(bundle, 'r:gz') as archive:
        members = archive.getmembers()
        if len(members) > 10000 or sum(m.size for m in members) > 512 * 1024 * 1024:
            raise ValueError('Oversized upgrade bundle')
        names = [m.name for m in members]
        if len(names) != len(set(names)):
            raise ValueError('Duplicate archive members')
        for member in members:
            if not member.isfile() or (member.name != 'manifest.json' and
                    not (member.name.startswith('payload/') and allowed(member.name[8:]))):
                raise ValueError('Invalid archive entry: ' + member.name)
            target = directory / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source, target.open('xb') as output:
                shutil.copyfileobj(source, output)
        manifest = json.loads((directory / 'manifest.json').read_text())
        if not isinstance(manifest, dict) or not manifest:
            raise ValueError('Invalid manifest')
        if set(names) != {'manifest.json'} | {'payload/' + n for n in manifest}:
            raise ValueError('Manifest/archive mismatch')
        for name, expected in manifest.items():
            if not allowed(name) or hashlib.sha256((directory / 'payload' / name).read_bytes()).hexdigest() != expected:
                raise ValueError('Checksum mismatch: ' + name)
        required = {'home/zlg/tems', TA, 'home/zlg/app/main.py',
                    'home/zlg/app/bin/modbus_tee_identity', 'home/zlg/app/bin/crypto_ta_client',
                    'home/zlg/app/scripts/modbus_certs.py', 'home/zlg/app/script/sign_ini.py'}
        if not required <= set(manifest):
            raise ValueError('Incomplete upgrade bundle')
        return manifest


def publish(source, target, executable=False, ownership=None):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise ValueError('Refusing to replace symlink: ' + str(target))
    owner = ownership or (target.stat() if target.exists() else target.parent.stat())
    descriptor, name = tempfile.mkstemp(prefix='.deploy-', dir=target.parent)
    try:
        with os.fdopen(descriptor, 'wb') as output, source.open('rb') as input_file:
            shutil.copyfileobj(input_file, output)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(name, 0o755 if executable else 0o644)
        os.chown(name, owner.st_uid, owner.st_gid)
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def active(service):
    return subprocess.run(['systemctl', 'is-active', '--quiet', service]).returncode == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--initialize-ini-baseline', action='store_true')
    parser.add_argument('--master-name')
    parser.add_argument('--slave-name')
    parser.add_argument('--slave-ip', action='append', default=[])
    parser.add_argument('--trust-master-fingerprint')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Run as root on the target device')
    if os.uname().machine not in {'aarch64', 'arm64'}:
        parser.error('This installer requires an AArch64 target')
    for name in (args.master_name, args.slave_name):
        if name and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', name):
            parser.error('Invalid certificate CN')
    for address in args.slave_ip:
        ipaddress.ip_address(address)
    if args.slave_name and not args.slave_ip:
        parser.error('--slave-name requires --slave-ip; include all expected addresses')
    base = Path('/home/zlg')
    with (base / '.deploy.lock').open('a') as lock, tempfile.TemporaryDirectory(prefix='em1000-install-') as temporary:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        directory = Path(temporary)
        manifest = unpack(args.bundle, directory)
        trusted_input = 'inputs/trusted-master.crt'
        if (trusted_input in manifest) != bool(args.trust_master_fingerprint):
            raise ValueError('Trusted master certificate and fingerprint must be supplied together')
        deployment = {name for name in manifest if not name.startswith('inputs/')}
        for tool in ('systemctl', 'ldd', 'openssl'):
            if not shutil.which(tool):
                raise RuntimeError('Missing required program: ' + tool)
        for service in SERVICES:
            result = subprocess.run(['systemctl', 'show', service, '--property=LoadState', '--value'],
                                    capture_output=True, text=True)
            if result.returncode or result.stdout.strip() != 'loaded':
                raise RuntimeError('Service is not installed: ' + service)
            execution = subprocess.run(['systemctl', 'show', service, '--property=ExecStart', '--value'],
                                       capture_output=True, text=True)
            if service == 'tems.service':
                matches = '/home/zlg/tems' in execution.stdout
            else:
                working = subprocess.run(['systemctl', 'show', service, '--property=WorkingDirectory', '--value'],
                                         capture_output=True, text=True)
                matches = ('/home/zlg/app/main.py' in execution.stdout or
                           (working.stdout.strip() == '/home/zlg/app' and
                            re.search(r'(?<![\w/])main\.py(?![\w/])', execution.stdout)))
            if execution.returncode or not matches:
                raise RuntimeError('Service ExecStart does not match the supported deployment layout: ' + service)
        if not (base / 'app/main.py').exists() or not (base / 'lc_data_set.ini').exists():
            raise RuntimeError('Requires an existing configured EMS installation')
        # Never accept a mismatched baseline as part of a routine deployment.
        ini = base / 'lc_data_set.ini'
        checksum = base / 'signature/lc_data_set.ini.sha256'
        if checksum.exists():
            expected = checksum.read_text().strip().lower()
            if not re.fullmatch('[0-9a-f]{64}', expected) or hashlib.sha256(ini.read_bytes()).hexdigest() != expected:
                raise RuntimeError('INI baseline mismatch; review configuration before deploying')
        elif not args.initialize_ini_baseline:
            raise RuntimeError('INI baseline missing; review configuration and use --initialize-ini-baseline')
        for filename in ('home/zlg/tems', 'home/zlg/app/bin/modbus_tee_identity', 'home/zlg/app/bin/crypto_ta_client'):
            candidate = directory / 'payload' / filename
            candidate.chmod(0o755)
            result = subprocess.run(['ldd', str(candidate)], capture_output=True, text=True)
            if result.returncode or 'not found' in result.stdout + result.stderr:
                raise RuntimeError('Unresolved runtime libraries: ' + filename + '\n' + result.stdout + result.stderr)
        config = configparser.ConfigParser(interpolation=None, strict=False)
        config.read(str(ini))
        tls = config.get('SYSTEM', 'modbus_tls_enabled', fallback='0').strip() == '1'
        backup = base / 'deploy-backups' / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
        backup.mkdir(parents=True, mode=0o700)
        paths = set(deployment)
        paths.add('home/zlg/signature/lc_data_set.ini.sha256')
        for role in ('master', 'slave'):
            paths.add('etc/ems/modbus/' + role + '.crt')
        if args.trust_master_fingerprint:
            paths.add('etc/ems/modbus/master-ca.crt')
        records = {}
        for name in sorted(paths):
            target = target_for(name)
            if target.is_symlink() or (target.exists() and not target.is_file()):
                raise RuntimeError('Invalid deployment target: ' + str(target))
            if target.exists():
                saved = backup / 'files' / name
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
                stat = target.stat()
                records[name] = {'mode': stat.st_mode & 0o777, 'uid': stat.st_uid, 'gid': stat.st_gid}
            else:
                records[name] = None
        was_active = {service: active(service) for service in SERVICES}
        (backup / 'state.json').write_text(json.dumps({'files': records, 'active': was_active}, indent=2))
        print('Backup: ' + str(backup), flush=True)
        changed = []
        try:
            run('systemctl', 'stop', 'python_app.service', 'tems.service')
            for name in sorted(deployment):
                target = target_for(name)
                changed.append(name)
                publish(directory / 'payload' / name, target,
                        name in {'home/zlg/tems', 'home/zlg/app/bin/modbus_tee_identity', 'home/zlg/app/bin/crypto_ta_client'})
            if not checksum.exists():
                changed.append('home/zlg/signature/lc_data_set.ini.sha256')
                run('python3', base / 'app/script/sign_ini.py')
            script = base / 'app/scripts/modbus_certs.py'
            for role, name in (('master', args.master_name), ('slave', args.slave_name)):
                cert = Path('/etc/ems/modbus') / (role + '.crt')
                if name:
                    changed.append('etc/ems/modbus/' + role + '.crt')
                    command = ['python3', str(script), 'renew' if cert.exists() else 'generate',
                               '--role', role, '--name', name]
                    if role == 'slave':
                        for address in args.slave_ip:
                            command += ['--ip', address]
                    run(*command)
                if tls and (cert.exists() or name):
                    run('python3', script, 'check', '--role', role)
            if args.trust_master_fingerprint:
                changed.append('etc/ems/modbus/master-ca.crt')
                run('python3', script, 'trust-add', '--cert', directory / 'payload' / trusted_input,
                    '--fingerprint', args.trust_master_fingerprint)
            if tls:
                if not Path('/etc/ems/modbus/slave.crt').exists():
                    raise RuntimeError('TLS slave certificate missing; use --slave-name and --slave-ip')
                trust = Path('/etc/ems/modbus/master-ca.crt')
                if not trust.is_file() or not trust.stat().st_size:
                    raise RuntimeError('Import a trusted master certificate before enabling TLS')
            for service in SERVICES:
                if was_active[service]:
                    run('systemctl', 'start', service)
            time.sleep(3)
            for service in SERVICES:
                if was_active[service] and not active(service):
                    raise RuntimeError('Service did not stay active: ' + service)
            if was_active['python_app.service']:
                ready = False
                for attempt in range(15):
                    try:
                        with urllib.request.urlopen('http://127.0.0.1:8000/permission/session', timeout=2) as response:
                            ready = response.status == 200
                    except urllib.error.HTTPError as exc:
                        ready = exc.code == 401
                    except (OSError, urllib.error.URLError):
                        pass
                    if ready:
                        break
                    time.sleep(1)
                if not ready:
                    raise RuntimeError('Backend HTTP readiness check failed')
        except BaseException:
            print('Deployment failed; restoring replaced files from ' + str(backup), flush=True)
            subprocess.run(['systemctl', 'stop', 'python_app.service', 'tems.service'])
            for name in reversed(changed):
                target = target_for(name)
                old = records[name]
                if old is None:
                    if target.is_file() and not target.is_symlink():
                        target.unlink()
                else:
                    publish(backup / 'files' / name, target, bool(old['mode'] & 0o111))
                    target.chmod(old['mode']); os.chown(target, old['uid'], old['gid'])
            for service in SERVICES:
                if was_active[service]:
                    subprocess.run(['systemctl', 'start', service])
            raise
        (backup / 'SUCCESS').write_text('Deployment completed\n')
        print('Deployment complete. Verify real Modbus TLS connectivity; backup: ' + str(backup), flush=True)
        if args.master_name:
            print('Distribute /etc/ems/modbus/master.crt to downstream slaves before expecting TLS connections.')


if __name__ == '__main__':
    main()
