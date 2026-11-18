"""设备证书接口：通用 CSR 流程，以及外部私钥/证书的定制批次导入流程。

Modbus 主机、从机和 HTTPS 使用独立身份；私钥始终保留在各自槽位。
这里只记录操作元数据，不打印请求体、证书/CSR 正文或私钥。
"""
from functools import wraps
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from time import monotonic

import config
from flask import request, jsonify, send_file, current_app, g
from routes.route_g3 import g3_bp
from utils.utils import DPrint

CERT_SCRIPT = Path('/home/zlg/app/script/modbus_certs.py')
CERT_DIR = Path('/etc/ems/modbus')
CERT_TIMEOUT = 60
MAX_CERT_SIZE = 1024 * 1024
CERT_FILES = {'master': 'master.crt', 'slave': 'slave.crt'}


class CertificateScriptError(Exception):
    """证书脚本缺失或拒绝操作，由接口统一映射为 422。"""


def _cert_log(event, *, level='INFO', **details):
    """使用项目统一打印，关联已认证操作人和接口，字段使用 repr 避免换行混入。"""
    user = getattr(g, 'current_user', None)
    context = {
        'operator': user.get('username', '-') if isinstance(user, dict) else '-',
        'method': request.method,
        'path': request.path,
        'ip': request.remote_addr,
        'pki_mode': getattr(g, 'pki_mode', '-'),
        **details,
    }
    fields = ' '.join(f'{key}={value!r}' for key, value in context.items())
    DPrint(f'[PKI] {event}: {fields}', level=level)


def cert_admin_required(function):
    """保留原有管理员授权，同时记录请求开始、最终状态和耗时。"""
    @wraps(function)
    def wrapped(*args, **kwargs):
        started = monotonic()
        user = getattr(g, 'current_user', None)
        if not isinstance(user, dict):
            _cert_log('拒绝请求：未认证', level='WARNING', status=401)
            return _cert_error('authentication required', 401)
        if user.get('permission') not in config.PERMISSION_TABLE.get('usermanage', []):
            _cert_log('拒绝请求：需要管理员权限', level='WARNING', status=403)
            return _cert_error('administrator permission required', 403)
        if not request.path.startswith(('/api/cert/custom/', '/api/cert/goose/')):
            # Only the HTTP parameter changes. Legacy callers and CLI tools keep their behavior.
            try:
                _cert_validate_general_mode()
            except ValueError:
                _cert_log('通用接口 PKI 模式参数无效', level='WARNING', status=400)
                return _cert_error('pki_mode must be general for this endpoint', 400)
        _cert_log('开始操作', operation=function.__name__)
        try:
            response = function(*args, **kwargs)
        except Exception:
            # 未映射异常继续交给 Flask，保持原有异常处理行为。
            _cert_log('操作异常', level='ERROR', operation=function.__name__,
                      elapsed_ms=round((monotonic() - started) * 1000, 1))
            current_app.logger.exception('Unhandled PKI error: %s', function.__name__)
            raise
        status = response[1] if isinstance(response, tuple) else response.status_code
        _cert_log('操作成功' if status < 400 else '操作失败',
                  level='INFO' if status < 400 else 'WARNING',
                  operation=function.__name__, status=status,
                  target=getattr(g, 'audit_target', '-'),
                  elapsed_ms=round((monotonic() - started) * 1000, 1))
        return response
    return wrapped


def _cert_validate_general_mode():
    """pki_mode限制为general或trina；不允许借参数跳过 CSR 校验。"""
    values = request.args.getlist('pki_mode') + request.form.getlist('pki_mode')
    data = request.get_json(silent=True) if request.is_json else None
    if isinstance(data, dict) and 'pki_mode' in data:
        values.append(data['pki_mode'])
    if any(((value != 'general') and (value != 'trina')) for value in values):
        raise ValueError('pki_mode must be general or trina')
    g.pki_mode = 'general'
    return 'general'


def _cert_success(message, data=None):
    payload = {'status': config.STATE_DONE, 'message': message}
    if data is not None:
        payload['data'] = data
    return jsonify(payload), 200


def _cert_error(message, http_code=400):
    codes = {
        400: 'PKI_INVALID_REQUEST',
        401: 'SESSION_INVALID',
        403: 'FORBIDDEN',
        422: 'PKI_VALIDATION_FAILED',
        503: 'PKI_UNAVAILABLE',
    }
    code = codes.get(http_code, 'PKI_ERROR')
    return jsonify(ok=False, status=config.STATE_ERROR, code=code, message=str(message)), http_code


def _cert_get_json():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError('JSON object required')
    return data


def _cert_validate_role(value):
    if not isinstance(value, str) or value.strip().lower() not in CERT_FILES:
        raise ValueError('role must be master or slave')
    role = value.strip().lower()
    g.audit_target = 'Modbus主机身份' if role == 'master' else 'Modbus从机身份'
    _cert_log('确认身份角色', role=role)
    return role


def _cert_validate_fingerprint(value):
    if not isinstance(value, str):
        raise ValueError('fingerprint required')
    value = value.replace(':', '').strip().upper()
    if not re.fullmatch('[0-9A-F]{64}', value):
        raise ValueError('full SHA-256 fingerprint required')
    return value


def _cert_build_identity_args(data):
    """校验 Modbus 身份名及 SAN，返回规范角色、名称和脚本参数。"""
    if set(data) - {'role', 'name', 'ip', 'dns', 'pki_mode'}:
        raise ValueError('unknown CSR field')
    role = _cert_validate_role(data.get('role'))
    name = data.get('name')
    if not isinstance(name, str) or not re.fullmatch(
        r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', name
    ):
        raise ValueError('invalid identity name')
    arguments = ['--role', role, '--name', name]
    for field in ('ip', 'dns'):
        values = data.get(field, [])
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list) or len(values) > 32:
            raise ValueError('invalid SAN list')
        for value in values:
            if not isinstance(value, str):
                raise ValueError('SAN must be text')
            if field == 'ip':
                value = str(ipaddress.ip_address(value))
            elif len(value) > 253 or not all(
                re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', part)
                for part in value.split('.')
            ):
                raise ValueError('invalid DNS SAN')
            arguments += ['--' + field, value]
    _cert_log('CSR 参数校验通过', role=role, name=name,
              ip_count=arguments.count('--ip'), dns_count=arguments.count('--dns'))
    return role, name, arguments


def _cert_run_script(command):
    """执行 Modbus 证书脚本；不记录可能含证书正文的标准输出。"""
    if not CERT_SCRIPT.is_file():
        _cert_log('Modbus 证书脚本未安装', level='ERROR', script=str(CERT_SCRIPT))
        raise CertificateScriptError('certificate script not installed')
    directory = Path(current_app.config.get('MODBUS_CERT_DIR', str(CERT_DIR)))
    started = monotonic()
    _cert_log('执行 Modbus 证书脚本', operation=command[0], directory=str(directory),
              timeout_seconds=CERT_TIMEOUT)
    arguments = [
        sys.executable, str(CERT_SCRIPT), '--dir', str(directory),
        '--config', str(config.INI_PATH), *command,
    ]
    result = subprocess.run(
        arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding='utf-8', errors='replace', timeout=CERT_TIMEOUT, check=False,
        env=dict(os.environ, MODBUS_CERT_DIR=str(directory),
                 HTTPS_CERT_DIR=current_app.config.get('HTTPS_CERT_DIR', '/etc/ssl/g3')),
    )
    if result.returncode:
        _cert_log('Modbus 证书脚本拒绝操作', level='ERROR', operation=command[0],
                  returncode=result.returncode)
        current_app.logger.error('PKI operation %s failed: %s', command[0], result.stderr[-4000:])
        raise CertificateScriptError('certificate operation rejected')
    _cert_log('Modbus 证书脚本完成', operation=command[0],
              elapsed_ms=round((monotonic() - started) * 1000, 1))
    return result.stdout.strip()


def _pki_errors(function):
    """统一保留参数错误 400、证书校验失败 422、服务不可用 503 的响应。"""
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except ValueError as error:
            _cert_log('参数或脚本结果格式无效', level='WARNING', reason=str(error)[:512])
            return _cert_error('invalid PKI request', 400)
        except CertificateScriptError as error:
            _cert_log('证书或 CSR 校验失败', level='WARNING', reason=str(error))
            return _cert_error('certificate or CSR validation failed; see server audit', 422)
        except subprocess.TimeoutExpired as error:
            _cert_log('证书脚本执行超时', level='ERROR', timeout_seconds=error.timeout)
            return _cert_error('PKI service unavailable', 503)
        except (OSError, ImportError, subprocess.SubprocessError):
            _cert_log('证书服务不可用', level='ERROR')
            current_app.logger.exception('PKI service unavailable')
            return _cert_error('PKI service unavailable', 503)
    return wrapped


def _https_pki(command, apply=False):
    """管理 HTTPS 证书；apply 单独调用部署脚本，成功后不解析 JSON。"""
    folder = Path(__file__).resolve().parents[1] / 'script'
    certificate_dir = current_app.config.get('HTTPS_CERT_DIR', '/etc/ssl/g3')
    if apply:
        arguments = ['bash', str(folder / 'enable_https.sh'), '--apply']
    else:
        arguments = [
            sys.executable, str(folder / 'https_certificates.py'),
            '--config', str(config.INI_PATH), '--dir', certificate_dir, *command,
        ]
    environment = dict(
        os.environ, LC_INI_PATH=str(config.INI_PATH), HTTPS_CERT_DIR=certificate_dir,
        MODBUS_CERT_DIR=str(current_app.config.get('MODBUS_CERT_DIR', str(CERT_DIR))),
    )
    operation = 'apply' if apply else command[0]
    started = monotonic()
    _cert_log('执行 HTTPS 证书脚本', operation=operation,
              directory=environment['HTTPS_CERT_DIR'], timeout_seconds=120)
    result = subprocess.run(
        arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=120, env=environment, text=True,
    )
    if result.returncode:
        _cert_log('HTTPS 证书脚本失败', level='ERROR', operation=operation,
                  returncode=result.returncode)
        current_app.logger.error('HTTPS PKI operation failed: %s', result.stderr[-4000:])
        if apply:
            raise OSError('HTTPS configuration application failed')
        raise CertificateScriptError('HTTPS PKI failed')
    data = dict(applied=True) if apply else json.loads(result.stdout)
    _cert_log('HTTPS 证书脚本完成', operation=operation,
              elapsed_ms=round((monotonic() - started) * 1000, 1))
    return data


def _uploaded_pki(directory):
    """接收必选 file 和可选 chain，各限 1 MiB，使用固定临时文件名。"""
    result = {}
    for name in ('file', 'chain'):
        upload = request.files.get(name)
        if upload is None:
            if name == 'file':
                raise ValueError('certificate file required')
            continue
        data = upload.stream.read(MAX_CERT_SIZE + 1)
        if not data or len(data) > MAX_CERT_SIZE:
            raise ValueError('invalid certificate upload size')
        path = Path(directory) / (name + '.pem')
        path.write_bytes(data)
        _cert_log('接收证书上传', field=name, size_bytes=len(data))
        result[name] = path
    return result


@g3_bp.route('/api/cert/mode', methods=['GET'])
@cert_admin_required
@_pki_errors
def certificate_mode():
    """GET：查询证书模式及共享 CA 文件是否已配置。"""
    from script.pki_common import read_config

    settings = read_config(config.INI_PATH)
    data = dict(mode=settings['mode'], ca_configured=settings['ca_file'].is_file())
    _cert_log('查询证书模式', **data)
    return _cert_success('certificate mode', data)


@g3_bp.route('/api/cert/csr', methods=['POST'])
@cert_admin_required
@_pki_errors
def create_identity_csr():
    """POST JSON：role、name 必填，ip/dns 为可选 SAN；生成供外部 CA 签发的 CSR。"""
    role, _, arguments = _cert_build_identity_args(_cert_get_json())
    _cert_run_script(['csr', *arguments])
    return _cert_success('CSR ready for external CA signing', dict(role=role, csr_ready=True))


@g3_bp.route('/api/cert/csr/export', methods=['GET'])
@cert_admin_required
@_pki_errors
def export_identity_csr():
    """GET ?role=master|slave：下载该角色 CSR，不包含私钥。"""
    role = _cert_validate_role(request.args.get('role'))
    with tempfile.TemporaryDirectory(prefix='csr-export-') as directory:
        path = Path(directory) / 'identity.csr'
        _cert_run_script(['csr-export', '--role', role, '--out', str(path)])
        data = path.read_bytes()
    _cert_log('准备导出 Modbus CSR', role=role, size_bytes=len(data))
    return send_file(
        io.BytesIO(data), as_attachment=True,
        download_name=role + '.csr', mimetype='application/pkcs10',
    )


@g3_bp.route('/api/cert/identity/import', methods=['POST'])
@cert_admin_required
@_pki_errors
def import_signed_identity():
    """POST multipart：role、file 必填，chain 可选；导入后需重启相关服务。"""
    role = _cert_validate_role(request.form.get('role'))
    with tempfile.TemporaryDirectory(prefix='identity-import-') as directory:
        files = _uploaded_pki(directory)
        command = ['identity-import', '--role', role, '--cert', str(files['file'])]
        if 'chain' in files:
            command += ['--chain', str(files['chain'])]
        _cert_run_script(command)
    _cert_log('Modbus 身份证书已导入', role=role, restart_required=True)
    return _cert_success(
        'CA-signed Modbus identity imported', dict(role=role, restart_required=True),
    )


@g3_bp.route('/api/cert/ca', methods=['GET'])
@cert_admin_required
@_pki_errors
def shared_ca_status():
    """GET：校验共享 CA 根证书并返回其 SHA-256 指纹。"""
    from script.pki_common import read_config, certificates, fingerprint, validate_roots

    settings = read_config(config.INI_PATH)
    data = validate_roots(settings['ca_file'].read_bytes())
    fingerprints = [fingerprint(cert) for cert in certificates(data)]
    _cert_log('共享 CA 校验通过', certificate_count=len(fingerprints))
    return _cert_success('shared CA trust', dict(mode=settings['mode'], fingerprints=fingerprints))


@g3_bp.route('/api/cert/ca/import', methods=['POST'])
@cert_admin_required
@_pki_errors
def import_shared_ca():
    """POST multipart：file 和可信渠道确认的 fingerprint 必填，指纹可重复传入。"""
    fingerprints = [
        _cert_validate_fingerprint(value)
        for value in request.form.getlist('fingerprint')
    ]
    if not fingerprints:
        raise ValueError('trusted-channel CA fingerprints are required')
    with tempfile.TemporaryDirectory(prefix='ca-import-') as directory:
        files = _uploaded_pki(directory)
        command = ['ca-import', '--cert', str(files['file'])]
        for fingerprint in fingerprints:
            command += ['--fingerprint', fingerprint]
        _cert_run_script(command)
    _cert_log('共享 CA 已导入', fingerprint_count=len(fingerprints), restart_required=True)
    return _cert_success('shared CA trust imported', dict(restart_required=True))


@g3_bp.route('/api/cert/https/csr', methods=['POST'])
@cert_admin_required
@_pki_errors
def create_https_csr():
    """POST：按设备配置生成 HTTPS CSR，返回摘要和设备 IP。"""
    result = _https_pki(['csr'])
    return _cert_success(
        'HTTPS CSR ready',
        dict(csr_ready=True, sha256=result['sha256'], device_ips=result['device_ips']),
    )


@g3_bp.route('/api/cert/https/csr/export', methods=['GET'])
@cert_admin_required
@_pki_errors
def export_https_csr():
    """GET：下载 HTTPS CSR，临时目录退出后使用内存数据发送。"""
    with tempfile.TemporaryDirectory(prefix='https-csr-') as directory:
        path = Path(directory) / 'https.csr'
        _https_pki(['csr-export', '--out', str(path)])
        data = path.read_bytes()
    _cert_log('准备导出 HTTPS CSR', size_bytes=len(data))
    return send_file(
        io.BytesIO(data), as_attachment=True,
        download_name='https.csr', mimetype='application/pkcs10',
    )


@g3_bp.route('/api/cert/https/identity/import', methods=['POST'])
@cert_admin_required
@_pki_errors
def import_https_identity():
    """POST multipart：file 必填、chain 可选；导入后通过 apply 接口应用配置。"""
    with tempfile.TemporaryDirectory(prefix='https-identity-') as directory:
        files = _uploaded_pki(directory)
        command = ['identity-import', '--cert', str(files['file'])]
        if 'chain' in files:
            command += ['--chain', str(files['chain'])]
        result = _https_pki(command)
    return _cert_success('HTTPS leaf and intermediates imported', result)


@g3_bp.route('/api/cert/https/apply', methods=['POST'])
@cert_admin_required
@_pki_errors
def apply_https_identity():
    """Apply all pending certificate changes; preserve the existing no-body API."""
    from script import pki_common as pki

    settings = pki.read_config(config.INI_PATH)
    services = {}
    https_dir = Path(current_app.config.get('HTTPS_CERT_DIR', '/etc/ssl/g3'))
    with pki.operation_lock(settings):
        pending = pki.pending_services(settings)
        # Keep support for HTTPS identities imported before shared markers existed.
        if (https_dir / '.reload-required').exists() and 'nginx' not in pending:
            pending.insert(0, 'nginx')
        for service in pending:
            _cert_log('应用证书变更', service=service)
            action = 'reload-or-start' if service == 'nginx' else 'restart'
            try:
                if service == 'nginx':
                    _https_pki([], apply=True)
                else:
                    for arguments in (
                        ['systemctl', '--no-ask-password', 'restart', 'tems.service'],
                        ['systemctl', '--no-ask-password', 'is-active', '--quiet', 'tems.service'],
                    ):
                        result = subprocess.run(arguments, capture_output=True, text=True, timeout=120, check=False)
                        if result.returncode:
                            current_app.logger.error('Certificate service application failed: %s', result.stderr[-2000:])
                            raise OSError('tems service operation failed')
                pki.pending_path(settings, service).unlink(missing_ok=True)
                services[service] = dict(action=action, status='success')
                _cert_log('证书服务应用成功', service=service)
            except (OSError, subprocess.SubprocessError):
                services[service] = dict(action=action, status='failed')
                _cert_log('证书服务应用失败，保留待应用标记', level='ERROR', service=service)
                current_app.logger.exception('Certificate service application failed: %s', service)
        remaining = pki.pending_services(settings)
        if services.get('nginx', {}).get('status') == 'failed' and 'nginx' not in remaining:
            remaining.append('nginx')
        try:
            _custom_pki().sync_service_states()
        except (OSError, ValueError):
            # A damaged historical batch must not turn a successful service action
            # into a failed legacy response. Status will recheck when queried.
            current_app.logger.exception('Could not synchronize custom PKI service state')
    data = dict(changed=bool(services), applied=not remaining, services=services, pending=remaining)
    if remaining:
        return jsonify(ok=False, status=config.STATE_ERROR, code='CERTIFICATE_APPLY_FAILED',
                       message='Some certificate changes could not be applied', data=data), 503
    return _cert_success('Certificate changes applied' if services else 'No certificate changes pending', data)


@g3_bp.route('/api/cert/crls', methods=['GET'])
@cert_admin_required
@_pki_errors
def get_crls():
    """List authenticated CRLs, freshness and services awaiting application."""
    from script import crl_store, pki_common as pki

    settings = pki.read_config(config.INI_PATH)
    try:
        entries = crl_store.inventory(settings)
    except ValueError as error:
        raise CertificateScriptError(str(error)) from error
    return _cert_success('Certificate revocation lists',
                         dict(crls=entries, pending=pki.pending_services(settings)))


@g3_bp.route('/api/cert/crls/import', methods=['POST'])
@cert_admin_required
@_pki_errors
def import_crls():
    """Multipart file: PEM/DER CRL; optional chain: PEM issuer/intermediates."""
    from script import crl_store, pki_common as pki

    settings = pki.read_config(config.INI_PATH)
    with tempfile.TemporaryDirectory(prefix='crl-import-') as directory:
        files = _uploaded_pki(directory)
        try:
            result = crl_store.import_crls(settings, files['file'].read_bytes(),
                                           files['chain'].read_bytes() if 'chain' in files else b'')
        except ValueError as error:
            raise CertificateScriptError(str(error)) from error
    for entry in result['crls']:
        _cert_log('CRL 已验证并保存', issuer=entry['issuer'], crl_number=entry['crlNumber'],
                  freshness=entry['status'], revoked_count=entry['revokedCount'])
    result['pending'] = pki.pending_services(settings)
    return _cert_success('CRLs staged; apply the matching custom batch' if result.get('staged')
                         else 'CRLs imported; apply to restart Modbus', result)


@g3_bp.route('/api/cert/https/status', methods=['GET'])
@cert_admin_required
@_pki_errors
def https_identity_status():
    """GET：通过 HTTPS 证书脚本检查当前 CA 身份状态。"""
    return _cert_success('HTTPS CA identity status', _https_pki(['status']))


@g3_bp.route('/api/cert/identity', methods=['GET'])
@cert_admin_required
@_pki_errors
def get_certificate_identity():
    """GET ?role=master|slave：查询对应角色的公开证书信息。"""
    role = _cert_validate_role(request.args.get('role'))
    certificate = _cert_run_script(['show', '--role', role])
    return _cert_success('CA identity information', dict(role=role, certificate=certificate))


@g3_bp.route('/api/cert/check', methods=['GET'])
@cert_admin_required
@_pki_errors
def check_certificate():
    """GET ?role=master|slave：校验链、角色、私钥匹配及已部署 CRL。"""
    role = _cert_validate_role(request.args.get('role'))
    _cert_run_script(['check', '--role', role])
    from script import crl_store, pki_common as pki
    settings = pki.read_config(config.INI_PATH)
    directory = Path(current_app.config.get('MODBUS_CERT_DIR', str(CERT_DIR)))
    revocation = crl_store.certificate_status((directory / CERT_FILES[role]).read_bytes(),
                                             settings['ca_file'], settings['crl_file'])
    return _cert_success(
        'CA chain, role and private key verified',
        dict(role=role, valid=True, chain_verified=True, revocation_status=revocation['revocationStatus']),
    )


@g3_bp.route('/api/cert/export', methods=['GET'])
@cert_admin_required
@_pki_errors
def export_certificate():
    """GET ?role=master|slave：先校验身份，再导出公开证书链。"""
    role = _cert_validate_role(request.args.get('role'))
    _cert_run_script(['check', '--role', role])
    with tempfile.TemporaryDirectory(prefix='certificate-export-') as directory:
        path = Path(directory) / 'identity.pem'
        _cert_run_script(['export', '--role', role, '--out', str(path)])
        data = path.read_bytes()
    _cert_log('准备导出 Modbus 证书链', role=role, size_bytes=len(data))
    return send_file(
        io.BytesIO(data), as_attachment=True,
        download_name=role + '-fullchain.crt', mimetype='application/x-pem-file',
    )


def _custom_pki():
    from script.custom_pki import CustomPKI
    return CustomPKI(
        config.INI_PATH,
        current_app.config.get('MODBUS_CERT_DIR', str(CERT_DIR)),
        current_app.config.get('HTTPS_CERT_DIR', '/etc/ssl/g3'),
        backend=os.environ.get('MODBUS_KEY_BACKEND', 'file'),
    )


def _custom_mode(data):
    if data.get('pki_mode') != 'trina':
        raise ValueError('pki_mode must be trina for this endpoint')
    g.pki_mode = 'trina'


def _custom_call(function, *args, **kwargs):
    """区分批次冲突与证书校验失败；响应中不返回私钥材料或私钥摘要。"""
    from script.custom_pki import Conflict
    try:
        state = function(*args, **kwargs)
    except Conflict as error:
        _cert_log('定制 PKI 批次冲突', level='WARNING', reason=str(error))
        return jsonify(ok=False, status=config.STATE_ERROR, code='PKI_BATCH_CONFLICT',
                       message='Custom PKI batch conflict; inspect server log'), 409
    except ValueError as error:
        if function.__name__ == 'upload' and args and args[0] == 'key':
            _cert_log('定制 PKI 私钥校验拒绝', level='WARNING', role=kwargs.get('role'),
                      batch_id=kwargs.get('batch_id') or '-', reason=str(error))
        raise CertificateScriptError(str(error)) from error
    return {key: value for key, value in state.items() if key not in ('active_hashes', 'base_hashes')}


def _custom_import(part):
    """四个导入操作仅更新待应用批次，绝不覆盖正在使用的身份。"""
    _custom_mode(request.form)
    role = request.form.get('role') if part != 'ca' else None
    if part != 'ca' and role not in ('master', 'slave', 'https'):
        raise ValueError('role must be master, slave or https')
    clear = request.form.get('clear') == 'true'
    upload = request.files.get('file')
    if clear:
        if part != 'chain' or upload is not None:
            raise ValueError('clear=true is only valid for a chain without a file')
        data = b''
    else:
        if upload is None:
            raise ValueError('file required')
        data = upload.stream.read(MAX_CERT_SIZE + 1)
        if not data or len(data) > MAX_CERT_SIZE:
            raise ValueError('invalid upload size')
    g.audit_target = '定制PKI信任根' if part == 'ca' else '定制PKI身份:' + role
    state = _custom_call(
        _custom_pki().upload, part, data, role=role,
        batch_id=request.form.get('batch_id') or None,
        expected=request.form.getlist('fingerprint'), actor=g.current_user.get('username', '-'),
    )
    if isinstance(state, tuple):
        return state
    if part == 'key':
        _cert_log('定制 PKI 普通 RSA 私钥校验通过', role=role, batch_id=state['batch_id'],
                  key_algorithm='RSA', allowed_bits='2048/3072')
    _cert_log('定制 PKI 材料已暂存', part=part, role=role, batch_id=state['batch_id'], size_bytes=len(data))
    return _cert_success('Custom PKI material staged; use custom apply to activate', state)


@g3_bp.route('/api/cert/custom/key/import', methods=['POST'])
@cert_admin_required
@_pki_errors
def custom_key_import():
    """Multipart pki_mode=trina, role, file, optional batch_id; unencrypted PEM RSA-2048/3072."""
    return _custom_import('key')


@g3_bp.route('/api/cert/custom/ca/import', methods=['POST'])
@cert_admin_required
@_pki_errors
def custom_ca_import():
    """Multipart pki_mode=trina, file, trusted-channel fingerprint(s), optional batch_id."""
    return _custom_import('ca')


@g3_bp.route('/api/cert/custom/chain/import', methods=['POST'])
@cert_admin_required
@_pki_errors
def custom_chain_import():
    """Multipart pki_mode=trina, role, file OR clear=true, optional batch_id."""
    return _custom_import('chain')


@g3_bp.route('/api/cert/custom/identity/import', methods=['POST'])
@cert_admin_required
@_pki_errors
def custom_identity_import():
    """Multipart pki_mode=trina, role, one issued leaf file, optional batch_id; no CSR required."""
    return _custom_import('identity')


def _custom_service_apply(service):
    _cert_log('定制 PKI 应用服务', service=service)
    if service == 'nginx':
        _https_pki([], apply=True)
    else:
        for command in (['systemctl', '--no-ask-password', 'restart', 'tems.service'],
                        ['systemctl', '--no-ask-password', 'is-active', '--quiet', 'tems.service']):
            result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
            if result.returncode:
                current_app.logger.error('Custom PKI tems application failed: %s', result.stderr[-2000:])
                raise OSError('tems application failed')


@g3_bp.route('/api/cert/custom/apply', methods=['POST'])
@cert_admin_required
@_pki_errors
def custom_pki_apply():
    """JSON {pki_mode:trina,batch_id}: validate, journal-install, apply services; retryable."""
    data = _cert_get_json()
    _custom_mode(data)
    g.audit_target = '定制PKI批次:' + str(data.get('batch_id', ''))[:32]
    state = _custom_call(_custom_pki().apply, data.get('batch_id'), _custom_service_apply)
    if isinstance(state, tuple):
        return state
    _cert_log('定制 PKI 应用结果', batch_id=state['batch_id'], status=state['status'], pending=state['pending'])
    if state['status'] != 'applied':
        return jsonify(ok=False, status=config.STATE_ERROR, code='CUSTOM_PKI_APPLY_FAILED',
                       message='Files installed; service application failed; retry this batch', data=state), 503
    return _cert_success('Custom PKI batch applied', state)


@g3_bp.route('/api/cert/custom/status', methods=['GET'])
@cert_admin_required
@_pki_errors
def custom_pki_status():
    """GET ?pki_mode=trina&batch_id=...: public batch state, never file contents."""
    _custom_mode(request.args)
    state = _custom_call(_custom_pki().status, request.args.get('batch_id'))
    return state if isinstance(state, tuple) else _cert_success('Custom PKI batch state', state)


@g3_bp.route('/api/cert/generate', methods=['POST'])
@g3_bp.route('/api/cert/renew', methods=['POST'])
@g3_bp.route('/api/cert/trust-add', methods=['POST'])
@g3_bp.route('/api/cert/trust-remove', methods=['POST'])
@g3_bp.route('/api/cert/trust-list', methods=['GET'])
@cert_admin_required
def retired_certificate_operation():
    """旧证书生成/续期/信任管理接口返回 410，统一使用外部 CA 签发流程。"""
    _cert_log('旧证书接口已停用', level='WARNING', status=410)
    return jsonify(
        ok=False, code='CA_CSR_REQUIRED',
        message='Use CSR, CA trust and signed identity import APIs',
    ), 410


# GOOSE uses independent PKI generations; TLS role, CA and CRL endpoints stay unchanged.
def _goose_pki():
    from script.goose_pki import GoosePKI
    g.pki_mode = 'goose'
    return GoosePKI(current_app.config.get('GOOSE_PKI_DIR',
                    os.environ.get('GOOSE_PKI_DIR', '/etc/ems/goose')))


def _goose_service_apply(service):
    if service != 'goose':
        raise ValueError('unknown GOOSE service')
    unit = current_app.config.get('GOOSE_SERVICE', 'goose_middle.service')
    if not isinstance(unit, str) or not re.fullmatch(r'[A-Za-z0-9_@.-]+\.service', unit):
        raise ValueError('invalid GOOSE_SERVICE')
    _cert_log('应用 GOOSE PKI，重启独立服务', service=unit)
    for action in (['restart', unit], ['is-active', '--quiet', unit]):
        result = subprocess.run(['systemctl', '--no-ask-password', *action],
                                capture_output=True, timeout=120, check=False)
        if result.returncode:
            raise OSError('GOOSE service application failed')


@g3_bp.route('/api/cert/goose/<part>/import', methods=['POST'])
@cert_admin_required
@_pki_errors
def import_goose_pki(part):
    """Multipart file, optional batch_id; part=identity|key|ca|crl. Stage only."""
    if part not in ('identity', 'key', 'ca', 'crl'):
        raise ValueError('invalid GOOSE PKI part')
    upload = request.files.get('file')
    if upload is None:
        raise ValueError('file required')
    data = upload.stream.read(MAX_CERT_SIZE + 1)
    if not data or len(data) > MAX_CERT_SIZE:
        raise ValueError('invalid upload size')
    g.audit_target = 'GOOSE PKI:' + part
    manager = _goose_pki()
    state = _custom_call(manager.upload, part, data,
                         batch_id=request.form.get('batch_id') or None,
                         actor=g.current_user.get('username', '-'))
    if isinstance(state, tuple):
        return state
    _cert_log('GOOSE PKI 材料已暂存', part=part, batch_id=state['batch_id'], size_bytes=len(data))
    return _cert_success('GOOSE PKI material staged; apply batch to activate', state)


@g3_bp.route('/api/cert/goose/status', methods=['GET'])
@cert_admin_required
@_pki_errors
def goose_pki_status():
    state = _custom_call(_goose_pki().status, request.args.get('batch_id'))
    return state if isinstance(state, tuple) else _cert_success('GOOSE PKI status', state)


@g3_bp.route('/api/cert/goose/apply', methods=['POST'])
@cert_admin_required
@_pki_errors
def goose_pki_apply():
    data = _cert_get_json()
    state = _custom_call(_goose_pki().apply, data.get('batch_id'), _goose_service_apply)
    if isinstance(state, tuple):
        return state
    _cert_log('GOOSE PKI 应用结果', batch_id=state['batch_id'], status=state['status'])
    if state['status'] != 'applied':
        return jsonify(ok=False, status=config.STATE_ERROR, code='GOOSE_PKI_APPLY_FAILED',
                       message='Files installed; GOOSE service application failed; retry this batch', data=state), 503
    return _cert_success('GOOSE PKI batch applied', state)
