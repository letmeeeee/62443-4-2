
# -*- coding: utf-8 -*-

"""
Modbus TLS 证书管理 API

功能：
    1. 查询本机证书
    2. 生成本机证书
    3. 更新本机证书
    4. 检查证书有效性
    5. 查询可信主机证书
    6. 上传并导入可信主机证书
    7. 删除可信主机证书
    8. 导出本机公开证书

运行环境：
    Python 3.8+
    Flask
    OpenSSL 1.1.1+

依赖：
    scripts/modbus_certs.py

说明：
    本模块不直接操作证书私钥内容。
    证书生成、校验和信任管理均调用现有证书管理脚本。
    不自动重启 tems 服务。
"""

import os
import re
import sys
import ipaddress
import shutil
import tempfile
import subprocess

from pathlib import Path
from functools import wraps
import config as config

from flask import (
    request,
    jsonify,
    send_file,
    current_app,
    g
)


# ============================================================
# 1. 基础配置
# ============================================================
from routes.route_g3 import g3_bp

# g3_bp = Blueprint("g3_cert", __name__)


# ------------------------------------------------------------
# 证书管理脚本路径
# ------------------------------------------------------------

CERT_SCRIPT = Path(
    "/home/zlg/app/scripts/modbus_certs.py"
)


# ------------------------------------------------------------
# 证书存放目录
# ------------------------------------------------------------

CERT_DIR = Path(
    "/etc/ems/modbus"
)


# ------------------------------------------------------------
# 脚本执行超时时间
# ------------------------------------------------------------

CERT_TIMEOUT = 60


# ------------------------------------------------------------
# 上传证书最大大小：1 MB
# ------------------------------------------------------------

MAX_CERT_SIZE = 1024 * 1024


# ------------------------------------------------------------
# 本机证书角色
# ------------------------------------------------------------

CERT_ROLES = (
    "master",
    "slave"
)


# ------------------------------------------------------------
# 本机公开证书文件
# ------------------------------------------------------------

CERT_FILES = {
    "master": "master.crt",
    "slave": "slave.crt"
}

# ------------------------------------------------------------
# SHA-256 证书指纹
#
# 支持：
#   AABBCC...
#   AA:BB:CC:...
# ------------------------------------------------------------

SHA256_PATTERN = re.compile(
    r"^(?:"
    r"[0-9a-fA-F]{64}"
    r"|"
    r"(?:[0-9a-fA-F]{2}:){31}"
    r"[0-9a-fA-F]{2}"
    r")$"
)


# ============================================================
# 2. 接口权限校验
# ============================================================

def cert_admin_required(func):
    """
    证书管理接口管理员权限校验。

    采用全局认证钩子写入的 g.current_user。

    正式集成时，应替换为项目现有的认证、
    角色检查及接口权限中间件。

    所有证书管理接口均需要认证。
    """

    @wraps(func)
    def wrapper(*args, **kwargs):

        # 请与现有后端的用户登录态字段保持一致。
        #
        # 这里不接受前端自行提交的 role 参数作为
        # 管理员身份判断依据。

        user = getattr(g, "current_user", None)

        if not isinstance(user, dict):

            return jsonify({
                "status": config.STATE_ERROR,
                "message": "authentication required"
            }), 401

        if user.get("permission") not in config.PERMISSION_TABLE.get("usermanage", []):

            return jsonify({
                "status": config.STATE_ERROR,
                "message": "administrator permission required"
            }), 403

        return func(*args, **kwargs)

    return wrapper


# ============================================================
# 3. 通用响应
# ============================================================

def _cert_success(message, data=None):
    """证书操作成功响应。"""

    result = {
        "status": config.STATE_DONE,
        "message": message
    }

    if data is not None:
        result["data"] = data

    return jsonify(result), 200


def _cert_error(message, http_code=400):
    """证书操作失败响应。"""

    return jsonify({
        "status": config.STATE_ERROR,
        "message": str(message)
    }), http_code


# ============================================================
# 4. 请求参数解析
# ============================================================

def _cert_get_json():
    """
    获取 JSON 请求参数。
    """

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        raise ValueError(
            "JSON request body is required"
        )

    return data


def _cert_validate_role(role):
    """
    校验证书角色。

    master：本机作为 Modbus 主机
    slave ：本机作为 Modbus 从机
    """

    if not isinstance(role, str):
        raise ValueError(
            "role is required"
        )

    role = role.strip().lower()

    if role not in CERT_ROLES:
        raise ValueError(
            "role must be master or slave"
        )

    return role


def _cert_validate_name(name):
    """
    校验证书名称。

    避免通过证书名称传入异常字符。
    """

    if not isinstance(name, str):
        raise ValueError(
            "name is required"
        )

    name = name.strip()

    if not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}",
        name
    ):
        raise ValueError(
            "invalid certificate name"
        )

    return name


def _cert_validate_days(days):
    """
    校验证书有效期。

    允许范围：1～3650 天。
    """

    if isinstance(days, bool):
        raise ValueError(
            "days must be an integer"
        )

    try:
        days = int(days)

    except (TypeError, ValueError):

        raise ValueError(
            "days must be an integer"
        )

    if not 1 <= days <= 3650:

        raise ValueError(
            "days must be between 1 and 3650"
        )

    return days


def _cert_validate_fingerprint(value):
    """
    校验完整 SHA-256 证书指纹。

    返回：
        64 位大写十六进制字符串。
    """

    if not isinstance(value, str):
        raise ValueError(
            "fingerprint is required"
        )

    value = value.strip()

    if not SHA256_PATTERN.fullmatch(value):

        raise ValueError(
            "invalid SHA-256 fingerprint"
        )

    return value.replace(
        ":", ""
    ).upper()


def _cert_validate_ip(ip):
    """
    校验 IP 地址。
    """

    if not isinstance(ip, str):
        raise ValueError(
            "invalid IP address"
        )

    ip = ip.strip()

    try:
        ipaddress.ip_address(ip)

    except ValueError:

        raise ValueError(
            "invalid IP address"
        )

    return ip


def _cert_validate_dns(dns):
    """
    校验 DNS 名称。
    """

    if not isinstance(dns, str):
        raise ValueError(
            "invalid DNS name"
        )

    dns = dns.strip()

    if len(dns) > 253 or not dns:

        raise ValueError(
            "invalid DNS name"
        )

    labels = dns.split(".")

    for label in labels:

        if not re.fullmatch(
            r"[A-Za-z0-9]"
            r"(?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?",
            label
        ):

            raise ValueError(
                "invalid DNS name"
            )

    return dns


def _cert_normalize_list(value):
    """
    将单个字符串或列表统一转换为列表。
    """

    if value is None:
        return []

    if isinstance(value, str):
        return [value]

    if isinstance(value, list):
        return value

    raise ValueError(
        "parameter must be a string or list"
    )


def _cert_build_identity_args(data):
    """
    构建生成证书和更新证书时的命令参数。

    请求示例：
        {
            "role": "slave",
            "name": "slave-001",
            "days": 365,
            "ip": ["192.168.2.136"],
            "dns": []
        }
    """

    role = _cert_validate_role(
        data.get("role")
    )

    name = _cert_validate_name(
        data.get("name")
    )

    days = _cert_validate_days(
        data.get("days", 365)
    )

    command = [
        "--role", role,
        "--name", name,
        "--days", str(days)
    ]

    # --------------------------------------------------------
    # IP SAN
    # --------------------------------------------------------

    ip_values = _cert_normalize_list(
        data.get("ip")
    )

    for ip in ip_values:

        ip = _cert_validate_ip(ip)

        command.extend([
            "--ip",
            ip
        ])

    # --------------------------------------------------------
    # DNS SAN
    # --------------------------------------------------------

    dns_values = _cert_normalize_list(
        data.get("dns")
    )

    for dns in dns_values:

        dns = _cert_validate_dns(dns)

        command.extend([
            "--dns",
            dns
        ])

    return role, name, days, command


# ============================================================
# 5. 证书管理脚本执行
# ============================================================

class CertificateScriptError(Exception):
    """证书管理脚本执行失败。"""


def _cert_run_script(command):
    """
    调用现有 modbus_certs.py。

    例如：
        _cert_run_script([
            "check",
            "--role",
            "master"
        ])

    实际执行：
        python3 modbus_certs.py
            --dir /etc/ems/modbus
            check
            --role master

    返回：
        脚本标准输出。

    注意：
        不使用 shell=True。
        前端不能直接指定任意系统命令。
    """

    if not CERT_SCRIPT.is_file():

        raise CertificateScriptError(
            "certificate script not found"
        )

    if not CERT_DIR.is_dir():

        raise CertificateScriptError(
            "certificate directory not found"
        )

    args = [
        sys.executable,
        str(CERT_SCRIPT),
        "--dir",
        str(CERT_DIR)
    ]

    args.extend(command)

    current_app.logger.info(
        "[CERT] execute operation=%s",
        command[0]
    )

    try:

        result = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CERT_TIMEOUT,
            check=False
        )

    except subprocess.TimeoutExpired:

        current_app.logger.error(
            "[CERT] operation timed out: %s",
            command[0]
        )

        raise CertificateScriptError(
            "certificate operation timed out"
        )

    except OSError:

        current_app.logger.exception(
            "[CERT] failed to start script"
        )

        raise CertificateScriptError(
            "failed to execute certificate script"
        )

    output = result.stdout.strip()

    error = result.stderr.strip()

    if result.returncode != 0:

        current_app.logger.error(
            "[CERT] operation=%s returncode=%s error=%s",
            command[0],
            result.returncode,
            error or output
        )

        raise CertificateScriptError(
            "certificate operation failed"
        )

    return output


# ============================================================
# 6. 查询本机证书信息
# ============================================================

@g3_bp.route(
    "/api/cert/identity",
    methods=["GET"]
)
@cert_admin_required
def get_certificate_identity():
    """
    查询本机证书信息。

    请求：
        GET /api/cert/identity?role=master

    返回：
        证书主体、签发者、有效期及 SHA-256 指纹。
    """

    role = (
        request.args.get("role") or ""
    ).strip()

    try:

        role = _cert_validate_role(role)

        output = _cert_run_script([
            "show",
            "--role",
            role
        ])

        return _cert_success(
            "certificate information retrieved",
            {
                "role": role,
                "certificate": output
            }
        )

    except ValueError as exc:

        return _cert_error(
            str(exc),
            400
        )

    except CertificateScriptError as exc:

        current_app.logger.error(
            "[CERT] get identity failed: %s",
            exc
        )

        return _cert_error(
            "failed to retrieve certificate information",
            500
        )


# ============================================================
# 7. 生成本机证书
# ============================================================

@g3_bp.route(
    "/api/cert/generate",
    methods=["POST"]
)
@cert_admin_required
def generate_certificate():
    """
    生成本机 Modbus TLS 证书。

    请求：
        POST /api/cert/generate

    JSON：
        {
            "role": "slave",
            "name": "slave-001",
            "days": 365,
            "ip": ["192.168.2.136"],
            "dns": []
        }

    说明：
        generate 不覆盖已有身份文件。
    """

    try:

        data = _cert_get_json()

        role, name, days, command = (
            _cert_build_identity_args(data)
        )

        # ----------------------------------------------------
        # 执行证书生成
        # ----------------------------------------------------

        output = _cert_run_script(
            ["generate"] + command
        )

        current_app.logger.info(
            "[CERT] certificate generated role=%s name=%s",
            role,
            name
        )

        return _cert_success(
            "certificate generated successfully",
            {
                "role": role,
                "name": name,
                "days": days,
                "output": output,
                "restart_required": True
            }
        )

    except ValueError as exc:

        return _cert_error(
            str(exc),
            400
        )

    except CertificateScriptError as exc:

        current_app.logger.error(
            "[CERT] generate failed: %s",
            exc
        )

        return _cert_error(
            "certificate generation failed",
            500
        )


# ============================================================
# 8. 更新本机证书
# ============================================================

@g3_bp.route(
    "/api/cert/renew",
    methods=["POST"]
)
@cert_admin_required
def renew_certificate():
    """
    更新本机证书。

    请求：
        POST /api/cert/renew

    JSON：
        {
            "role": "master",
            "name": "master-001",
            "days": 365,
            "ip": [],
            "dns": []
        }

    说明：
        1. 脚本备份旧公开证书。
        2. 更新证书复用对应角色的 TA 私钥；首次迁移会创建 TA 密钥。
        3. 不自动重启 tems。
        4. 应在维护流程已停止相关 tems 进程后调用。
        5. IP/DNS SAN 需要重新传入。
    """

    try:

        data = _cert_get_json()

        role, name, days, command = (
            _cert_build_identity_args(data)
        )

        # ----------------------------------------------------
        # 更新证书
        # ----------------------------------------------------

        output = _cert_run_script(
            ["renew"] + command
        )

        current_app.logger.info(
            "[CERT] certificate renewed role=%s name=%s",
            role,
            name
        )

        return _cert_success(
            "certificate renewed successfully",
            {
                "role": role,
                "name": name,
                "days": days,
                "output": output,
                "restart_required": True
            }
        )

    except ValueError as exc:

        return _cert_error(
            str(exc),
            400
        )

    except CertificateScriptError as exc:

        current_app.logger.error(
            "[CERT] renew failed: %s",
            exc
        )

        return _cert_error(
            "certificate renewal failed",
            500
        )


# ============================================================
# 9. 检查本机证书
# ============================================================

@g3_bp.route(
    "/api/cert/check",
    methods=["GET"]
)
@cert_admin_required
def check_certificate():
    """
    检查本机证书。

    请求：
        GET /api/cert/check?role=master

    检查内容由原有证书脚本提供：
        1. 自签名
        2. 有效期
        3. 证书角色用途
        4. 证书与私钥匹配
        5. 私钥权限
    """

    role = (
        request.args.get("role") or ""
    ).strip()

    try:

        role = _cert_validate_role(role)

        output = _cert_run_script([
            "check",
            "--role",
            role
        ])

        return _cert_success(
            "certificate check passed",
            {
                "role": role,
                "valid": True,
                "output": output
            }
        )

    except ValueError as exc:

        return _cert_error(
            str(exc),
            400
        )

    except CertificateScriptError as exc:

        current_app.logger.error(
            "[CERT] check failed role=%s error=%s",
            role,
            exc
        )

        return jsonify({
            "status": config.STATE_ERROR,
            "message": "certificate check failed",
            "data": {
                "role": role,
                "valid": False
            }
        }), 422


# ============================================================
# 10. 查询可信主机证书列表
# ============================================================

@g3_bp.route(
    "/api/cert/trust-list",
    methods=["GET"]
)
@cert_admin_required
def get_certificate_trust_list():
    """
    查询当前从机信任的主机证书。

    请求：
        GET /api/cert/trust-list

    对应文件：
        /etc/ems/modbus/master-ca.crt
    """

    try:

        output = _cert_run_script([
            "trust-list"
        ])

        return _cert_success(
            "trusted certificates retrieved",
            {
                "output": output
            }
        )

    except CertificateScriptError as exc:

        current_app.logger.error(
            "[CERT] trust-list failed: %s",
            exc
        )

        return _cert_error(
            "failed to retrieve trusted certificates",
            500
        )


# ============================================================
# 11. 上传并导入可信主机证书
# ============================================================

@g3_bp.route(
    "/api/cert/trust-add",
    methods=["POST"]
)
@cert_admin_required
def add_certificate_trust():
    """
    上传并导入可信主机证书。

    请求：
        POST /api/cert/trust-add

    Content-Type:
        multipart/form-data

    参数：
        file:
            待导入的主机公开证书。

        fingerprint:
            可选，完整 SHA-256 指纹。

    说明：
        仅允许上传 PEM 格式的公开证书。
        实际证书有效性由 modbus_certs.py 校验。
    """

    temp_dir = None

    try:

        # ----------------------------------------------------
        # 1. 获取上传文件
        # ----------------------------------------------------

        upload_file = request.files.get("file")

        if upload_file is None:

            return _cert_error(
                "certificate file is required",
                400
            )

        filename = upload_file.filename or ""

        if not filename.lower().endswith(".crt"):

            return _cert_error(
                "only .crt files are allowed",
                400
            )

        # ----------------------------------------------------
        # 2. 获取可选 SHA-256 指纹
        # ----------------------------------------------------

        fingerprint = (
            request.form.get("fingerprint") or ""
        ).strip()

        if fingerprint:

            fingerprint = (
                _cert_validate_fingerprint(
                    fingerprint
                )
            )

        # ----------------------------------------------------
        # 3. 读取上传证书
        # ----------------------------------------------------

        cert_data = upload_file.stream.read(
            MAX_CERT_SIZE + 1
        )

        if not cert_data:

            return _cert_error(
                "certificate file is empty",
                400
            )

        if len(cert_data) > MAX_CERT_SIZE:

            return _cert_error(
                "certificate file is too large",
                413
            )

        # ----------------------------------------------------
        # 4. PEM 格式预检查
        # ----------------------------------------------------

        if not cert_data.lstrip().startswith(
            b"-----BEGIN CERTIFICATE-----"
        ):

            return _cert_error(
                "invalid PEM certificate format",
                400
            )

        # ----------------------------------------------------
        # 5. 创建临时目录
        # ----------------------------------------------------

        temp_dir = Path(
            tempfile.mkdtemp(
                prefix="modbus-cert-"
            )
        )

        os.chmod(
            temp_dir,
            0o700
        )

        temp_cert = temp_dir / "upload.crt"

        with open(temp_cert, "xb") as file:

            file.write(cert_data)

        os.chmod(
            temp_cert,
            0o600
        )

        # ----------------------------------------------------
        # 6. 构建证书导入命令
        # ----------------------------------------------------

        command = [
            "trust-add",
            "--cert",
            str(temp_cert)
        ]

        if fingerprint:

            command.extend([
                "--fingerprint",
                fingerprint
            ])

        # ----------------------------------------------------
        # 7. 导入可信主机证书
        # ----------------------------------------------------

        output = _cert_run_script(
            command
        )

        current_app.logger.info(
            "[CERT] trusted certificate imported"
        )

        return _cert_success(
            "trusted certificate imported successfully",
            {
                "output": output,
                "restart_required": True
            }
        )

    except ValueError as exc:

        return _cert_error(
            str(exc),
            400
        )

    except CertificateScriptError as exc:

        current_app.logger.error(
            "[CERT] trust-add failed: %s",
            exc
        )

        return _cert_error(
            "failed to import trusted certificate",
            500
        )

    except OSError:

        current_app.logger.exception(
            "[CERT] upload file operation failed"
        )

        return _cert_error(
            "certificate upload failed",
            500
        )

    finally:

        # ----------------------------------------------------
        # 8. 清理临时证书
        # ----------------------------------------------------

        if temp_dir is not None:

            shutil.rmtree(
                temp_dir,
                ignore_errors=True
            )


# ============================================================
# 12. 删除可信主机证书
# ============================================================

@g3_bp.route(
    "/api/cert/trust-remove",
    methods=["POST"]
)
@cert_admin_required
def remove_certificate_trust():
    """
    根据 SHA-256 指纹删除可信主机证书。

    请求：
        POST /api/cert/trust-remove

    JSON：
        {
            "fingerprint": "完整SHA256指纹"
        }

    说明：
        不能通过设备名称或文件名删除。
        删除最后一个信任证书可能导致从机无法启动
        TLS 监听，应先导入替代证书。
    """

    try:

        data = _cert_get_json()

        fingerprint = (
            _cert_validate_fingerprint(
                data.get("fingerprint")
            )
        )

        # ----------------------------------------------------
        # 删除信任证书
        # ----------------------------------------------------

        output = _cert_run_script([
            "trust-remove",
            "--fingerprint",
            fingerprint
        ])

        current_app.logger.info(
            "[CERT] trusted certificate removed fingerprint=%s",
            fingerprint
        )

        return _cert_success(
            "trusted certificate removed successfully",
            {
                "fingerprint": fingerprint,
                "output": output,
                "restart_required": True
            }
        )

    except ValueError as exc:

        return _cert_error(
            str(exc),
            400
        )

    except CertificateScriptError as exc:

        current_app.logger.error(
            "[CERT] trust-remove failed: %s",
            exc
        )

        return _cert_error(
            "failed to remove trusted certificate",
            500
        )


# ============================================================
# 13. 导出本机公开证书
# ============================================================

@g3_bp.route(
    "/api/cert/export",
    methods=["GET"]
)
@cert_admin_required
def export_certificate():
    """
    导出本机公开证书。

    请求：
        GET /api/cert/export?role=master

    返回：
        master.crt

    安全说明：
        只能导出 master.crt / slave.crt。
        不允许通过前端参数指定任意文件路径。
        不提供私钥下载接口。
    """

    role = (
        request.args.get("role") or ""
    ).strip()

    try:

        role = _cert_validate_role(role)

        # ----------------------------------------------------
        # 1. 通过白名单获取证书路径
        # ----------------------------------------------------

        cert_file = CERT_FILES[role]

        cert_path = CERT_DIR / cert_file

        if not cert_path.is_file():

            return _cert_error(
                "certificate not found",
                404
            )

        # ----------------------------------------------------
        # 2. 检查证书有效性
        # ----------------------------------------------------

        _cert_run_script([
            "check",
            "--role",
            role
        ])

        # ----------------------------------------------------
        # 3. 导出公开证书
        # ----------------------------------------------------

        response = send_file(
            str(cert_path),
            mimetype="application/x-pem-file",
            as_attachment=True,
            download_name=cert_file
        )

        response.headers[
            "Cache-Control"
        ] = "no-store"

        return response

    except ValueError as exc:

        return _cert_error(
            str(exc),
            400
        )

    except CertificateScriptError as exc:

        current_app.logger.error(
            "[CERT] export failed: %s",
            exc
        )

        return _cert_error(
            "certificate export failed",
            500
        )

    except OSError:

        current_app.logger.exception(
            "[CERT] certificate file read failed"
        )

        return _cert_error(
            "failed to read certificate file",
            500
        )


# ============================================================
# 14. 独立测试启动
# ============================================================

if __name__ == "__main__":

    from flask import Flask

    app = Flask(__name__)

    app.register_blueprint(
        g3_bp
    )

    # 仅注册路由，独立运行时不提供测试管理员身份。
    # 正式使用请接入现有 Flask 应用的会话认证机制。
    #
    # 不要在生产环境中使用硬编码 Secret Key
    # 或为了测试而绕过管理员认证。

    app.run(
        host="127.0.0.1",
        port=8001,
        debug=False
    )
