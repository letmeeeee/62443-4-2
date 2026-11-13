"""TEE 管理接口：持久密钥、公钥、CMAC 及 RSA 签名验签。

通过本机 crypto_ta_client 调用 TEE；HTTP 消息及结果使用 Base64 编码。
接口沿用证书模块的 status/message/data 响应结构。
"""

import base64
import binascii
import json
import os
import subprocess
import traceback
from functools import wraps
from pathlib import Path

import config
from flask import current_app, g, jsonify, request

from routes.route_g3 import g3_bp
from utils.utils import DPrint


TEE_CLIENT = Path(os.environ.get(
    "CRYPTO_TA_CLIENT", "/home/zlg/app/bin/crypto_ta_client"
))
TEE_TIMEOUT = 15
TEE_MAX_MESSAGE_SIZE = 1024 * 1024


class TeeClientError(Exception):
    """本机客户端或 TA 调用失败，异常信息不包含请求中的密钥或消息材料。"""


def tee_admin_required(function):
    """校验当前请求的登录身份及 usermanage 管理权限。"""
    @wraps(function)
    def wrapper(*args, **kwargs):
        user = getattr(g, "current_user", None)
        if not isinstance(user, dict):
            return _error("authentication required", 401)
        allowed = config.PERMISSION_TABLE.get("usermanage", [])
        if user.get("permission") not in allowed:
            return _error("administrator permission required", 403)
        return function(*args, **kwargs)
    return wrapper


def _success(message, data=None):
    """构造成功响应；仅在 data 非 None 时包含 data 字段。"""
    result = {"status": config.STATE_DONE, "message": message}
    if data is not None:
        result["data"] = data
    return jsonify(result), 200


def _error(message, status_code=400):
    """构造证书模块格式的错误响应，并保留调用方指定的 HTTP 状态码。"""
    return jsonify({
        "status": config.STATE_ERROR,
        "message": str(message)
    }), status_code


def _json_body():
    """读取 JSON 对象，空请求或非对象请求体抛出参数异常。"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("JSON request body is required")
    return data


def _decode(value, field, expected_size=None):
    """严格解码 Base64，检查指定字节长度及 1 MiB 消息上限。"""
    if not isinstance(value, str):
        raise ValueError("%s is required" % field)
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("%s must be valid base64" % field)
    if expected_size is not None and len(decoded) != expected_size:
        raise ValueError("%s must decode to %d bytes" % (field, expected_size))
    if len(decoded) > TEE_MAX_MESSAGE_SIZE:
        raise ValueError("%s is too large" % field)
    return decoded


def _run(operation, payload=b""):
    """调用固定命令集合中的 TEE 操作，向客户端标准输入传入原始字节。

    校验客户端文件、执行超时、退出码和 JSON 响应；失败统一抛出 TeeClientError。
    """
    if operation not in {
        "gen-aes", "gen-rsa", "rotate-rsa", "cmac", "sign",
        "verify-cmac", "verify-rsa", "public-key"
    }:
        raise TeeClientError("unsupported TEE operation")
    if not TEE_CLIENT.is_file():
        raise TeeClientError("TEE client is not installed")
    # 不拼接 shell 命令，消息材料仅通过标准输入传给客户端。
    try:
        result = subprocess.run(
            [str(TEE_CLIENT), operation],
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=TEE_TIMEOUT,
            check=False
        )
    except subprocess.TimeoutExpired:
        raise TeeClientError("TEE operation timed out")
    except OSError:
        raise TeeClientError("failed to execute TEE client")
    if result.returncode != 0:
        diagnostic = result.stderr.decode("utf-8", "replace").strip()
        current_app.logger.error(
            "[CERT][TEE] operation=%s failed: %s", operation, diagnostic
        )
        DPrint(f'[CERT][TEE] operation={operation} failed: {diagnostic}', level='ERROR')
        raise TeeClientError("TEE operation failed")
    # 客户端必须返回 JSON 对象，且 ok 严格为 true。
    try:
        response = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise TeeClientError("invalid TEE client response")
    if not isinstance(response, dict) or response.get("ok") is not True:
        raise TeeClientError("invalid TEE client response")
    return response


def _hex_to_base64(value, expected_size=None):
    """将客户端十六进制输出转为 HTTP Base64 字段，并校验可选字节长度。"""
    if not isinstance(value, str):
        raise TeeClientError("invalid TEE client response")
    try:
        raw = bytes.fromhex(value)
    except ValueError:
        raise TeeClientError("invalid TEE client response")
    if expected_size is not None and len(raw) != expected_size:
        raise TeeClientError("invalid TEE client response")
    return base64.b64encode(raw).decode("ascii")


@g3_bp.route("/api/cert/tee/keys", methods=["POST"])
@tee_admin_required
def tee_generate_keys():
    """创建或复用 TEE 持久密钥，不轮换现有密钥。

    请求示例：
      POST /api/cert/tee/keys
      {"type": "all"}

    type 可选，默认 all，可取 aes、rsa、all。
    返回 data：{type, created_or_reused: true, rotated: false}。
    参数错误返回 400，TEE 调用失败返回 503。
    """
    try:
        key_type = str(_json_body().get("type", "all")).strip().lower()
        operations = {
            "aes": ("gen-aes",),
            "rsa": ("gen-rsa",),
            "all": ("gen-aes", "gen-rsa")
        }.get(key_type)
        if operations is None:
            raise ValueError("type must be aes, rsa or all")
        for operation in operations:
            _run(operation)
        current_app.logger.info(
            "[CERT][TEE] persistent key ensured type=%s", key_type
        )
        DPrint(f'[CERT][TEE] persistent key ensured type={key_type}', level='INFO')
        return _success("TEE key is ready", {
            "type": key_type,
            "created_or_reused": True,
            "rotated": False
        })
    except ValueError as exc:
        return _error(exc, 400)
    except TeeClientError as exc:
        return _error(exc, 503)


@g3_bp.route("/api/cert/tee/rotate-rsa", methods=["POST"])
@tee_admin_required
def tee_rotate_rsa():
    """显式确认后轮换 TEE 持久 RSA 密钥对。

    请求示例：
      POST /api/cert/tee/rotate-rsa
      {"confirm": "ROTATE_RSA_KEY"}

    返回 data：type、rotated、certificate_renewal_required、restart_required。
    确认文本错误返回 400；TEE 调用失败返回 503。
    """
    try:
        if _json_body().get("confirm") != "ROTATE_RSA_KEY":
            raise ValueError("confirm must be ROTATE_RSA_KEY")
        _run("rotate-rsa")
        current_app.logger.info(
            "[CERT][TEE] RSA key rotated operator=%s",
            g.current_user["username"]
        )
        DPrint(f'[CERT][TEE] RSA key rotated operator={g.current_user["username"]}', level='INFO')
        return _success("TEE RSA key rotated", {
            "type": "rsa",
            "rotated": True,
            "certificate_renewal_required": True,
            "restart_required": True
        })
    except ValueError as exc:
        return _error(exc, 400)
    except TeeClientError as exc:
        return _error(exc, 503)


@g3_bp.route("/api/cert/tee/public-key", methods=["GET"])
@tee_admin_required
def tee_get_public_key():
    """查询 TEE RSA-3072 公钥，无入参。

    请求示例：
      GET /api/cert/tee/public-key

    返回 data：{algorithm, format, modulus, exponent}。
    模数为 384 字节；模数与指数均以无符号大端字节的 Base64 表示。
    未安装客户端时返回 status=3、message=TEE_UNAVAILABLE、data=null。
    客户端已安装但执行失败或输出无效时返回 503。
    """
    if not TEE_CLIENT.is_file():
        return jsonify(status=config.STATE_DONE, message='TEE_UNAVAILABLE', data=None), 200
    try:
        result = _run("public-key")
        exponent = _hex_to_base64(result.get("e"))
        if not base64.b64decode(exponent):
            raise TeeClientError("invalid TEE client response")
        return _success("TEE RSA public key retrieved", {
            "algorithm": "RSA-3072",
            "format": "unsigned-big-endian",
            "modulus": _hex_to_base64(result.get("n"), 384),
            "exponent": exponent
        })
    except TeeClientError as exc:
        current_app.logger.warning('[CERT][TEE] public key unavailable: %s', exc)
        DPrint(f'[CERT][TEE] public key unavailable: {exc}\n{traceback.format_exc()}', level='WARNING')
        return jsonify(
            status=config.STATE_ERROR,
            ok=False,
            code='TEE_UNAVAILABLE',
            message='TEE public key is unavailable',
        ), 503


def _calculate(operation, field, size, algorithm):
    """共用计算流程：解码原始消息、调用 TEE、校验并编码结果。

    field 指定响应字段名，size 指定结果字节长度，algorithm 用于响应算法标识。
    """
    try:
        message = _decode(_json_body().get("message"), "message")
        result = _run(operation, message)
        return _success("TEE operation completed", {
            "algorithm": algorithm,
            field: _hex_to_base64(result.get("value"), size)
        })
    except ValueError as exc:
        return _error(exc, 400)
    except TeeClientError as exc:
        return _error(exc, 503)


@g3_bp.route("/api/cert/tee/cmac", methods=["POST"])
@tee_admin_required
def tee_cmac():
    """计算 AES-128-CMAC，请求 JSON：{"message": "<Base64 原始消息>"}。

    POST /api/cert/tee/cmac，返回 data：{algorithm, mac}。
    mac 为 16 字节 CMAC 的 Base64 编码。
    """
    return _calculate("cmac", "mac", 16, "AES-128-CMAC")


@g3_bp.route("/api/cert/tee/sign", methods=["POST"])
@tee_admin_required
def tee_sign():
    """计算 RSA-3072-PSS-SHA256 签名，请求 JSON：{"message": "<Base64 原始消息>"}。

    POST /api/cert/tee/sign，返回 data：{algorithm, signature}。
    消息摘要由 TA 内部计算，签名为 384 字节的 Base64 编码。
    """
    return _calculate("sign", "signature", 384, "RSA-3072-PSS-SHA256")


def _verify(operation, proof_field, proof_size, algorithm):
    """共用验证流程：解码消息及证明值，按“证明值 + 原始消息”调用客户端。

    客户端 valid 必须为布尔值；不匹配返回成功响应中的 valid=false。
    """
    try:
        data = _json_body()
        message = _decode(data.get("message"), "message")
        proof = _decode(data.get(proof_field), proof_field, proof_size)
        result = _run(operation, proof + message)
        if not isinstance(result.get("valid"), bool):
            raise TeeClientError("invalid TEE client response")
        return _success("TEE verification completed", {
            "algorithm": algorithm,
            "valid": result["valid"]
        })
    except ValueError as exc:
        return _error(exc, 400)
    except TeeClientError as exc:
        return _error(exc, 503)


@g3_bp.route("/api/cert/tee/verify-cmac", methods=["POST"])
@tee_admin_required
def tee_verify_cmac():
    """验证 CMAC，请求 JSON：{"message": "<Base64>", "mac": "<Base64>"}。

    POST /api/cert/tee/verify-cmac，mac 解码后必须为 16 字节。
    返回 data：{algorithm, valid}；参数错误返回 400，TEE 调用失败返回 503。
    """
    return _verify("verify-cmac", "mac", 16, "AES-128-CMAC")


@g3_bp.route("/api/cert/tee/verify-signature", methods=["POST"])
@tee_admin_required
def tee_verify_signature():
    """验证 RSA 签名，请求 JSON：{"message": "<Base64>", "signature": "<Base64>"}。

    POST /api/cert/tee/verify-signature，signature 解码后必须为 384 字节。
    返回 data：{algorithm, valid}；验证不匹配时 valid=false，HTTP 仍为 200。
    """
    return _verify(
        "verify-rsa", "signature", 384, "RSA-3072-PSS-SHA256"
    )
