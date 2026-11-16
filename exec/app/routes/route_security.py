"""安全中心接口：安全策略、状态采集、证书清单及备份恢复。

权限、CSRF 与审计入口由公共钩子处理；本模块保留各接口原有的校验和返回结构。
平台未提供的遥测能力通过 available、reason 等字段明确标记。
"""
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, current_app, g, jsonify, request, send_file
from sqlalchemy import select
from utils import security_store as store
from utils import security_audit as audit
from utils.access import ABILITIES
from utils.utils import DPrint

security_bp = Blueprint('security', __name__)
DEFAULT_NOTICE = dict(
    enabled=True,
    version=1,
    text='仅限授权人员使用。所有操作可能被记录和审计。',
    text_en='Authorized users only. All operations may be recorded and audited.',
)


def _require_write_csrf():
    """为本轮修复的写接口校验会话 Token，包括同源请求。"""
    import hmac

    supplied = request.headers.get('X-CSRF-Token', '')
    expected = getattr(g, 'csrf_token', '')
    if not supplied or not expected or not hmac.compare_digest(
        supplied.encode('utf-8'), expected.encode('utf-8')
    ):
        return jsonify(ok=False, code='CSRF_INVALID', message='CSRF token is invalid'), 403
    return None


def _collection_unavailable(code):
    """采集失败保留服务端堆栈，向客户端仅返回能力错误码。"""
    current_app.logger.exception('Security collection failed: %s', code)
    DPrint(
        f'Security collection failed: {code}; trace_id={getattr(g, "trace_id", None)}\n'
        f'{traceback.format_exc()}',
        level='ERROR',
    )
    return jsonify(ok=False, code=code, message=code), 503


def _body():
    """读取 JSON 对象；缺失、解析失败或非对象请求体统一交给参数错误处理器。"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError('INVALID_JSON')
    return data


@security_bp.errorhandler(ValueError)
def invalid_request(exc):
    """将参数异常转换为 400；仅允许规范的错误码直接用于响应。"""
    value = str(exc)
    code = value if re.fullmatch(r'[A-Z][A-Z0-9_]{1,80}', value) else 'INVALID_REQUEST'
    return jsonify(ok=False, code=code, message=code), 400


@security_bp.errorhandler(FileNotFoundError)
def missing_resource(exc):
    """将文件不存在异常转换为资源未找到响应。"""
    return jsonify(ok=False, code='RESOURCE_NOT_FOUND'), 404


@security_bp.route('/permission/login-notice', methods=['GET', 'POST'])
def login_notice():
    """查询或更新登录公告。

    请求示例：
      GET /permission/login-notice
      POST /permission/login-notice
      {"enabled": true, "text": "仅限授权人员使用。", "text_en": "Authorized users only."}

    返回：ok、enabled、text、text_en、version。text_en 可为空，不自动翻译。
    内容变化时在事务内递增版本；expectedVersion 可选，用于检查并发冲突。
    """
    if request.method == 'POST':
        error = _require_write_csrf()
        if error:
            return error
    with audit.engine().begin() as conn:
        if request.method == 'POST':
            store.lock_security(conn)
            data = _body()
            if (
                type(data.get('enabled')) is not bool
                or not isinstance(data.get('text'), str)
                or not 1 <= len(data['text']) <= 4000
            ):
                raise ValueError('INVALID_NOTICE')
            if 'text_en' in data and (
                not isinstance(data['text_en'], str) or len(data['text_en']) > 4000
            ):
                raise ValueError('INVALID_NOTICE')
            old = dict(store.get_setting(conn, 'login_notice', DEFAULT_NOTICE))
            old.setdefault('text_en', '')
            if 'expectedVersion' in data:
                if type(data['expectedVersion']) is not int:
                    raise ValueError('INVALID_NOTICE_VERSION')
                if data['expectedVersion'] != old['version']:
                    return jsonify(ok=False, code='NOTICE_CONFLICT'), 409
            # Preserve English on enable-only updates, but never pair edited Chinese
            # with a stale translation from an older client that omits text_en.
            english = data.get('text_en', old['text_en'] if old['text'] == data['text'] else '')
            notice = dict(
                enabled=data['enabled'],
                text=data['text'],
                text_en=english,
                version=old['version'] + int(
                    old['enabled'] != data['enabled'] or old['text'] != data['text']
                    or old['text_en'] != english
                ),
            )
            store.set_setting(conn, 'login_notice', notice)
            g.audit_before, g.audit_after = old, notice
        else:
            notice = dict(store.get_setting(conn, 'login_notice', DEFAULT_NOTICE))
            notice.setdefault('text_en', '')
    return jsonify(ok=True, **notice)


@security_bp.route('/api/security/password-policy')
def password_policy():
    """查询当前口令策略，返回 {ok: true, ...口令策略字段}。"""
    return jsonify(ok=True, **store.PASSWORD_POLICY)


@security_bp.route('/api/security/roles')
def roles():
    """查询角色能力映射，返回 {ok: true, abilities: {...}}。"""
    return jsonify(ok=True, abilities=ABILITIES)


@security_bp.route('/api/security/maintenance', methods=['GET', 'POST'])
def maintenance():
    """查询、进入或退出维护模式。

    请求示例：
      GET /api/security/maintenance
      POST /api/security/maintenance
      {"enabled": true, "seconds": 900, "confirm": "ENTER_MAINTENANCE", "password": "..."}

    seconds 默认 900，范围 60～3600；退出时 confirm 为 EXIT_MAINTENANCE。
    写入前重新验证当前用户口令，返回 {ok: true, ...维护状态字段}。
    """
    import time

    if request.method == 'POST':
        from routes.route_permission import _credentials_check
        data = _body()
        enabled = data.get('enabled')
        seconds = data.get('seconds', 900)
        # 先校验请求参数与确认文本，再重新验证当前用户口令。
        if (
            type(enabled) is not bool
            or type(seconds) is not int
            or not 60 <= seconds <= 3600
        ):
            raise ValueError('INVALID_MAINTENANCE_REQUEST')
        if data.get('confirm') != ('ENTER_MAINTENANCE' if enabled else 'EXIT_MAINTENANCE'):
            raise ValueError('CONFIRMATION_REQUIRED')
        _, error = _credentials_check(g.current_user['username'], data.get('password'))
        if error:
            return error
        with audit.engine().begin() as conn:
            store.lock_security(conn)
            g.audit_before = store.maintenance_state(conn)
            store.set_setting(
                conn,
                'maintenance',
                dict(
                    until=time.time() + seconds if enabled else 0,
                    operator=g.current_user['username'],
                ),
            )
            g.audit_after = store.maintenance_state(conn)
    with audit.engine().connect() as conn:
        return jsonify(ok=True, **store.maintenance_state(conn))


@security_bp.route('/api/history/status')
def history_status():
    """查询审计存储及留存状态，返回 {ok: true, ...审计状态字段}。"""
    return jsonify(ok=True, **audit.status())


@security_bp.route('/api/history/getSecurityAudit')
def security_audit_query():
    """分页查询安全审计记录。

    Query 参数交给 audit.query_records 校验和查询；参数错误返回 400 INVALID_QUERY。
    成功时直接返回审计模块提供的分页结构。
    """
    try:
        return jsonify(audit.query_records(request.args))
    except (ValueError, TypeError):
        return jsonify(ok=False, code='INVALID_QUERY', message='Invalid audit query'), 400


@security_bp.route('/api/history/export')
def history_export():
    """按请求参数导出日志，响应及导出审计由 audit.export_records 处理。"""
    return audit.export_records()


def _command(arguments, env=None):
    """执行只读采集命令；失败或超过 5 秒时返回 None。"""
    try:
        result = subprocess.run(
            arguments,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
            text=True,
            env=env,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def memory_usage():
    """读取 /proc/meminfo，返回内存总量、可用量、已用量（字节）及使用率。"""
    values = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        if key in ('MemTotal', 'MemAvailable'):
            values[key] = int(value.split()[0]) * 1024
    total, available = values['MemTotal'], values['MemAvailable']
    return dict(
        total=total,
        available=available,
        used=total - available,
        usedPercent=round((total - available) * 100 / total, 2),
    )


def certificate_inventory():
    """采集 master、slave、HTTPS 和 CA 根证书的公开信息。

    缺失文件跳过，无效文件记录 invalid；身份证书的 fullchain 仅取首张叶证书。
    有效期判断与证书链校验分别保存，不将其视为私钥校验或吊销状态检查。
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from script import pki_common as pki
    import config

    # 按角色列出证书来源，CA 路径沿用 PKI 配置中的值。
    settings = pki.read_config(config.INI_PATH)
    directory = Path(current_app.config.get('MODBUS_CERT_DIR', '/etc/ems/modbus'))
    https = Path(current_app.config.get('HTTPS_CERT_DIR', '/etc/ssl/g3'))
    paths = [
        (directory / 'master.crt', 'master'),
        (directory / 'slave.crt', 'slave'),
        (https / 'g3.crt', 'https'),
        (settings['ca_file'], 'ca-root'),
    ]
    items = []
    pending = set(pki.pending_services(settings))
    role_services = {'master': ('tems',), 'slave': ('tems',),
                     'https': ('nginx',), 'ca-root': ('nginx', 'tems')}
    now = datetime.now(timezone.utc)
    for path, role in paths:
        try:
            if not path.exists():
                continue
            if path.is_symlink() or path.stat().st_size > 1024 * 1024:
                items.append(dict(role=role, status='invalid', reason='INVALID_CERTIFICATE_FILE'))
                continue
            data = path.read_bytes()
        except OSError:
            current_app.logger.exception('Certificate file collection failed: %s', role)
            DPrint(f'Certificate file collection failed: {role}\n{traceback.format_exc()}', level='ERROR')
            items.append(dict(role=role, status='invalid', reason='CERTIFICATE_FILE_UNAVAILABLE'))
            continue
        blocks = re.findall(
            b'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----', data, re.S
        )
        if not blocks:
            items.append(dict(role=role, status='invalid', reason='INVALID_CERTIFICATE'))
            continue
        # fullchain 表示一个身份，不将其中的中间证书计为额外设备。
        if role != 'ca-root':
            blocks = blocks[:1]
        for block in blocks:
            try:
                cert = x509.load_pem_x509_certificate(block)
                # 较旧的 cryptography 仅提供无时区 UTC 属性。
                if hasattr(cert, 'not_valid_before_utc'):
                    start, end = cert.not_valid_before_utc, cert.not_valid_after_utc
                else:
                    start = cert.not_valid_before.replace(tzinfo=timezone.utc)
                    end = cert.not_valid_after.replace(tzinfo=timezone.utc)
                digest = cert.fingerprint(hashes.SHA256()).hex()
                public = cert.public_key().public_bytes(
                    serialization.Encoding.DER,
                    serialization.PublicFormat.SubjectPublicKeyInfo,
                )
                validity = (
                    'not_yet_valid' if now < start
                    else 'expired' if now > end
                    else 'expiring' if (end - now).days <= 30
                    else 'valid'
                )

                # 链验证失败只标记当前证书，不中止后续证书采集。
                verified = True
                try:
                    if role == 'ca-root':
                        pki.validate_roots(data)
                    else:
                        pki.validate_identity(
                            data, None, settings['ca_file'],
                            'sslclient' if role == 'master' else 'sslserver',
                        )
                except (OSError, ValueError, subprocess.SubprocessError):
                    verified = False
                revocation = _certificate_revocation(data, settings, role)
                items.append(dict(
                    id=digest,
                    role=role,
                    subject=cert.subject.rfc4514_string(),
                    issuer=cert.issuer.rfc4514_string(),
                    notBefore=start.isoformat(),
                    notAfter=end.isoformat(),
                    sha256=digest,
                    keyId=hashlib.sha256(public).hexdigest(),
                    signatureAlgorithmOid=cert.signature_algorithm_oid.dotted_string,
                    status=validity if verified and revocation['revocationStatus'] != 'revoked' else 'invalid',
                    validityStatus=validity,
                    chainVerified=verified,
                    privateKeyVerified=None,
                    validityOnly=False,
                    **revocation,
                    applyPending=bool(pending.intersection(role_services[role])),
                ))
            except ValueError:
                items.append(dict(role=role, status='invalid', reason='INVALID_CERTIFICATE'))
    return items


def _certificate_revocation(data, settings, role):
    """Keep list collection available when one CRL cannot be evaluated."""
    if role == 'ca-root':
        return dict(revocationStatus='not_applicable', revocationReason='TRUST_ANCHOR')
    from script import crl_store
    try:
        return crl_store.certificate_status(data, settings['ca_file'], settings['crl_file'])
    except (OSError, ValueError, subprocess.SubprocessError):
        current_app.logger.exception('Certificate CRL check failed role=%s', role)
        return dict(revocationStatus='unavailable', revocationReason='CRL_CHECK_FAILED')


def _https_private_key_check(certificate, directory):
    """用既有 HTTPS 文件私钥签名随机挑战，再用证书公钥验签。"""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import dsa, ec, ed25519, ed448, padding, rsa

    path = directory / 'g3.key'
    if not path.exists():
        return False, 'PRIVATE_KEY_NOT_FOUND'
    metadata = path.stat()
    if path.is_symlink() or not path.is_file() or metadata.st_size > 1024 * 1024:
        return False, 'INVALID_PRIVATE_KEY_FILE'
    # 与现有 HTTPS 检查保持一致：密钥属于当前进程用户，且禁止组/其他用户访问。
    if metadata.st_uid != os.geteuid() or metadata.st_mode & 0o077:
        return False, 'INVALID_PRIVATE_KEY_PERMISSIONS'
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    public = certificate.public_key()
    encoding = serialization.Encoding.DER
    form = serialization.PublicFormat.SubjectPublicKeyInfo
    if key.public_key().public_bytes(encoding, form) != public.public_bytes(encoding, form):
        return False, 'PRIVATE_KEY_MISMATCH'

    challenge = os.urandom(32)
    if isinstance(key, rsa.RSAPrivateKey):
        signature = key.sign(challenge, padding.PKCS1v15(), hashes.SHA256())
        public.verify(signature, challenge, padding.PKCS1v15(), hashes.SHA256())
    elif isinstance(key, ec.EllipticCurvePrivateKey):
        signature = key.sign(challenge, ec.ECDSA(hashes.SHA256()))
        public.verify(signature, challenge, ec.ECDSA(hashes.SHA256()))
    elif isinstance(key, dsa.DSAPrivateKey):
        signature = key.sign(challenge, hashes.SHA256())
        public.verify(signature, challenge, hashes.SHA256())
    elif isinstance(key, (ed25519.Ed25519PrivateKey, ed448.Ed448PrivateKey)):
        public.verify(key.sign(challenge), challenge)
    else:
        return None, 'PRIVATE_KEY_ALGORITHM_UNSUPPORTED'
    return True, 'VERIFIED'


def _certificate_private_key_check(item):
    """供完整证书状态查询使用；结果绑定本次采集的叶证书，不生成或轮换密钥。

    True 表示持钥自检通过；False 表示检查失败；None 表示不适用或无法完成检查。
    Modbus 复用现有 check 命令，其后端沿用 MODBUS_KEY_BACKEND（file/tee）。
    """
    from cryptography import x509
    from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
    from cryptography.hazmat.primitives import hashes
    import config

    role = item['role']
    if role == 'ca-root':
        return None, 'NOT_APPLICABLE'
    if not item.get('sha256'):
        return None, 'INVALID_CERTIFICATE'
    directory = Path(current_app.config.get(
        'HTTPS_CERT_DIR' if role == 'https' else 'MODBUS_CERT_DIR',
        '/etc/ssl/g3' if role == 'https' else '/etc/ems/modbus',
    ))
    path = directory / ('g3.crt' if role == 'https' else role + '.crt')
    try:
        if path.is_symlink() or path.stat().st_size > 1024 * 1024:
            return None, 'CERTIFICATE_CHANGED_DURING_CHECK'
        data = path.read_bytes()
        certificate = x509.load_pem_x509_certificate(data)
        if certificate.fingerprint(hashes.SHA256()).hex() != item['sha256']:
            return None, 'CERTIFICATE_CHANGED_DURING_CHECK'
        if role == 'https':
            result = _https_private_key_check(certificate, directory)
        else:
            # 临时文件仅含公开证书。角色原路径仍用于定位已有私钥；绝不调用 ensure/csr。
            executable = os.environ.get(
                'MODBUS_TEE_IDENTITY', '/home/zlg/app/bin/modbus_tee_identity'
            )
            environment = dict(os.environ, LC_INI_PATH=str(config.INI_PATH))
            with tempfile.TemporaryDirectory(prefix='certificate-self-test-') as temporary:
                snapshot = Path(temporary) / 'identity.crt'
                snapshot.write_bytes(data)
                process = subprocess.run(
                    [executable, '--dir', str(directory), 'check', role, str(snapshot)],
                    env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
                )
            result = ((True, 'VERIFIED') if process.returncode == 0
                      else (False, 'PRIVATE_KEY_SELF_TEST_FAILED'))
        # 防止检查期间替换证书后仍向前端返回旧证书的成功结果。
        if path.is_symlink() or path.read_bytes() != data:
            return None, 'CERTIFICATE_CHANGED_DURING_CHECK'
        return result
    except subprocess.TimeoutExpired:
        return None, 'PRIVATE_KEY_CHECK_TIMEOUT'
    except (OSError, subprocess.SubprocessError):
        return None, 'PRIVATE_KEY_CHECK_UNAVAILABLE'
    except UnsupportedAlgorithm:
        return None, 'PRIVATE_KEY_ALGORITHM_UNSUPPORTED'
    except (ValueError, TypeError, InvalidSignature):
        return False, 'PRIVATE_KEY_SELF_TEST_FAILED'


def _checked_certificate_inventory():
    """采集公开清单并执行持钥自检，供所有返回完整证书条目的接口复用。"""
    items = certificate_inventory()
    for item in items:
        verified, reason = _certificate_private_key_check(item)
        item['privateKeyVerified'] = verified
        item['privateKeyCheckReason'] = reason
        # 保留业务日志和审计的原有通道；仅增加不含密钥/签名的诊断打印。
        DPrint(
            f"Certificate private key self-test: role={item['role']}, "
            f"verified={verified}, reason={reason}",
            level='WARNING' if verified is False else 'INFO',
        )
    return items


@security_bp.route('/api/security/certificates', methods=['GET'])
def certificates():
    """查询证书清单，无入参。

    返回：{ok, data, scope, expiringCount, errorCount}。
    每次请求对设备身份执行持钥自检，独立返回 privateKeyVerified 和原因。
    expiringCount 按有效期统计，errorCount 包含无效、过期和尚未生效的证书。
    """
    try:
        items = _checked_certificate_inventory()
    except (ImportError, OSError, ValueError):
        return _collection_unavailable('CERTIFICATE_COLLECTION_FAILED')
    return jsonify(
        ok=True,
        data=items,
        scope='ca-issued-device-identities',
        expiringCount=sum(
            item.get('validityStatus', item['status']) == 'expiring' for item in items
        ),
        errorCount=sum(
            item['status'] in ('invalid', 'expired', 'not_yet_valid') for item in items
        ),
    )


@security_bp.route('/api/security/certificates/import', methods=['POST'])
def certificate_import():
    """导入已签发的身份证书；请求解析、校验与响应复用证书模块实现。"""
    from routes.route_cert import import_signed_identity
    return import_signed_identity()


@security_bp.route('/api/security/certificates/verify', methods=['POST'])
def certificate_verify():
    """校验证书，请求 JSON：{"role": "master"}。

    成功返回 ok、valid、role、revocationStatus；脚本校验失败返回 422 CERTIFICATE_INVALID。
    role 的合法性由证书模块校验。
    """
    from routes.route_cert import _cert_run_script, _cert_validate_role, CertificateScriptError
    role = _cert_validate_role(_body().get('role'))
    import config
    from script import pki_common as pki
    settings = pki.read_config(config.INI_PATH)
    directory = Path(current_app.config.get('MODBUS_CERT_DIR', '/etc/ems/modbus'))
    try:
        revocation = _certificate_revocation((directory / (role + '.crt')).read_bytes(), settings, role)
    except OSError:
        revocation = dict(revocationStatus='unavailable', revocationReason='CERTIFICATE_UNAVAILABLE')
    try:
        _cert_run_script(['check', '--role', role])
        valid = revocation['revocationStatus'] not in ('revoked', 'unknown')
        return jsonify(ok=valid, valid=valid, role=role, **revocation), 200 if valid else 422
    except CertificateScriptError:
        return jsonify(
            ok=False,
            code='CERTIFICATE_INVALID',
            message='Certificate verification failed',
            valid=False,
            **revocation,
        ), 422


@security_bp.route('/api/security/keys')
def keys():
    """查询公开密钥引用，无入参，不导出私钥或对称密钥。

    返回：{ok, data, rotationTelemetryAvailable, teeStatus, symmetricKeyTelemetryAvailable}。
    TEE 公钥采集失败时保留证书引用，并将 teeStatus 标为 unavailable。
    """
    # 证书公钥引用不代表 TEE 硬件自检成功。
    try:
        inventory = certificate_inventory()
    except (ImportError, OSError, ValueError):
        return _collection_unavailable('KEY_COLLECTION_FAILED')
    items = [
        dict(
            keyId=item['keyId'],
            role=item['role'],
            source='certificate',
            lastRotation=None,
            privateKeyExportable=False,
        )
        for item in inventory if 'keyId' in item
    ]
    tee_status = 'unavailable'
    try:
        from routes.route_tee import _run
        public = _run('public-key')
        modulus, exponent = int(public['n'], 16), int(public['e'], 16)
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
        from cryptography.hazmat.primitives import serialization
        der = RSAPublicNumbers(exponent, modulus).public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        with audit.engine().connect() as conn:
            from sqlalchemy import func
            rotated = conn.execute(
                select(func.max(audit.EVENTS.c.operation_time)).where(
                    audit.EVENTS.c.operation_target == '/api/cert/tee/rotate-rsa',
                    audit.EVENTS.c.result == 1,
                )
            ).scalar()
        items.append(dict(
            keyId=hashlib.sha256(der).hexdigest(),
            source='tee-public-key',
            algorithm='RSA-3072',
            lastRotation=rotated.isoformat() if rotated else None,
            privateKeyExportable=False,
        ))
        tee_status = 'public_key_available'
    except Exception:
        current_app.logger.info('TEE public key telemetry is not available')
        DPrint(f'TEE public key telemetry is not available\n{traceback.format_exc()}', level='INFO')
    return jsonify(
        ok=True,
        data=items,
        rotationTelemetryAvailable=True,
        teeStatus=tee_status,
        symmetricKeyTelemetryAvailable=False,
    )


@security_bp.route('/api/security/peer-status')
def peers():
    """只读查询 logger 发布的活动 Modbus TLS 对端及已认证公开证书。

    快照缺失、过期或进程失效时返回遥测不可用，不将历史证书显示为在线。
    不主动发起连接，不读取本机身份清单，也不修改信任库。
    """
    from utils.modbus_peers import peer_status
    result = peer_status()
    DPrint(
        f"Modbus peer status: available={result['liveAuthenticationTelemetryAvailable']}, "
        f"count={len(result['data'])}, reason={result.get('reason', '-')}",
        level='INFO',
    )
    return jsonify(result)


def _firewalld_zones(output):
    """解析 firewalld 运行时区域清单，保留服务、富规则和其他条件。

    ports 仅表示显式端口规则，不将其当成完整开放端口或监听端口清单。
    """
    zones = []
    zone = None
    field = None
    for line_number, line in enumerate(output.splitlines(), 1):
        if not line.strip():
            continue
        if not line[0].isspace():
            match = re.fullmatch(
                r'([A-Za-z0-9_.-]+)((?:\s+\((?:default|active)'
                r'(?:,\s*(?:default|active))*\))*)', line.strip()
            )
            if not match:
                raise ValueError(f'Invalid firewalld zone header at line {line_number}: {line[:160]!r}')
            flags = re.findall(r'[A-Za-z]+', match.group(2))
            zone = dict(name=match.group(1), active='active' in flags,
                        ports=[], services=[], interfaces=[], sources=[], richRules=[], details={})
            zones.append(zone)
            field = None
            continue
        if zone is None:
            raise ValueError('Missing firewalld zone header')
        # 富规则内部可能含冒号（如 IPv6），须按缩进区分，不能再次按字段解析。
        if field == 'rich rules' and line.lstrip().startswith('rule '):
            zone['richRules'].append(line.strip())
            continue
        key, separator, value = line.strip().partition(':')
        if not separator:
            raise ValueError(
                f'Invalid firewalld zone field at line {line_number}, '
                f"zone={zone['name']}, previous={field!r}: {line[:160]!r}"
            )
        field, value = key, value.strip()
        if key == 'ports':
            for token in value.split():
                port, separator, protocol = token.partition('/')
                if not separator or not re.fullmatch(r'[0-9]+(?:-[0-9]+)?', port) or not protocol:
                    raise ValueError(f'Invalid firewalld port at line {line_number}: {token[:160]!r}')
                zone['ports'].append(dict(port=port, protocol=protocol))
        elif key in ('services', 'interfaces', 'sources'):
            zone[key] = value.split()
        elif key == 'target':
            zone['target'] = value
        elif key == 'rich rules':
            if value:
                zone['richRules'].append(value)
        else:
            # 包括转发、伪装、ICMP、source-ports 等，避免将复杂区域误展示为单纯放行端口。
            zone['details'][key] = value
    if not zones:
        raise ValueError('Empty firewalld zone output')
    return zones


@security_bp.route('/api/security/network-rules')
def network_rules():
    """只读查询网卡、路由和 firewalld 运行时区域规则，无入参。

    rules.zones 返回区域、端口、服务和来源等；ports 不包含服务隐含的端口。
    采集失败时 rules 为 null，并返回 rulesUnavailableReason；不修改防火墙配置。
    """
    addresses = _command(['ip', '-j', 'address', 'show'])
    routes = _command(['ip', '-j', 'route', 'show'])
    # 固定机器可解析的语言，避免进程语言环境将字段翻译后破坏解析。
    output = _command(
        ['firewall-cmd', '--list-all-zones'], env=dict(os.environ, LC_ALL='C')
    )
    rules = None
    reason = None
    if output is None:
        reason = 'FIREWALLD_QUERY_FAILED'
    else:
        try:
            rules = dict(scope='runtime-zones', zones=_firewalld_zones(output))
        except ValueError as exc:
            DPrint(f'Firewalld response parsing failed: {exc}', level='WARNING')
            reason = 'FIREWALLD_RESPONSE_INVALID'
    if reason:
        DPrint(f'Firewalld rules unavailable: {reason}', level='WARNING')
    else:
        DPrint(f"Firewalld rules collected: zones={len(rules['zones'])}", level='INFO')
    return jsonify(
        ok=True,
        interfaces=json.loads(addresses) if addresses else [],
        routes=json.loads(routes) if routes else [],
        rules=rules,
        interfacesAvailable=addresses is not None,
        rulesAvailable=rules is not None,
        rulesUnavailableReason=reason,
        source='iproute2-firewalld',
        writable=False,
    )


@security_bp.route('/api/system/components')
def components():
    """查询运行环境及配置清单中的组件，无入参。

    返回：{ok, components, scope, firmwareInventoryComplete}。
    COMPONENT_MANIFEST 可补充固件组件；当前按其是否提供条目设置完整性标志。
    """
    # 先采集 Python 包与基础运行环境，再追加配置清单中的组件。
    python_packages = sorted(
        [
            dict(name=d.metadata['Name'], version=d.version, type='python-package')
            for d in importlib.metadata.distributions() if d.metadata.get('Name')
        ],
        key=lambda item: item['name'].lower(),
    )
    base = [
        dict(name='Python', version=platform.python_version(), type='runtime'),
        dict(name='Linux', version=platform.release(), type='kernel'),
    ]
    for name, command in (
        ('Node.js', ['node', '--version']),
        ('MySQL client', ['mysql', '--version']),
    ):
        # 未安装的可选程序不作为“已安装但版本未知”的组件。
        if shutil.which(command[0]) is None:
            continue
        version = _command(command)
        base.append(dict(name=name, version=version, available=version is not None))
    manifest = current_app.config.get('COMPONENT_MANIFEST')
    supplied = []
    if manifest:
        path = Path(manifest)
        if path.stat().st_size > 1024 * 1024:
            raise ValueError('COMPONENT_MANIFEST_TOO_LARGE')
        entries = json.loads(path.read_text())
        if not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries):
            raise ValueError('INVALID_COMPONENT_MANIFEST')
        for item in entries:
            supplied.append({
                key: value for key, value in item.items()
                if key in ('name', 'version', 'type', 'supplier', 'license', 'purl', 'sha256')
                and isinstance(value, str)
            })
    return jsonify(
        ok=True,
        components=base + python_packages + supplied,
        scope='backend-runtime-and-configured-manifest',
        firmwareInventoryComplete=bool(supplied),
    )


@security_bp.route('/api/security/config-summary')
def config_summary():
    """查询安全配置摘要，无入参，不包含口令或私钥。

    返回用户启用状态、角色能力、口令和会话策略，以及证书、审计、网络和组件清单。
    generatedAt 使用 UTC 时间，timePolicy 描述平台时区与同步策略。
    """
    from utils.auth import is_developer_account_disabled
    from sqlalchemy import text
    import config

    try:
        with audit.engine().connect() as conn:
            users = conn.execute(text(f'SELECT username,permission FROM `{config.PERM_TABLE}`')).mappings().all()
            identities = []
            for user in users:
                state = store.read_account_state(conn, user['username'])
                identities.append(dict(
                    username=user['username'],
                    permission=user['permission'],
                    uid=state['uid'] if state else None,
                    enabled=(state['enabled'] if state else True)
                    and not is_developer_account_disabled(user['username']),
                ))
        return jsonify(
            ok=True,
            schemaVersion=1,
            generatedAt=datetime.now(timezone.utc).isoformat(),
            users=identities,
            abilities=ABILITIES,
            passwordPolicy=store.PASSWORD_POLICY,
            session=dict(
                absoluteSeconds=int(current_app.permanent_session_lifetime.total_seconds()),
                idleSeconds=current_app.config['AUTH_IDLE_SECONDS'],
            ),
            certificates=_checked_certificate_inventory(),
            audit=audit.status(),
            networkRules=network_rules().get_json(),
            components=components().get_json(),
            timePolicy=dict(
                timezone=str(datetime.now().astimezone().tzinfo),
                syncPolicy='platform-managed',
            ),
        )

    except (ImportError, OSError, ValueError):
        return _collection_unavailable('CONFIG_SUMMARY_COLLECTION_FAILED')


@security_bp.route('/api/security/status')
def security_status():
    """聚合安全状态，无入参，返回 {ok, checks, maintenance, alerts, sampledAt}。

    CPU、内存、审计、证书和会话容量分别采集，单项异常记录为 COLLECTION_FAILED。
    资源使用率达到 90%、审计异常、证书异常及配置完整性异常会生成告警。
    """
    from utils.auth import login_capacity
    from utils.system_usage import cpu_usage
    from utils.ini_integrity import verify_ini_checksum

    # 独立采集各项状态，保留现有的单项异常隔离边界。
    checks = {}
    for name, provider in (
        ('cpu', cpu_usage),
        ('memory', memory_usage),
        ('audit', audit.status),
        ('certificates', _checked_certificate_inventory),
        ('loginSessions', login_capacity),
    ):
        try:
            checks[name] = dict(available=True, data=provider())
        except Exception:
            current_app.logger.exception('Security status collection failed: %s', name)
            DPrint(f'Security status collection failed: {name}\n{traceback.format_exc()}', level='ERROR')
            checks[name] = dict(available=False, reason='COLLECTION_FAILED')
    try:
        usage = shutil.disk_usage(current_app.config.get('SECURITY_DISK_PATH', '/'))
        checks['disk'] = dict(
            available=True,
            data=dict(
                total=usage.total,
                used=usage.used,
                free=usage.free,
                usagePercent=round(usage.used * 100 / usage.total, 2),
            ),
        )
    except OSError:
        checks['disk'] = dict(available=False)
    valid, detail = verify_ini_checksum()
    checks['configurationIntegrity'] = dict(
        available=not detail.startswith('Integrity check unavailable'), valid=valid
    )
    ntp = _command(['timedatectl', 'show', '--property=NTPSynchronized', '--value'])
    checks['timeSync'] = dict(
        available=ntp in ('yes', 'no'),
        synchronized=ntp == 'yes' if ntp in ('yes', 'no') else None,
    )
    provider = current_app.extensions.get('web_connection_capacity')
    checks['webConnections'] = dict(
        available=provider is not None, data=provider() if provider else None
    )
    checks['tee'] = dict(available=False, reason='HARDWARE_TELEMETRY_NOT_PROVIDED')
    with audit.engine().connect() as conn:
        maintenance_state = store.maintenance_state(conn)

    # 根据已采集状态生成告警，不额外触发采集或修改设备状态。
    alerts = []
    for name in ('cpu', 'memory', 'disk'):
        value = checks[name]
        if value.get('available'):
            percent = value['data'].get('usedPercent', value['data'].get('usagePercent', 0))
            if percent >= 90:
                alerts.append(dict(code='RESOURCE_USAGE_HIGH', source=name, usagePercent=percent))
    log_status = checks['audit']
    if audit.write_failed():
        alerts.append(dict(code='AUDIT_WRITE_FAILED', source='audit'))
    if log_status.get('available'):
        capacity_code = audit.capacity_alert(log_status['data'])
        if capacity_code:
            alerts.append(dict(code=capacity_code, source='audit'))
    cert_status = checks['certificates']
    if cert_status.get('available') and any(item['status'] != 'valid' for item in cert_status['data']):
        alerts.append(dict(code='CERTIFICATE_ATTENTION_REQUIRED', source='certificates'))
    if checks['configurationIntegrity']['available'] and not valid:
        alerts.append(dict(code='CONFIGURATION_INTEGRITY_FAILED', source='configurationIntegrity'))
    return jsonify(
        ok=True,
        checks=checks,
        maintenance=maintenance_state,
        alerts=alerts,
        sampledAt=datetime.now(timezone.utc).isoformat(),
    )


@security_bp.route('/api/security/backups', methods=['GET', 'POST'])
def backups():
    """查询备份列表或创建备份。

    GET 返回 {ok: true, data: [...]}；POST 调用备份模块创建文件，返回 201 及备份元数据。
    创建成功后将备份 id 写入当前请求的审计目标。
    """
    if request.method == 'POST':
        error = _require_write_csrf()
        if error:
            return error
    try:
        from utils import security_backup as backup
        if request.method == 'GET':
            return jsonify(ok=True, data=backup.list_backups())
        result = backup.create_backup()
    except (ImportError, OSError):
        return _collection_unavailable('BACKUP_STORAGE_UNAVAILABLE')
    except ValueError as exc:
        if str(exc) in (
            'INVALID_SECURITY_DIRECTORY', 'SYMLINK_SECURITY_DIRECTORY',
            'SECURITY_DIRECTORY_REQUIRES_0700', 'DEVICE_ID_UNAVAILABLE',
        ):
            return _collection_unavailable('BACKUP_STORAGE_UNAVAILABLE')
        raise
    g.audit_target = result['id']
    return jsonify(ok=True, **result), 201


@security_bp.route('/api/security/backups/<identifier>/download')
def backup_download(identifier):
    """下载指定备份，identifier 为路径中的备份 id。

    先校验文件再写下载审计；文件无效返回 404，审计失败返回 503。
    成功以附件返回 .lcb 文件，并在 X-Backup-SHA256 中提供摘要。
    """
    from utils.security_backup import _path, MAX_BACKUP_BYTES

    path = _path(identifier)
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_BACKUP_BYTES + 64:
        return jsonify(ok=False, code='BACKUP_NOT_FOUND'), 404
    if not audit.record_event('backup.download', identifier, True):
        return jsonify(ok=False, code='AUDIT_UNAVAILABLE'), 503
    response = send_file(
        path,
        as_attachment=True,
        download_name='backup-' + identifier + '.lcb',
        mimetype='application/octet-stream',
    )
    response.headers['X-Backup-SHA256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    return response


@security_bp.route('/api/security/backups/<identifier>/validate', methods=['POST'])
def backup_validate(identifier):
    """校验指定备份，请求 JSON：{"sha256": "<备份摘要>"}。

    校验由 read_backup 完成，直接返回其校验结果，并记录备份 id 作为审计目标。
    """
    error = _require_write_csrf()
    if error:
        return error
    data = _body()
    if not re.fullmatch(r'[0-9a-f]{32}', identifier):
        raise ValueError('INVALID_BACKUP_ID')
    try:
        from utils.security_files import private_directory
        path = private_directory('backups') / (identifier + '.lcb')
        if not path.exists():
            return jsonify(ok=False, code='BACKUP_NOT_FOUND'), 404
        digest = data.get('sha256')
        if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', digest):
            raise ValueError('VALIDATED_DIGEST_REQUIRED')
        from utils.security_backup import read_backup
        _, result = read_backup(identifier, digest)
    except FileNotFoundError:
        return jsonify(ok=False, code='BACKUP_NOT_FOUND'), 404
    except (ImportError, OSError):
        return _collection_unavailable('BACKUP_STORAGE_UNAVAILABLE')
    except ValueError as exc:
        if str(exc) == 'BACKUP_DIGEST_MISMATCH':
            raise ValueError('VALIDATED_DIGEST_REQUIRED') from None
        if str(exc) in (
            'INVALID_SECURITY_DIRECTORY', 'SYMLINK_SECURITY_DIRECTORY',
            'SECURITY_DIRECTORY_REQUIRES_0700',
        ):
            return _collection_unavailable('BACKUP_STORAGE_UNAVAILABLE')
        raise
    g.audit_target = result['id']
    return jsonify(result)


def _maintenance_confirmation(action):
    """解析危险操作的预览或执行请求，返回 (请求体, 是否执行)。

    只有 dry_run 严格为 false 才进入执行校验：执行开关、确认文本、维护模式、口令。
    其他情况均为预览；不在本函数内执行恢复或清理操作。
    """
    data = _body()
    if data.get('dry_run', True) is not False:
        return data, False
    if not current_app.config.get('SECURITY_ALLOW_DESTRUCTIVE', False):
        raise ValueError('DESTRUCTIVE_OPERATIONS_DISABLED')
    if data.get('confirm') != action:
        raise ValueError('CONFIRMATION_REQUIRED')
    with audit.engine().connect() as conn:
        if not store.maintenance_state(conn)['active']:
            raise ValueError('MAINTENANCE_REQUIRED')
    # 在管理员身份和 CSRF 校验之外，再次校验当前用户口令。
    from routes.route_permission import _credentials_check
    _, error = _credentials_check(g.current_user['username'], data.get('password'))
    if error:
        raise ValueError('REAUTHENTICATION_FAILED')
    return data, True


@security_bp.route('/api/security/backups/<identifier>/restore', methods=['POST'])
def backup_restore(identifier):
    """预览或执行指定备份的恢复。

    请求 JSON：sha256；执行时还需 dry_run=false、confirm=RESTORE_BACKUP、password。
    预览返回 validation 及会话撤销、重启、执行开关提示。
    执行时先核对摘要并写授权审计，再调用恢复模块。
    """
    from utils.security_backup import read_backup, restore_backup
    data, execute = _maintenance_confirmation('RESTORE_BACKUP')
    _, checked = read_backup(identifier, data.get('sha256'))
    if not execute:
        return jsonify(
            ok=True,
            dry_run=True,
            validation=checked,
            sessions_will_be_revoked=True,
            restart_required=True,
            executionEnabled=current_app.config.get('SECURITY_ALLOW_DESTRUCTIVE', False),
        )
    if data.get('sha256') != checked['sha256']:
        raise ValueError('VALIDATED_DIGEST_REQUIRED')
    if not audit.record_event('backup.restore.authorize', identifier, True, 'Execution authorized'):
        return jsonify(ok=False, code='AUDIT_UNAVAILABLE'), 503
    return jsonify(restore_backup(identifier, checked['sha256']))


@security_bp.route('/api/security/factory-reset', methods=['POST'])
def factory_reset():
    """预览或恢复已配置的出厂基线。

    请求 JSON：{"dry_run": true}；执行时需 dry_run=false、confirm=FACTORY_RESET、password。
    基线由 SECURITY_FACTORY_BACKUP_ID / SHA256 指定，未配置返回 409。
    校验基线账号口令格式后，预览返回 validation；执行恢复时强制修改口令。
    """
    error = _require_write_csrf()
    if error:
        return error
    data, execute = _maintenance_confirmation('FACTORY_RESET')
    identifier = current_app.config.get('SECURITY_FACTORY_BACKUP_ID')
    digest = current_app.config.get('SECURITY_FACTORY_BACKUP_SHA256')
    if not identifier or not digest:
        return jsonify(
            ok=False,
            code='FACTORY_BASELINE_NOT_CONFIGURED',
            message='Provision a trusted device-specific factory baseline first',
        ), 409
    try:
        from utils.security_backup import read_backup, restore_backup
        baseline, checked = read_backup(identifier, digest)
    except FileNotFoundError:
        return jsonify(ok=False, code='FACTORY_BASELINE_NOT_FOUND'), 409
    except (ImportError, OSError):
        return _collection_unavailable('FACTORY_BASELINE_UNAVAILABLE')
    if any(not user['password'].startswith('pbkdf2_sha256$') for user in baseline['users']):
        return jsonify(ok=False, code='FACTORY_BASELINE_REQUIRES_STRONG_CREDENTIALS'), 409
    if not execute:
        return jsonify(
            ok=True,
            dry_run=True,
            validation=checked,
            scope='application-security',
            restart_required=True,
        )
    if not audit.record_event('factory.reset.authorize', identifier, True, 'Execution authorized'):
        return jsonify(ok=False, code='AUDIT_UNAVAILABLE'), 503
    return jsonify(restore_backup(identifier, digest, force_password_change=True))


@security_bp.route('/api/security/decommission', methods=['POST'])
def decommission():
    """预览或执行应用身份退役，不包含平台安全擦除。

    请求 JSON：{"dry_run": true}。
    执行时需 dry_run=false、confirm=DECOMMISSION_APPLICATION、password，
    并显式指定 scope=application-identities。

    返回清理计划；执行时先写授权审计，再清空身份相关表、断开会话并删除私有文件。
    文件清理失败通过 failedScopes 返回，且响应状态为 500。
    """
    from utils.auth import LOGIN_SESSIONS, disconnect_revoked
    from utils.security_files import private_directory
    from sqlalchemy import MetaData, Table
    import config

    data, execute = _maintenance_confirmation('DECOMMISSION_APPLICATION')
    plan = dict(
        scope='application-identities',
        tables=[
            config.PERM_TABLE,
            store.ACCOUNT_STATE.name,
            store.SESSION_STATE.name,
            store.SESSION_LOCKS.name,
            LOGIN_SESSIONS.name,
            store.ATTEMPTS.name,
            store.RATE_LIMITS.name,
            store.SETTINGS.name,
        ],
        privateFiles=['credentials', 'backups'],
        excluded=[
            'platform-and-TEE-keys',
            'device-configuration',
            'certificates',
            'business-database',
            'audit-and-application-logs',
        ],
        completeDeviceErasure=False,
    )
    if not execute:
        return jsonify(
            ok=True,
            dry_run=True,
            plan=plan,
            executionEnabled=current_app.config.get('SECURITY_ALLOW_DESTRUCTIVE', False),
        )
    if data.get('scope') != 'application-identities':
        raise ValueError('EXPLICIT_SCOPE_REQUIRED')
    targets = {
        name: list(private_directory(name).iterdir()) for name in ('credentials', 'backups')
    }
    if not audit.record_event('decommission.authorize', 'application-identities', True, 'Execution authorized'):
        return jsonify(ok=False, code='AUDIT_UNAVAILABLE'), 503
    # 数据库清理在同一事务内完成，提交后再断开会话和清理私有文件。
    with audit.engine().begin() as conn:
        store.lock_security(conn)
        users = Table(config.PERM_TABLE, MetaData(), autoload_with=conn)
        ids = conn.execute(select(LOGIN_SESSIONS.c.sid)).scalars().all()
        for table in (
            users,
            store.ACCOUNT_STATE,
            store.SESSION_STATE,
            store.SESSION_LOCKS,
            LOGIN_SESSIONS,
            store.ATTEMPTS,
            store.RATE_LIMITS,
            store.SETTINGS,
        ):
            conn.execute(table.delete())
    disconnect_revoked(ids)
    failures = []
    for name, paths in targets.items():
        for path in paths:
            if path.is_file() and not path.is_symlink():
                try:
                    path.unlink()
                except OSError:
                    failures.append(name)
            elif path.exists() or path.is_symlink():
                failures.append(name)
    return jsonify(
        ok=not failures,
        plan=plan,
        failedScopes=sorted(set(failures)),
        reprovisionRequired=True,
    ), (200 if not failures else 500)
