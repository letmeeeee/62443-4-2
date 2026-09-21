"""INI and HTTPS reconciliation tests using real OpenSSL and isolated service stubs."""
import importlib.util
import os
from pathlib import Path
import subprocess

import pytest

SOURCE = Path(__file__).parents[1] / "script"
spec = importlib.util.spec_from_file_location("https_config", SOURCE / "https_config.py")
https_config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(https_config)


def test_read_multiple_ips(tmp_path):
    config = tmp_path / "device.ini"
    config.write_text("\ufeff[other]\npassword=100%secret\n[HTTPS]\ndevice_ips=192.168.3.136, 192.168.2.136 192.168.3.136\n")
    assert https_config.read_device_ips(config) == ["192.168.2.136", "192.168.3.136"]


@pytest.mark.parametrize("content", ["[other]\nx=1", "[HTTPS]\ndevice_ips=",
    "[HTTPS]\ndevice_ips=999.1.1.1", "[HTTPS]\ndevice_ips=127.0.0.1;evil",
    "[HTTPS]\ndevice_ips=0.0.0.0", "[HTTPS]\ndevice_ips=224.0.0.1",
    "[HTTPS]\ndevice_ips=::1"])
def test_invalid_ini_rejected(tmp_path, content):
    config = tmp_path / "device.ini"
    config.write_text(content)
    with pytest.raises(ValueError):
        https_config.read_device_ips(config)


@pytest.fixture
def deployment(tmp_path):
    """Map system paths to a temp device; stub only privileged service operations."""
    root = tmp_path / "device"
    script_dir = root / "home/zlg/app/script"
    script_dir.mkdir(parents=True)
    (script_dir.parent / "main.py").touch()
    for directory in ("etc/nginx/conf.d", "etc/systemd/system", "usr/local", "bin"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    script = (SOURCE / "enable_https.sh").read_text()
    for prefix in ("/home/zlg", "/etc/", "/usr/local/", "/var/log/"):
        script = script.replace(prefix, str(root) + prefix)
    script = "\n".join(
        'export PATH="' + str(root / "bin") + ':$PATH"' if line.startswith("export PATH=") else line
        for line in script.splitlines()) + "\n"
    (script_dir / "enable_https.sh").write_text(script)
    (script_dir / "https_config.py").write_text((SOURCE / "https_config.py").read_text())
    stubs = {
        "id": "echo 0",
        "nginx": 'echo nginx "$@" >> "$CALL_LOG"\n[ "${FAIL_NGINX:-0}" != 1 ]',
        "systemctl": 'echo systemctl "$@" >> "$CALL_LOG"\nexit 0',
        "ss": "exit 0",
    }
    for name, body in stubs.items():
        path = root / "bin" / name
        path.write_text("#!/bin/bash\n" + body + "\n")
        path.chmod(0o755)
    config = root / "home/zlg/lc_data_set.ini"
    config.write_text("[HTTPS]\ndevice_ips=192.168.3.136,192.168.2.136\n")
    env = dict(os.environ, CALL_LOG=str(root / "calls"))

    def run(mode="--prepare", **overrides):
        return subprocess.run(["bash", str(script_dir / "enable_https.sh"), mode],
                              env=dict(env, **overrides), capture_output=True, text=True, timeout=30)
    return root, config, run


def test_prepare_idempotence_and_changed_san(deployment):
    root, config, run = deployment
    result = run()
    assert result.returncode == 0, result.stderr + result.stdout
    cert = root / "etc/ssl/g3/g3.crt"
    key = root / "etc/ssl/g3/g3.key"
    original = cert.read_bytes()
    assert key.stat().st_mode & 0o777 == 0o600
    output = subprocess.check_output(["openssl", "x509", "-in", str(cert), "-noout", "-ext", "subjectAltName"], text=True)
    assert "IP Address:192.168.2.136" in output
    assert "IP Address:192.168.3.136" in output
    assert run().returncode == 0
    assert cert.read_bytes() == original
    assert "systemctl" not in (root / "calls").read_text()
    nginx = (root / "etc/nginx/conf.d/g3_https.conf").read_text()
    assert "location = /api/upgrade/process" in nginx
    assert "proxy_pass http://127.0.0.1:9000;" in nginx
    assert "proxy_pass http://127.0.0.1:8000;" in nginx
    config.write_text("[HTTPS]\ndevice_ips=192.168.3.136\n")
    assert run().returncode == 0
    assert cert.read_bytes() != original
    output = subprocess.check_output(["openssl", "x509", "-in", str(cert), "-noout", "-ext", "subjectAltName"], text=True)
    assert "192.168.2.136" not in output


def test_invalid_nginx_restores_files(deployment):
    root, config, run = deployment
    assert run().returncode == 0
    paths = [root / p for p in ("etc/ssl/g3/g3.crt", "etc/ssl/g3/g3.key", "etc/nginx/conf.d/g3_https.conf")]
    originals = [path.read_bytes() for path in paths]
    config.write_text("[HTTPS]\ndevice_ips=192.168.4.136\n")
    assert run(FAIL_NGINX="1").returncode != 0
    assert [path.read_bytes() for path in paths] == originals
    config.write_text("[HTTPS]\ndevice_ips=invalid\n")
    assert run().returncode != 0
    assert [path.read_bytes() for path in paths] == originals


def test_install_and_apply(deployment):
    root, config, run = deployment
    result = run("--install-service")
    assert result.returncode == 0, result.stderr + result.stdout
    assert (root / "usr/local/lib/g3-https/https_config.py").is_file()
    unit = (root / "etc/systemd/system/g3-https.service").read_text()
    assert "Before=nginx.service" in unit
    assert "--prepare" in unit
    assert "RemainAfterExit=yes" in unit
    dropin = (root / "etc/systemd/system/nginx.service.d/g3-https.conf").read_text()
    assert "Requires=g3-https.service" in dropin
    calls = root / "calls"
    calls.write_text("")
    assert run("--apply").returncode == 0
    assert "reload nginx" not in calls.read_text()
    config.write_text("[HTTPS]\ndevice_ips=192.168.4.136\n")
    assert run("--apply").returncode == 0
    assert "reload nginx" in calls.read_text()


@pytest.mark.parametrize("days,cn", [(1, "logger"), (398, "192.168.2.136")])
def test_expiry_or_old_subject_certificate_renewed(deployment, days, cn):
    root, _, run = deployment
    assert run().returncode == 0
    cert = root / "etc/ssl/g3/g3.crt"
    key = root / "etc/ssl/g3/g3.key"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                    "-keyout", str(key), "-out", str(cert), "-days", str(days),
                    "-subj", "/CN=" + cn,
                    "-addext", "subjectAltName=IP:192.168.2.136,IP:192.168.3.136"],
                   check=True, capture_output=True)
    original = cert.read_bytes()
    assert run().returncode == 0
    assert cert.read_bytes() != original
    identity = subprocess.check_output(["openssl", "x509", "-in", str(cert), "-noout",
                                        "-subject", "-issuer", "-nameopt", "RFC2253"], text=True)
    assert "subject=CN=logger" in identity
    assert "issuer=CN=logger" in identity
    assert subprocess.run(["openssl", "x509", "-in", str(cert), "-noout", "-checkend", "2592000"],
                          capture_output=True).returncode == 0


def test_first_setup_failure_leaves_no_partial_config(deployment):
    root, _, run = deployment
    assert run(FAIL_NGINX="1").returncode != 0
    for name in ("etc/ssl/g3/g3.crt", "etc/ssl/g3/g3.key", "etc/nginx/conf.d/g3_https.conf"):
        assert not (root / name).exists()
