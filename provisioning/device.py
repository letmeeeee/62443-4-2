"""Local first-boot provisioning; reuses production CLI and OpenSSL validation."""
import contextlib
import fcntl
import importlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

from .common import ROLES, atomic_write, device_name, digest, json_bytes, public_package, read_file


class DeviceProvisioner:
    def __init__(self, app='/home/zlg/app', config='/home/zlg/lc_data_set.ini', backend='file',
                 modbus_dir='/etc/ems/modbus', https_dir='/etc/ssl/g3', helper=None):
        if backend not in ('file', 'tee'):
            raise ValueError('密钥后端仅支持 file/tee')
        self.app = Path(app).absolute()
        self.config = Path(config).absolute()
        self.backend = backend
        self.modbus = Path(modbus_dir).absolute()
        self.https = Path(https_dir).absolute()
        self.helper = Path(helper or self.app / 'bin/modbus_tee_identity').absolute()
        self.environment = dict(os.environ, MODBUS_KEY_BACKEND=backend, LC_INI_PATH=str(self.config),
                                MODBUS_TEE_IDENTITY=str(self.helper), HTTPS_CERT_DIR=str(self.https))
        # No main Flask import or database access during commissioning.
        sys.path.insert(0, str(self.app / 'script'))
        self.pki = importlib.import_module('pki_common')
        self.https_tool = importlib.import_module('https_certificates')
        self.https_config = importlib.import_module('https_config')
        self.settings = self.pki.read_config(self.config)

    def run(self, arguments, timeout=180):
        result = subprocess.run([str(a) for a in arguments], env=self.environment,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, timeout=timeout, check=False)
        if result.returncode:
            raise RuntimeError('命令失败: ' + shlex.join([str(a) for a in arguments]) + '\n' + result.stderr[-5000:] + result.stdout[-2000:])
        return result.stdout.strip()

    def modbus_command(self, *args):
        return [sys.executable, self.app/'script/modbus_certs.py', '--config', self.config,
                '--dir', self.modbus, *args]

    def https_command(self, *args):
        return [sys.executable, self.app/'script/https_certificates.py', '--config', self.config,
                '--dir', self.https, *args]

    @contextlib.contextmanager
    def locked(self):
        self.modbus.mkdir(parents=True, mode=0o700, exist_ok=True)
        lock = self.modbus / '.commission.lock'
        fd = os.open(str(lock), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)

    def generate(self, device_id, output):
        device_name(device_id)
        output = Path(output).absolute()
        if output.exists():
            raise ValueError('CSR 输出目录已存在，请选择新目录，避免覆盖交接材料')
        ips = self.https_config.read_device_ips(self.config)
        with self.locked():
            self.run(self.modbus_command('csr', '--role', 'master', '--name', device_id+'-master'))
            slave = ['csr', '--role', 'slave', '--name', device_id+'-slave']
            for ip in ips: slave += ['--ip', ip]
            self.run(self.modbus_command(*slave))
            self.run(self.https_command('csr'))
            output.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='.csr-export-', dir=str(output.parent)) as temporary:
                stage = Path(temporary) / 'request'; stage.mkdir()
                for role in ('master', 'slave'):
                    self.run(self.modbus_command('csr-export', '--role', role, '--out', stage/(role+'.csr')))
                self.run(self.https_command('csr-export', '--out', stage/'https.csr'))
                keys = [self.pki.csr_public_key(read_file(stage/(r+'.csr'))) for r in ROLES]
                if len(set(keys)) != 3:
                    raise ValueError('三种身份必须使用不同私钥')
                manifest = dict(version=1, kind='lc400-csr', device_id=device_id,
                                backend=self.backend, files={r+'.csr':digest(read_file(stage/(r+'.csr'))) for r in ROLES})
                atomic_write(stage/'manifest.json', json_bytes(manifest), 0o644)
                os.rename(stage, output)
            return dict(output=str(output), device_id=device_id, device_ips=ips,
                        message='仅导出公开 CSR；私钥仍在设备上。请核对 CN/IP 后交给 CA 签发。')

    def preflight(self, bundle, fingerprints):
        bundle = Path(bundle)
        manifest = public_package(bundle, 'lc400-certificates')
        roots = self.pki.validate_roots(read_file(bundle/'roots.pem'))
        actual = {self.pki.fingerprint(c) for c in self.pki.certificates(roots)}
        expected = {str(f).replace(':','').strip().upper() for f in fingerprints}
        if not expected or any(not re.fullmatch('[0-9A-F]{64}', f) for f in expected) or expected != actual:
            raise ValueError('共享根 CA 指纹与可信渠道确认值不一致；不能直接信任包内自带指纹')
        chain = read_file(bundle/'intermediates.pem')
        keys, identities = set(), []
        for role in ROLES:
            csr_path = (self.https/'g3.csr') if role == 'https' else (self.modbus/(role+'.csr'))
            csr = read_file(csr_path)
            leaf, clean = self.pki.validate_identity(read_file(bundle/(role+'-leaf.pem')), chain,
                         bundle/'roots.pem', 'sslclient' if role=='master' else 'sslserver', csr)
            public = self.pki.public_key(leaf)
            if public in keys:
                raise ValueError('三个角色不能共用私钥')
            keys.add(public)
            if role == 'https':
                if public != self.https_tool.key_public(self.https/'g3.key'):
                    raise ValueError('HTTPS 证书与本机私钥不匹配')
                expected_ips = {('IP', ip) for ip in self.https_config.read_device_ips(self.config)}
                if self.pki.subject_cn(leaf) != 'logger' or not expected_ips.issubset(self.pki.san_values(leaf)):
                    raise ValueError('HTTPS CN/SAN 不符合本机配置')
            else:
                with tempfile.TemporaryDirectory(prefix='lc-proof-') as temporary:
                    certificate = Path(temporary)/'identity.pem'; certificate.write_bytes(leaf+clean)
                    self.run([self.helper, '--dir', self.modbus, 'check', role, certificate])
            identities.append(dict(role=role, sha256=self.pki.fingerprint(leaf), private_key_verified=True))
        return dict(valid=True, device_id=manifest['device_id'], root_fingerprints=sorted(actual), identities=identities)

    def import_bundle(self, bundle, fingerprints):
        # Work from immutable local copies; an external USB/share cannot change the package between steps.
        with self.locked(), tempfile.TemporaryDirectory(prefix='lc-import-') as temporary:
            stage = Path(temporary)
            public_package(bundle, 'lc400-certificates')
            names = ['manifest.json','roots.pem','intermediates.pem'] + [r+'-leaf.pem' for r in ROLES]
            for filename in names: (stage/filename).write_bytes(read_file(Path(bundle)/filename))
            checked = self.preflight(stage, fingerprints)
            targets = [self.settings['ca_file'], self.modbus/'master.crt', self.modbus/'slave.crt',
                       self.https/'g3.crt', self.https/'.reload-required']
            previous = {}
            for path in targets:
                if path.is_symlink(): raise ValueError('不能覆盖符号链接: ' + str(path))
                previous[path] = (read_file(path), path.stat().st_mode & 0o777) if path.exists() else None
            # Persist a recovery record before modifying public certificates; never back up private keys.
            recovery = self.modbus/'deployment-recovery'
            if recovery.is_symlink(): raise ValueError('恢复目录不能为符号链接')
            recovery.mkdir(mode=0o700, exist_ok=True)
            if any(recovery.iterdir()):
                raise ValueError('存在未完成导入的恢复记录: ' + str(recovery) + '，请先按部署文档恢复')
            saved = []
            for index, (path, old) in enumerate(previous.items()):
                entry = dict(path=str(path), existed=old is not None)
                if old:
                    atomic_write(recovery/str(index), old[0]); entry.update(file=str(index), mode=old[1])
                saved.append(entry)
            atomic_write(recovery/'manifest.json', json_bytes(saved))
            try:
                args = ['ca-import','--cert',stage/'roots.pem']
                for fingerprint in fingerprints: args += ['--fingerprint', fingerprint]
                self.run(self.modbus_command(*args))
                for role in ('master','slave'):
                    self.run(self.modbus_command('identity-import','--role',role,'--cert',stage/(role+'-leaf.pem'),'--chain',stage/'intermediates.pem'))
                self.run(self.https_command('identity-import','--cert',stage/'https-leaf.pem','--chain',stage/'intermediates.pem'))
                self.check()
            except Exception as original:
                failures = []
                for path, old in previous.items():
                    try:
                        if old is None: path.unlink(missing_ok=True)
                        else: atomic_write(path, old[0], old[1])
                    except OSError as exc: failures.append(str(exc))
                if failures:
                    raise RuntimeError('导入失败且回滚未完成；恢复记录位于 ' + str(recovery) + '\n' + '\n'.join(failures)) from original
                for path in recovery.iterdir(): path.unlink()
                recovery.rmdir()
                raise
            for path in recovery.iterdir(): path.unlink()
            recovery.rmdir()
            return dict(imported=True, validation=checked, applied=False, restart_required=True,
                        message='三份身份证书已导入并校验；请执行应用步骤。')

    def recover(self):
        """Explicit recovery after power loss; restore public files, never touch private keys."""
        with self.locked():
            recovery = self.modbus/'deployment-recovery'
            entries = json.loads(read_file(recovery/'manifest.json'))
            targets = [self.settings['ca_file'], self.modbus/'master.crt', self.modbus/'slave.crt',
                       self.https/'g3.crt', self.https/'.reload-required']
            if not isinstance(entries, list) or len(entries) != len(targets):
                raise ValueError('恢复记录不完整，请人工核查，不自动修改文件')
            restored = []
            for index, (entry, target) in enumerate(zip(entries, targets)):
                if entry.get('path') != str(target) or type(entry.get('existed')) is not bool:
                    raise ValueError('恢复目标与当前配置不匹配')
                if target.is_symlink(): raise ValueError('拒绝恢复到符号链接')
                if entry['existed']:
                    if entry.get('file') != str(index): raise ValueError('恢复文件索引无效')
                    mode = entry.get('mode')
                    if type(mode) is not int or not 0 <= mode <= 0o777: raise ValueError('恢复文件权限无效')
                    restored.append((target, read_file(recovery/str(index)), mode))
                else: restored.append((target, None, None))
            for target, data, mode in restored:
                if data is None: target.unlink(missing_ok=True)
                else: atomic_write(target, data, mode)
            for target in recovery.iterdir(): target.unlink()
            recovery.rmdir()
            return dict(recovered=True, applied=False, message='已恢复导入前的公开证书；请重新校验、导入后再应用。')

    def check(self):
        values = {role:self.run(self.modbus_command('check','--role',role)) for role in ('master','slave')}
        values['https'] = json.loads(self.run(self.https_command('check')))
        return dict(valid=True, backend=self.backend, identities=values)

    def apply(self, tems_service, install_https=True):
        if not re.fullmatch(r'[A-Za-z0-9_@.-]+\.service', tems_service or ''):
            raise ValueError('必须明确提供实际 tems systemd 服务名（含 .service）')
        with self.locked():
            if (self.modbus/'deployment-recovery').exists():
                raise ValueError('存在未完成导入的恢复记录，禁止应用')
            checked = self.check()
            if install_https and (str(self.config) != '/home/zlg/lc_data_set.ini' or str(self.https) != '/etc/ssl/g3'):
                raise ValueError('现有 HTTPS 定时服务使用默认 INI/证书路径；自定义路径请使用 --no-install-timer 并自行维护服务环境')
            loaded = self.run(['systemctl','show',tems_service,'--property=LoadState','--value'])
            if loaded != 'loaded':
                raise ValueError('tems 服务未加载，请核对实际 systemd 服务名')
            env = self.run(['systemctl','show',tems_service,'--property=Environment','--value'])
            settings = dict(item.split('=',1) for item in shlex.split(env) if '=' in item)
            if settings.get('MODBUS_KEY_BACKEND','file') != self.backend:
                raise ValueError('tems 服务 Environment 的密钥后端与部署工具不一致；请先配置服务环境')
            if settings.get('LC_INI_PATH', '/home/zlg/lc_data_set.ini') != str(self.config):
                raise ValueError('tems 服务 Environment 的 INI 路径与部署工具不一致')
            # No config writes: assumes the device INI and both service environments are already configured.
            log = []
            log.append(self.run(['bash',self.app/'script/enable_https.sh',
                                 '--install-service' if install_https else '--apply']))
            try:
                log.append(self.run(['systemctl','restart',tems_service]))
                self.run(['systemctl','is-active','--quiet',tems_service])
            except Exception as exc:
                raise RuntimeError('HTTPS 已应用，但 tems 重启/状态检查失败，请核查服务日志；未自动撤回已应用配置。\n'+str(exc)) from exc
            return dict(applied=True, https_applied=True, tems_service=tems_service,
                        validation=checked, log=log,
                        message='HTTPS 配置已应用，tems 服务处于 active；仍需业务连接和真实 TLS 握手验收。')
