"""设备证书接口：生成 CSR → 外部 CA 签发 → 导入证书 → 校验/导出。

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
    if set(data) - {'role', 'name', 'ip', 'dns'}:
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
        except (OSError, subprocess.SubprocessError):
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
    """POST：执行 HTTPS 配置应用脚本，可能触发 Nginx 重载。"""
    return _cert_success('HTTPS configuration applied', _https_pki([], apply=True))


@g3_bp.route('/api/cert/https/status', methods=['GET'])
@cert_admin_required
@_pki_errors
def https_identity_status():
    """GET：通过 HTTPS 证书脚本检查当前 CA 身份状态。"""
    return _cert_success('HTTPS CA identity status', _https_pki(['check']))


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
    """GET ?role=master|slave：校验证书链、角色和私钥匹配；不提供吊销状态。"""
    role = _cert_validate_role(request.args.get('role'))
    _cert_run_script(['check', '--role', role])
    return _cert_success(
        'CA chain, role and private key verified',
        dict(role=role, valid=True, chain_verified=True, revocation_status='unavailable'),
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
