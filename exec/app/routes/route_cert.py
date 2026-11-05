"""CA-only device identity management; private keys never leave their role slot."""
import io
import json
import os
from pathlib import Path
from functools import wraps
import re
import subprocess
import sys
import tempfile

import config
from flask import request, jsonify, send_file, current_app, g
from routes.route_g3 import g3_bp

CERT_SCRIPT=Path('/home/zlg/app/script/modbus_certs.py')
CERT_DIR=Path('/etc/ems/modbus')
CERT_TIMEOUT=60
MAX_CERT_SIZE=1024*1024
CERT_FILES={'master':'master.crt','slave':'slave.crt'}


class CertificateScriptError(Exception):
    pass


def cert_admin_required(function):
    @wraps(function)
    def wrapped(*args,**kwargs):
        user=getattr(g,'current_user',None)
        if not isinstance(user,dict):
            return _cert_error('authentication required',401)
        if user.get('permission') not in config.PERMISSION_TABLE.get('usermanage',[]):
            return _cert_error('administrator permission required',403)
        return function(*args,**kwargs)
    return wrapped


def _cert_success(message,data=None):
    return jsonify(status=config.STATE_DONE,message=message,**({'data':data} if data is not None else {})),200


def _cert_error(message,http_code=400):
    code={400:'PKI_INVALID_REQUEST',401:'SESSION_INVALID',403:'FORBIDDEN',
          422:'PKI_VALIDATION_FAILED',503:'PKI_UNAVAILABLE'}.get(http_code,'PKI_ERROR')
    return jsonify(ok=False,status=config.STATE_ERROR,code=code,message=str(message)),http_code


def _cert_get_json():
    data=request.get_json(silent=True)
    if not isinstance(data,dict):
        raise ValueError('JSON object required')
    return data


def _cert_validate_role(value):
    if not isinstance(value,str) or value.strip().lower() not in CERT_FILES:
        raise ValueError('role must be master or slave')
    return value.strip().lower()


def _cert_validate_fingerprint(value):
    if not isinstance(value,str):
        raise ValueError('fingerprint required')
    value=value.replace(':','').strip().upper()
    if not re.fullmatch('[0-9A-F]{64}',value):
        raise ValueError('full SHA-256 fingerprint required')
    return value


def _cert_build_identity_args(data):
    import ipaddress
    if set(data)-{'role','name','ip','dns'}:
        raise ValueError('unknown CSR field')
    role=_cert_validate_role(data.get('role'))
    name=data.get('name')
    if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',name):
        raise ValueError('invalid identity name')
    arguments=['--role',role,'--name',name]
    for field in ('ip','dns'):
        values=data.get(field,[])
        if isinstance(values,str):
            values=[values]
        if not isinstance(values,list) or len(values)>32:
            raise ValueError('invalid SAN list')
        for value in values:
            if not isinstance(value,str):
                raise ValueError('SAN must be text')
            if field=='ip':
                value=str(ipaddress.ip_address(value))
            elif len(value)>253 or not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?',part) for part in value.split('.')):
                raise ValueError('invalid DNS SAN')
            arguments+=['--'+field,value]
    return role,name,arguments


def _cert_run_script(command):
    if not CERT_SCRIPT.is_file():
        raise CertificateScriptError('certificate script not installed')
    directory=Path(current_app.config.get('MODBUS_CERT_DIR',str(CERT_DIR)))
    result=subprocess.run([sys.executable,str(CERT_SCRIPT),'--dir',str(directory),
        '--config',str(config.INI_PATH),*command],stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        text=True,encoding='utf-8',errors='replace',timeout=CERT_TIMEOUT,check=False)
    if result.returncode:
        current_app.logger.error('PKI operation %s failed: %s',command[0],result.stderr[-4000:])
        raise CertificateScriptError('certificate operation rejected')
    return result.stdout.strip()


def _pki_errors(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except ValueError:
            return _cert_error('invalid PKI request',400)
        except CertificateScriptError:
            return _cert_error('certificate or CSR validation failed; see server audit',422)
        except (OSError,subprocess.SubprocessError):
            current_app.logger.exception('PKI service unavailable')
            return _cert_error('PKI service unavailable',503)
    return wrapped


def _https_pki(command, apply=False):
    folder=Path(__file__).resolve().parents[1]/'script'
    arguments=(['bash',str(folder/'enable_https.sh'),'--apply'] if apply else
        [sys.executable,str(folder/'https_certificates.py'),'--config',str(config.INI_PATH),
         '--dir',current_app.config.get('HTTPS_CERT_DIR','/etc/ssl/g3'),*command])
    environment=dict(os.environ,LC_INI_PATH=str(config.INI_PATH),
                     HTTPS_CERT_DIR=current_app.config.get('HTTPS_CERT_DIR','/etc/ssl/g3'))
    result=subprocess.run(arguments,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                          timeout=120,env=environment,text=True)
    if result.returncode:
        current_app.logger.error('HTTPS PKI operation failed: %s',result.stderr[-4000:])
        if apply:
            raise OSError('HTTPS configuration application failed')
        raise CertificateScriptError('HTTPS PKI failed')
    return json.loads(result.stdout) if not apply else dict(applied=True)


def _uploaded_pki(directory):
    result={}
    for name in ('file','chain'):
        upload=request.files.get(name)
        if upload is None:
            if name=='file':
                raise ValueError('certificate file required')
            continue
        data=upload.stream.read(MAX_CERT_SIZE+1)
        if not data or len(data)>MAX_CERT_SIZE:
            raise ValueError('invalid certificate upload size')
        path=Path(directory)/(name+'.pem')
        path.write_bytes(data)
        result[name]=path
    return result


@g3_bp.route('/api/cert/mode',methods=['GET'])
@cert_admin_required
@_pki_errors
def certificate_mode():
    from script.pki_common import read_config
    settings=read_config(config.INI_PATH)
    return _cert_success('certificate mode',dict(mode=settings['mode'],ca_configured=settings['ca_file'].is_file()))


@g3_bp.route('/api/cert/csr',methods=['POST'])
@cert_admin_required
@_pki_errors
def create_identity_csr():
    role,_,arguments=_cert_build_identity_args(_cert_get_json())
    _cert_run_script(['csr',*arguments])
    return _cert_success('CSR ready for external CA signing',dict(role=role,csr_ready=True))


@g3_bp.route('/api/cert/csr/export',methods=['GET'])
@cert_admin_required
@_pki_errors
def export_identity_csr():
    role=_cert_validate_role(request.args.get('role'))
    with tempfile.TemporaryDirectory(prefix='csr-export-') as directory:
        path=Path(directory)/'identity.csr'
        _cert_run_script(['csr-export','--role',role,'--out',str(path)])
        data=path.read_bytes()
    return send_file(io.BytesIO(data),as_attachment=True,download_name=role+'.csr',mimetype='application/pkcs10')


@g3_bp.route('/api/cert/identity/import',methods=['POST'])
@cert_admin_required
@_pki_errors
def import_signed_identity():
    role=_cert_validate_role(request.form.get('role'))
    with tempfile.TemporaryDirectory(prefix='identity-import-') as directory:
        files=_uploaded_pki(directory)
        command=['identity-import','--role',role,'--cert',str(files['file'])]
        if 'chain' in files:
            command+=['--chain',str(files['chain'])]
        _cert_run_script(command)
    return _cert_success('CA-signed Modbus identity imported',dict(role=role,restart_required=True))


@g3_bp.route('/api/cert/ca',methods=['GET'])
@cert_admin_required
@_pki_errors
def shared_ca_status():
    from script.pki_common import read_config,certificates,fingerprint,validate_roots
    settings=read_config(config.INI_PATH)
    data=validate_roots(settings['ca_file'].read_bytes())
    return _cert_success('shared CA trust',dict(mode=settings['mode'],fingerprints=[fingerprint(cert) for cert in certificates(data)]))


@g3_bp.route('/api/cert/ca/import',methods=['POST'])
@cert_admin_required
@_pki_errors
def import_shared_ca():
    fingerprints=[_cert_validate_fingerprint(value) for value in request.form.getlist('fingerprint')]
    if not fingerprints:
        raise ValueError('trusted-channel CA fingerprints are required')
    with tempfile.TemporaryDirectory(prefix='ca-import-') as directory:
        files=_uploaded_pki(directory)
        command=['ca-import','--cert',str(files['file'])]
        for fingerprint in fingerprints:
            command+=['--fingerprint',fingerprint]
        _cert_run_script(command)
    return _cert_success('shared CA trust imported',dict(restart_required=True))


@g3_bp.route('/api/cert/https/csr',methods=['POST'])
@cert_admin_required
@_pki_errors
def create_https_csr():
    result=_https_pki(['csr'])
    return _cert_success('HTTPS CSR ready',dict(csr_ready=True,sha256=result['sha256'],device_ips=result['device_ips']))


@g3_bp.route('/api/cert/https/csr/export',methods=['GET'])
@cert_admin_required
@_pki_errors
def export_https_csr():
    with tempfile.TemporaryDirectory(prefix='https-csr-') as directory:
        path=Path(directory)/'https.csr'
        _https_pki(['csr-export','--out',str(path)])
        data=path.read_bytes()
    return send_file(io.BytesIO(data),as_attachment=True,download_name='https.csr',mimetype='application/pkcs10')


@g3_bp.route('/api/cert/https/identity/import',methods=['POST'])
@cert_admin_required
@_pki_errors
def import_https_identity():
    with tempfile.TemporaryDirectory(prefix='https-identity-') as directory:
        files=_uploaded_pki(directory)
        command=['identity-import','--cert',str(files['file'])]
        if 'chain' in files:
            command+=['--chain',str(files['chain'])]
        result=_https_pki(command)
    return _cert_success('HTTPS leaf and intermediates imported',result)


@g3_bp.route('/api/cert/https/apply',methods=['POST'])
@cert_admin_required
@_pki_errors
def apply_https_identity():
    return _cert_success('HTTPS configuration applied',_https_pki([],apply=True))


@g3_bp.route('/api/cert/https/status',methods=['GET'])
@cert_admin_required
@_pki_errors
def https_identity_status():
    return _cert_success('HTTPS CA identity status',_https_pki(['check']))



@g3_bp.route('/api/cert/identity',methods=['GET'])
@cert_admin_required
@_pki_errors
def get_certificate_identity():
    role=_cert_validate_role(request.args.get('role'))
    return _cert_success('CA identity information',dict(role=role,certificate=_cert_run_script(['show','--role',role])))


@g3_bp.route('/api/cert/check',methods=['GET'])
@cert_admin_required
@_pki_errors
def check_certificate():
    role=_cert_validate_role(request.args.get('role'))
    _cert_run_script(['check','--role',role])
    return _cert_success('CA chain, role and private key verified',dict(role=role,valid=True,chain_verified=True,revocation_status='unavailable'))


@g3_bp.route('/api/cert/export',methods=['GET'])
@cert_admin_required
@_pki_errors
def export_certificate():
    role=_cert_validate_role(request.args.get('role'))
    _cert_run_script(['check','--role',role])
    with tempfile.TemporaryDirectory(prefix='certificate-export-') as directory:
        path=Path(directory)/'identity.pem'
        _cert_run_script(['export','--role',role,'--out',str(path)])
        data=path.read_bytes()
    return send_file(io.BytesIO(data),as_attachment=True,download_name=role+'-fullchain.crt',mimetype='application/x-pem-file')


@g3_bp.route('/api/cert/generate',methods=['POST'])
@g3_bp.route('/api/cert/renew',methods=['POST'])
@g3_bp.route('/api/cert/trust-add',methods=['POST'])
@g3_bp.route('/api/cert/trust-remove',methods=['POST'])
@g3_bp.route('/api/cert/trust-list',methods=['GET'])
@cert_admin_required
def retired_certificate_operation():
    return jsonify(ok=False,code='CA_CSR_REQUIRED',message='Use CSR, CA trust and signed identity import APIs'),410
