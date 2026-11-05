"""Bounded JSON RPC entry point uploaded temporarily by the PC SSH client."""
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import sys

from .common import ROLES, read_file

PROTOCOL = 1
MAX_REQUEST = 65536


def workspace_path():
    executable = Path(sys.argv[0]).absolute()
    workspace = executable.parent
    if executable.name != 'agent.pyz' or workspace.parent != Path('/tmp') or not workspace.name.startswith('lc400-pc-'):
        raise ValueError('Invalid remote staging workspace')
    if workspace.is_symlink() or not workspace.is_dir():
        raise ValueError('Invalid remote staging directory')
    return workspace


def dispatch(request, workspace):
    if not isinstance(request, dict) or request.get('protocol') != PROTOCOL:
        raise ValueError('Remote protocol mismatch')
    operation = request.get('operation')
    if operation == 'cleanup':
        shutil.rmtree(workspace)
        return dict(cleaned=True)
    options = request.get('options', {})
    if not isinstance(options, dict) or set(options)-{'app','config','backend','modbus_dir','https_dir','helper'}:
        raise ValueError('Invalid device options')
    if operation == 'info':
        app = Path(options.get('app','/home/zlg/app'))
        helper = Path(options.get('helper') or app/'bin/modbus_tee_identity')
        expected = [app/'script/pki_common.py',app/'script/https_certificates.py',
                    app/'script/https_config.py',app/'script/enable_https.sh',
                    app/'script/modbus_certs.py',helper]
        missing = [str(path) for path in expected if not path.is_file()]
        config = options.get('config','/home/zlg/lc_data_set.ini')
        return dict(hostname=socket.gethostname(),uid=os.geteuid(),python=sys.version.split()[0],
                    can_apply=os.geteuid()==0,missing=missing,configuration_exists=Path(config).is_file(),
                    ready=not missing and Path(config).is_file())
    from .device import DeviceProvisioner
    tool = DeviceProvisioner(**options)
    if operation == 'generate':
        result = tool.generate(request.get('device_id'),workspace/'request')
        result['public_files'] = {name:base64.b64encode(read_file(workspace/'request'/name)).decode('ascii')
                                  for name in ['manifest.json']+[role+'.csr' for role in ROLES]}
        result.pop('output',None)
        return result
    if operation in ('preview','import'):
        fingerprints = request.get('fingerprints')
        if not isinstance(fingerprints,list) or not fingerprints or any(not isinstance(x,str) for x in fingerprints):
            raise ValueError('CA fingerprints required')
        method = tool.preflight if operation=='preview' else tool.import_bundle
        return method(workspace/'bundle',fingerprints)
    if operation == 'check':
        return tool.check()
    if operation == 'recover':
        if request.get('confirm') != 'RESTORE_PUBLIC_CERTIFICATES':
            raise ValueError('Recovery confirmation required')
        return tool.recover()
    if operation == 'apply':
        if request.get('confirm') != 'APPLY_AND_RESTART':
            raise ValueError('Apply confirmation required')
        if os.geteuid()!=0:
            raise ValueError('设备端应用需要 root；请以 root 登录或选择 sudo -n')
        install_https = request.get('install_https',True)
        if type(install_https) is not bool:
            raise ValueError('Invalid timer flag')
        return tool.apply(request.get('tems_service'),install_https)
    raise ValueError('Unknown remote operation')


def main():
    os.umask(0o077)
    try:
        data = sys.stdin.buffer.read(MAX_REQUEST+1)
        if len(data)>MAX_REQUEST:
            raise ValueError('Remote request too large')
        request = json.loads(data)
        with contextlib.redirect_stdout(io.StringIO()):
            result = dispatch(request,workspace_path())
        response = dict(protocol=PROTOCOL,ok=True,result=result)
    except Exception as exc:
        response = dict(protocol=PROTOCOL,ok=False,error=str(exc))
    print(json.dumps(response,ensure_ascii=False))
    return 0 if response['ok'] else 1


if __name__=='__main__':
    raise SystemExit(main())
