import io
from unittest.mock import patch

from flask import Flask, g

from routes import route_g3


def test_upload_upgrade_file_accepts_legacy_fields(tmp_path):
    app = Flask(__name__)
    app.register_blueprint(route_g3.g3_bp)

    @app.before_request
    def authenticated_user():
        # This route unit test supplies the identity normally loaded by init_auth.
        g.current_user = {"username": "admin", "permission": 4}

    route_g3.UPLOAD_DIR = tmp_path / "upload"
    route_g3.UPGRADE_PACKAGE_DIR = route_g3.UPLOAD_DIR / "packages"

    with app.test_client() as client:
        with patch.object(route_g3, "_require_upgrade_permission", return_value=None), \
             patch.object(route_g3, "_record_upgrade_operation"), \
             patch.object(route_g3, "verify_upgrade_package", return_value="inner.tar.gz"), \
             patch.object(route_g3, "read_upgrade_package_info", return_value={
                 "firmware": "LC",
                 "version": "1.0.0",
                 "scan_path": "content",
             }), \
             patch.object(route_g3, "secure_filename", side_effect=lambda value: value):
            resp = client.post(
                "/api/upgrade/file",
                data={
                    "operatorName": "admin",
                    "taskName": "job-1",
                    "deviceId": "1",
                    "firmwareCategory": "lc",
                    "upgradeEnable": "0",
                    "firmwareFile": (io.BytesIO(b"dummy package"), "pkg.tar.gz"),
                },
                content_type="multipart/form-data",
            )

    assert resp.status_code == 200
    assert resp.get_json()["package"]["firmware"] == "LC"
