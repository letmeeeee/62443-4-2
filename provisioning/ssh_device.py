"""PC-side SSH/SFTP provisioning; only public CSR/certificate materials cross the link."""
import base64
import contextlib
import hashlib
import importlib.resources
import io
import json
import os
from pathlib import Path
import secrets
import shlex
import socket
import sys
import tempfile
import time
import zipfile

from .common import ROLES, MAX_FILE, device_name, public_package, read_file

MAX_RESPONSE = 8 * 1024 * 1024


class RemoteDeploymentError(RuntimeError):
    pass


def fingerprint(key):
    return 'SHA256:'+base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode('ascii').rstrip('=')


def validate_fingerprint(value):
    if not value:
        return None
    if not isinstance(value,str) or not value.startswith('SHA256:'):
        raise ValueError('SSH 主机指纹格式必须为 SHA256:...，与 CA 根证书十六进制指纹不同')
    encoded=value[7:]
    try:
        data=base64.b64decode(encoded+'='*((-len(encoded))%4),validate=True)
    except (ValueError,TypeError):
        raise ValueError('SSH 主机指纹无效') from None
    if len(data)!=32 or base64.b64encode(data).decode().rstrip('=')!=encoded:
        raise ValueError('SSH 主机指纹无效')
    return value


def agent_archive():
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for name in ('__init__','common','device','ssh_agent'):
            archive.writestr('provisioning/'+name+'.py',importlib.resources.read_binary('provisioning',name+'.py'))
        archive.writestr('__main__.py','from provisioning.ssh_agent import main\nraise SystemExit(main())\n')
    return output.getvalue()


def _paramiko():
    try:
        import paramiko
        return paramiko
    except ImportError:
        raise RuntimeError('PC 缺少 SSH 依赖，请安装 provisioning/requirements-device.txt') from None


class SSHDeviceProvisioner:
    def __init__(self,host,port=22,username='root',password=None,identity_file=None,
                 key_passphrase=None,host_fingerprint=None,known_hosts=None,sudo=False,
                 remote_python='/usr/bin/python3',options=None,timeout=300):
        if not isinstance(host,str) or not host or len(host)>253 or any(c.isspace() or ord(c)<32 for c in host):
            raise ValueError('请输入有效设备主机名或 IP')
        if type(port) is not int or not 1<=port<=65535:
            raise ValueError('SSH 端口必须为 1–65535')
        if not username or any(ord(c)<32 for c in username):
            raise ValueError('SSH 用户名无效')
        if not isinstance(remote_python,str) or not remote_python.startswith('/') or any(ord(c)<32 for c in remote_python):
            raise ValueError('设备 Python 必须为绝对路径')
        self.host,self.port,self.username=host,port,username
        self.password,self.identity_file,self.key_passphrase=password,identity_file,key_passphrase
        self.host_fingerprint=validate_fingerprint(host_fingerprint)
        self.known_hosts=Path(known_hosts).expanduser() if known_hosts else Path.home()/'.ssh/known_hosts'
        if known_hosts and not self.known_hosts.is_file():
            raise ValueError('指定的 known_hosts 文件不存在')
        self.sudo,self.remote_python,self.options=sudo,remote_python,dict(options or {})
        self.timeout=timeout
        if set(self.options)-{'app','config','backend','modbus_dir','https_dir','helper'}:
            raise ValueError('设备选项包含未知字段')
        for name,value in self.options.items():
            if name=='backend':
                if value not in ('file','tee'): raise ValueError('密钥后端仅支持 file/tee')
            elif value is not None and (not isinstance(value,str) or not value.startswith('/') or any(ord(c)<32 for c in value)):
                raise ValueError('设备路径必须为 POSIX 绝对路径: '+name)
        self.client=None
        self.sftp=None

    def _known_hosts(self):
        known=_paramiko().HostKeys()
        if self.known_hosts.is_file(): known.load(str(self.known_hosts))
        return known

    def _transport_factory(self,known):
        """Use identical host-key preferences for unauthenticated probe and login."""
        paramiko=_paramiko()
        hostname=self.host if self.port==22 else '['+self.host+']:'+str(self.port)
        trusted=known.lookup(hostname)
        def factory(*args,**kwargs):
            transport=paramiko.Transport(*args,**kwargs)
            if trusted:
                security=transport.get_security_options()
                def recorded(algorithm):
                    family='ssh-rsa' if algorithm.startswith('rsa-sha2-') else algorithm
                    return family in trusted
                original=list(security.key_types)
                security.key_types=[x for x in original if recorded(x)]+[x for x in original if not recorded(x)]
            return transport
        return factory

    def probe(self):
        """Retrieve an unauthenticated key for out-of-band comparison; do not trust/store it."""
        known=self._known_hosts()
        sock=socket.create_connection((self.host,self.port),timeout=15)
        transport=self._transport_factory(known)(sock)
        try:
            transport.start_client(timeout=15)
            key=transport.get_remote_server_key()
            return dict(host=self.host,port=self.port,ssh_fingerprint=fingerprint(key),
                        key_type=key.get_name(),trusted=False,
                        message='仅探测，尚未信任。密钥类型与正式连接使用相同选择规则；请独立核对后填入。')
        finally:
            transport.close();sock.close()

    def connect(self):
        paramiko=_paramiko()
        known=self._known_hosts()
        expected=self.host_fingerprint
        target=self.host+':'+str(self.port)
        transport_factory=self._transport_factory(known)
        class VerifyHost(paramiko.MissingHostKeyPolicy):
            def missing_host_key(policy,client,hostname,key):
                actual=fingerprint(key)
                entries=known.lookup(hostname)
                known_key=entries.get(key.get_name()) if entries else None
                if entries and (known_key is None or known_key.asbytes()!=key.asbytes()):
                    raise RemoteDeploymentError('SSH 主机密钥与 known_hosts 不一致，拒绝连接。\n主机：'+target+'\n协商密钥类型：'+key.get_name()+'\n当前指纹：'+actual+'\n请在设备本地核对对应类型的 SSH 主机公钥，不要直接删除信任记录。')
                if expected and actual!=expected:
                    raise RemoteDeploymentError('SSH 主机指纹不匹配，拒绝连接。\n主机：'+target+'\n协商密钥类型：'+key.get_name()+'\n填写的指纹：'+expected+'\n当前指纹：'+actual+'\n请在设备本地核对同一密钥类型；不同 RSA/Ed25519/ECDSA 公钥的指纹不同。')
                if not expected and known_key is None:
                    raise RemoteDeploymentError('未知 SSH 主机，请先核对并填写主机指纹；当前指纹 '+actual)
        self.client=paramiko.SSHClient()
        # Keep verification in one pre-auth policy for both pinned and known_hosts keys.
        self.client.set_missing_host_key_policy(VerifyHost())
        try:
            self.client.connect(self.host,port=self.port,username=self.username,password=self.password,
                key_filename=str(Path(self.identity_file).expanduser()) if self.identity_file else None,
                passphrase=self.key_passphrase,allow_agent=self.password is None,
                look_for_keys=self.password is None,timeout=15,banner_timeout=15,auth_timeout=20,
                transport_factory=transport_factory)
            self.client.get_transport().set_keepalive(20)
            self.sftp=self.client.open_sftp()
            self.sftp.get_channel().settimeout(30)
            return self
        except Exception:
            self.close()
            raise

    def close(self):
        if self.sftp:
            with contextlib.suppress(Exception): self.sftp.close()
        if self.client:
            with contextlib.suppress(Exception): self.client.close()
        self.sftp=self.client=None
        self.password=self.key_passphrase=None

    def __enter__(self):
        return self.connect()

    def __exit__(self,*args):
        self.close()

    def _upload(self,path,data):
        if len(data)>MAX_FILE:
            raise ValueError('上传文件超过 1 MiB')
        with self.sftp.open(path,'wx') as stream:
            stream.write(data)
        self.sftp.chmod(path,0o600)

    def _rpc(self,workspace,operation,**arguments):
        command=[self.remote_python,workspace+'/agent.pyz']
        if self.sudo: command=['sudo','-n','--']+command
        data=json.dumps(dict(protocol=1,operation=operation,options=self.options,**arguments),ensure_ascii=False).encode()
        channel=self.client.get_transport().open_session(timeout=15)
        channel.settimeout(15)
        output,error=bytearray(),bytearray()
        deadline=time.monotonic()+self.timeout
        try:
            channel.exec_command(' '.join(shlex.quote(value) for value in command))
            channel.sendall(data);channel.shutdown_write()
            while True:
                if channel.recv_ready(): output.extend(channel.recv(65536))
                if channel.recv_stderr_ready(): error.extend(channel.recv_stderr(65536))
                if len(output)>MAX_RESPONSE or len(error)>1024*1024:
                    raise RemoteDeploymentError('设备返回内容超出限制')
                if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
                    break
                if time.monotonic()>deadline:
                    raise TimeoutError('设备操作超时')
                time.sleep(0.01)
            status=channel.recv_exit_status()
        except (OSError,EOFError,TimeoutError,_paramiko().SSHException) as exc:
            raise RemoteDeploymentError('SSH 操作中断；远程操作可能已执行，请重新连接后先校验，勿盲目重复导入/应用。') from exc
        finally:
            channel.close()
        if status==-1:
            raise RemoteDeploymentError('SSH 未收到设备执行结果；远程操作可能已执行，请重连后先校验。')
        try:
            response=json.loads(output.decode('utf-8'))
        except (ValueError,UnicodeError):
            detail=error.decode('utf-8',errors='replace')[-3000:]
            raise RemoteDeploymentError('设备端执行失败或未返回有效 JSON，请检查 Python/sudo 权限。\n'+detail) from None
        if not isinstance(response,dict) or response.get('protocol')!=1:
            raise RemoteDeploymentError('设备端协议不匹配')
        if status or response.get('ok') is not True:
            raise RemoteDeploymentError(str(response.get('error','设备操作失败')))
        return response['result']

    @contextlib.contextmanager
    def _workspace(self):
        if not self.client or not self.sftp:
            raise RuntimeError('请先建立 SSH 连接')
        self.cleanup_warning=None
        workspace='/tmp/lc400-pc-'+secrets.token_hex(16)
        self.sftp.mkdir(workspace,mode=0o700)
        cleanup_warning=None
        try:
            self._upload(workspace+'/agent.pyz',agent_archive())
            yield workspace
        finally:
            failure=sys.exc_info()[1]
            try: self._rpc(workspace,'cleanup')
            except Exception:
                # Fixed-name SFTP cleanup also works if Python/sudo was unavailable.
                for folder,names in [('request',['manifest.json']+[r+'.csr' for r in ROLES]),
                                     ('bundle',['manifest.json','roots.pem','intermediates.pem']+[r+'-leaf.pem' for r in ROLES])]:
                    for name in names:
                        with contextlib.suppress(Exception): self.sftp.remove(workspace+'/'+folder+'/'+name)
                    with contextlib.suppress(Exception): self.sftp.rmdir(workspace+'/'+folder)
                with contextlib.suppress(Exception): self.sftp.remove(workspace+'/agent.pyz')
                try: self.sftp.rmdir(workspace)
                except Exception: cleanup_warning=workspace
            if cleanup_warning:
                self.cleanup_warning='临时公开材料/代码未能清理：'+cleanup_warning
                if isinstance(failure,Exception):
                    raise RemoteDeploymentError(str(failure)+'\n'+self.cleanup_warning) from failure

    def info(self):
        with self._workspace() as workspace:
            return self._rpc(workspace,'info')

    def generate(self,device_id,output):
        device_name(device_id)
        output=Path(output).absolute()
        if output.exists(): raise ValueError('PC CSR 输出目录已存在，请选择新目录')
        output.parent.mkdir(parents=True,exist_ok=True)
        with self._workspace() as workspace:
            result=self._rpc(workspace,'generate',device_id=device_id)
        files=result.pop('public_files',None)
        expected=['manifest.json']+[r+'.csr' for r in ROLES]
        if not isinstance(files,dict) or set(files)!=set(expected):
            raise RemoteDeploymentError('设备 CSR 文件清单无效')
        with tempfile.TemporaryDirectory(prefix='.ssh-csr-',dir=str(output.parent)) as temporary:
            stage=Path(temporary)/'request';stage.mkdir()
            for name in expected:
                try: data=base64.b64decode(files[name],validate=True)
                except (ValueError,TypeError): raise RemoteDeploymentError('设备 CSR 编码无效') from None
                if len(data)>MAX_FILE: raise RemoteDeploymentError('设备 CSR 文件过大')
                (stage/name).write_bytes(data)
            manifest=public_package(stage,'lc400-csr')
            if manifest['device_id']!=device_id: raise RemoteDeploymentError('设备 CSR 编号不匹配')
            os.rename(stage,output)
        result.update(output=str(output),downloaded=True,message='三份公开 CSR 已下载到 PC；设备私钥未传出。')
        return result

    def _certificate_operation(self,operation,bundle,fingerprints):
        bundle=Path(bundle)
        public_package(bundle,'lc400-certificates')
        # Snapshot and validate before any connection-side upload.
        names=['manifest.json','roots.pem','intermediates.pem']+[r+'-leaf.pem' for r in ROLES]
        material={name:read_file(bundle/name) for name in names}
        with tempfile.TemporaryDirectory(prefix='lc-pc-bundle-') as temporary:
            for name,data in material.items(): (Path(temporary)/name).write_bytes(data)
            public_package(temporary,'lc400-certificates')
        with self._workspace() as workspace:
            self.sftp.mkdir(workspace+'/bundle',mode=0o700)
            for name,data in material.items(): self._upload(workspace+'/bundle/'+name,data)
            return self._rpc(workspace,operation,fingerprints=list(fingerprints))

    def preflight(self,bundle,fingerprints):
        return self._certificate_operation('preview',bundle,fingerprints)

    def import_bundle(self,bundle,fingerprints):
        return self._certificate_operation('import',bundle,fingerprints)

    def check(self):
        with self._workspace() as workspace: return self._rpc(workspace,'check')

    def recover(self):
        with self._workspace() as workspace:
            return self._rpc(workspace,'recover',confirm='RESTORE_PUBLIC_CERTIFICATES')

    def apply(self,tems_service,install_https=True):
        with self._workspace() as workspace:
            return self._rpc(workspace,'apply',tems_service=tems_service,
                             install_https=install_https,confirm='APPLY_AND_RESTART')
