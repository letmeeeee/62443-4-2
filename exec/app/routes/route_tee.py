"""Administrative HTTP facade for the project OP-TEE crypto TA ABI."""

import base64
import binascii
import json
import os
import subprocess
from functools import wraps
from pathlib import Path

import config
from flask import current_app, g, jsonify, request

from routes.route_g3 import g3_bp


TEE_CLIENT = Path(os.environ.get(
    "CRYPTO_TA_CLIENT", "/home/zlg/app/bin/crypto_ta_client"
))
TEE_TIMEOUT = 15
TEE_MAX_MESSAGE_SIZE = 1024 * 1024


class TeeClientError(Exception):
    """The local client or TA failed without exposing request material."""


def tee_admin_required(function):
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
    result = {"status": config.STATE_DONE, "message": message}
    if data is not None:
        result["data"] = data
    return jsonify(result), 200


def _error(message, status_code=400):
    return jsonify({
        "status": config.STATE_ERROR,
        "message": str(message)
    }), status_code


def _json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("JSON request body is required")
    return data


def _decode(value, field, expected_size=None):
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
    if operation not in {
        "gen-aes", "gen-rsa", "rotate-rsa", "cmac", "sign",
        "verify-cmac", "verify-rsa", "public-key"
    }:
        raise TeeClientError("unsupported TEE operation")
    if not TEE_CLIENT.is_file():
        raise TeeClientError("TEE client is not installed")
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
        raise TeeClientError("TEE operation failed")
    try:
        response = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise TeeClientError("invalid TEE client response")
    if not isinstance(response, dict) or response.get("ok") is not True:
        raise TeeClientError("invalid TEE client response")
    return response


def _hex_to_base64(value, expected_size=None):
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
    """Idempotently create or reuse persistent keys; never rotates them."""
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
    """Replace the persistent RSA keypair after explicit confirmation."""
    try:
        if _json_body().get("confirm") != "ROTATE_RSA_KEY":
            raise ValueError("confirm must be ROTATE_RSA_KEY")
        _run("rotate-rsa")
        current_app.logger.info(
            "[CERT][TEE] RSA key rotated operator=%s",
            g.current_user["username"]
        )
        return _success("TEE RSA key rotated", {
            "type": "rsa", "rotated": True,
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
        return _error(exc, 503)


def _calculate(operation, field, size, algorithm):
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
    return _calculate("cmac", "mac", 16, "AES-128-CMAC")


@g3_bp.route("/api/cert/tee/sign", methods=["POST"])
@tee_admin_required
def tee_sign():
    return _calculate("sign", "signature", 384, "RSA-3072-PSS-SHA256")


def _verify(operation, proof_field, proof_size, algorithm):
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
    return _verify("verify-cmac", "mac", 16, "AES-128-CMAC")


@g3_bp.route("/api/cert/tee/verify-signature", methods=["POST"])
@tee_admin_required
def tee_verify_signature():
    return _verify(
        "verify-rsa", "signature", 384, "RSA-3072-PSS-SHA256"
    )
