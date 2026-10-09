import base64
import importlib
import json
import sys
import types
from pathlib import Path
from unittest.mock import Mock

import pytest
from flask import Blueprint, Flask, g


@pytest.fixture
def tee_module(monkeypatch, tmp_path):
    config = types.ModuleType("config")
    config.STATE_DONE = 3
    config.STATE_ERROR = -1
    config.PERMISSION_TABLE = {"usermanage": [4]}
    route_g3 = types.ModuleType("routes.route_g3")
    route_g3.g3_bp = Blueprint("g3-test-tee", __name__)
    monkeypatch.setitem(sys.modules, "config", config)
    monkeypatch.setitem(sys.modules, "routes.route_g3", route_g3)
    sys.modules.pop("routes.route_tee", None)
    module = importlib.import_module("routes.route_tee")
    client = tmp_path / "crypto_ta_client"
    client.write_bytes(b"test")
    module.TEE_CLIENT = client
    return module


@pytest.fixture
def app(tee_module):
    application = Flask(__name__)
    application.register_blueprint(tee_module.g3_bp)

    @application.before_request
    def authenticated_admin():
        g.current_user = {"username": "admin", "permission": 4}

    return application


def completed(payload):
    return types.SimpleNamespace(
        returncode=0, stdout=json.dumps(payload).encode(), stderr=b""
    )


def test_generate_all_invokes_fixed_commands(app, tee_module, monkeypatch):
    run = Mock(side_effect=[completed({"ok": True}), completed({"ok": True})])
    monkeypatch.setattr(tee_module.subprocess, "run", run)

    response = app.test_client().post("/api/cert/tee/keys", json={"type": "all"})

    assert response.status_code == 200
    assert [call.args[0][1] for call in run.call_args_list] == ["gen-aes", "gen-rsa"]
    assert response.get_json()["data"]["rotated"] is False


def test_rotate_rsa_requires_confirmation_and_invokes_explicit_command(
        app, tee_module, monkeypatch):
    run = Mock(return_value=completed({"ok": True}))
    monkeypatch.setattr(tee_module.subprocess, "run", run)

    denied = app.test_client().post("/api/cert/tee/rotate-rsa", json={})
    assert denied.status_code == 400
    run.assert_not_called()

    response = app.test_client().post("/api/cert/tee/rotate-rsa", json={
        "confirm": "ROTATE_RSA_KEY"
    })
    assert response.status_code == 200
    assert run.call_args.args[0][1] == "rotate-rsa"
    assert response.get_json()["data"]["certificate_renewal_required"] is True


def test_sign_passes_original_message_and_checks_signature_size(
        app, tee_module, monkeypatch):
    message = b"original message, not a precomputed digest"
    run = Mock(return_value=completed({"ok": True, "value": "ab" * 384}))
    monkeypatch.setattr(tee_module.subprocess, "run", run)

    response = app.test_client().post("/api/cert/tee/sign", json={
        "message": base64.b64encode(message).decode()
    })

    assert response.status_code == 200
    assert run.call_args.kwargs["input"] == message
    assert len(base64.b64decode(response.get_json()["data"]["signature"])) == 384


def test_verify_mismatch_is_successful_request_with_false_result(
        app, tee_module, monkeypatch):
    run = Mock(return_value=completed({"ok": True, "valid": False}))
    monkeypatch.setattr(tee_module.subprocess, "run", run)
    signature = bytes(384)
    message = b"payload"

    response = app.test_client().post("/api/cert/tee/verify-signature", json={
        "message": base64.b64encode(message).decode(),
        "signature": base64.b64encode(signature).decode()
    })

    assert response.status_code == 200
    assert response.get_json()["data"]["valid"] is False
    assert run.call_args.kwargs["input"] == signature + message


@pytest.mark.parametrize("field,value", [
    ("message", "not base64!"),
    ("mac", base64.b64encode(bytes(15)).decode())
])
def test_verify_cmac_rejects_invalid_input(app, tee_module, monkeypatch, field, value):
    body = {
        "message": base64.b64encode(b"payload").decode(),
        "mac": base64.b64encode(bytes(16)).decode()
    }
    body[field] = value
    run = Mock()
    monkeypatch.setattr(tee_module.subprocess, "run", run)

    response = app.test_client().post("/api/cert/tee/verify-cmac", json=body)

    assert response.status_code == 400
    run.assert_not_called()


def test_non_admin_is_rejected(app, tee_module, monkeypatch):
    @app.before_request
    def downgrade_user():
        g.current_user = {"username": "viewer", "permission": 1}

    run = Mock()
    monkeypatch.setattr(tee_module.subprocess, "run", run)

    response = app.test_client().get("/api/cert/tee/public-key")

    assert response.status_code == 403
    run.assert_not_called()


def test_public_key_preserves_returned_lengths(app, tee_module, monkeypatch):
    modulus = bytes(range(256)) + bytes(range(128))
    exponent = b"\x01\x00\x01"
    monkeypatch.setattr(tee_module.subprocess, "run", Mock(return_value=completed({
        "ok": True, "n": modulus.hex(), "e": exponent.hex()
    })))

    response = app.test_client().get("/api/cert/tee/public-key")

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert base64.b64decode(data["modulus"]) == modulus
    assert base64.b64decode(data["exponent"]) == exponent
