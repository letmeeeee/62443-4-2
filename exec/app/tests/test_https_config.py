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
    for helper in ("https_config.py", "https_certificates.py", "pki_common.py"):
        (script_dir / helper).write_text((SOURCE / helper).read_text())
    stubs = {
        "id": "echo 0",
        "nginx": 'echo nginx "$@" >> "$CALL_LOG"\n[ "${FAIL_NGINX:-0}" != 1 ]',
        "systemctl": 'echo systemctl "$@" >> "$CALL_LOG"\nif [ "$1" = reload ] && [ "${FAIL_RELOAD:-0}" = 1 ]; then exit 1; fi\nexit 0',
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


def provision(deployment,days=365):
    from pki_test_helpers import make_ca,sign_csr
    root,config,run=deployment
    ca=make_ca(root/'offline-ca')
    ca_file=root/'etc/ems/pki/ca-roots.crt'
    ca_file.parent.mkdir(parents=True)
    ca_file.write_bytes(ca['root'].read_bytes())
    with config.open('a') as stream:
        stream.write('\n[TLS]\nca_file='+str(ca_file)+'\n')
    script=root/'home/zlg/app/script/https_certificates.py'
    directory=root/'etc/ssl/g3'
    def tool(*args,success=True):
        result=subprocess.run(['python3',str(script),'--config',str(config),'--dir',str(directory),*map(str,args)],
                              capture_output=True,text=True,timeout=60)
        assert (result.returncode==0)==success,result.stderr
        return result
    tool('csr')
    leaf=sign_csr(directory/'g3.csr',root/'issued.crt',ca,ips=['192.168.2.136','192.168.3.136'],days=days)
    tool('identity-import','--cert',leaf,'--chain',ca['intermediate'])
    return root,config,run,tool,ca


def test_prepare_preserves_ca_identity_and_private_key(deployment):
    root,config,run,tool,ca=provision(deployment)
    certificate=root/'etc/ssl/g3/g3.crt'
    key=root/'etc/ssl/g3/g3.key'
    original,private=certificate.read_bytes(),key.read_bytes()
    assert run().returncode==0
    assert run().returncode==0
    assert certificate.read_bytes()==original and key.read_bytes()==private
    assert original.count(b'BEGIN CERTIFICATE')==2
    assert key.stat().st_mode&0o777==0o600
    nginx=(root/'etc/nginx/conf.d/g3_https.conf').read_text()
    assert 'location = /api/upgrade/process' in nginx
    assert 'systemctl' not in (root/'calls').read_text()
    config.write_text(config.read_text().replace('192.168.3.136,192.168.2.136','192.168.4.136'))
    assert run().returncode!=0
    assert certificate.read_bytes()==original and key.read_bytes()==private
    request=root/'etc/ssl/g3/g3.csr'
    leaf=sign_csr_local(request,root/'reissued.crt',ca,['192.168.4.136'])
    tool('identity-import','--cert',leaf,'--chain',ca['intermediate'])
    assert run().returncode==0
    assert key.read_bytes()==private


def sign_csr_local(request,path,ca,ips):
    from pki_test_helpers import sign_csr
    return sign_csr(request,path,ca,ips=ips)


def test_invalid_nginx_restores_configuration_and_preserves_identity(deployment):
    root,config,run,_,_=provision(deployment)
    assert run().returncode==0
    paths=[root/p for p in ('etc/ssl/g3/g3.crt','etc/ssl/g3/g3.key','etc/nginx/conf.d/g3_https.conf')]
    originals=[path.read_bytes() for path in paths]
    (root/'etc/nginx/conf.d/g3_https.conf').write_text('previous config')
    expected=paths[-1].read_bytes()
    assert run(FAIL_NGINX='1').returncode!=0
    assert paths[-1].read_bytes()==expected
    assert [path.read_bytes() for path in paths[:2]]==originals[:2]


def test_install_and_apply_ca_certificate(deployment):
    root,_,run,tool,ca=provision(deployment)
    result=run('--install-service')
    assert result.returncode==0,result.stdout+result.stderr
    for helper in ('https_config.py','https_certificates.py','pki_common.py'):
        assert (root/'usr/local/lib/g3-https'/helper).is_file()
    calls=root/'calls';calls.write_text('')
    assert run('--apply').returncode==0
    assert 'reload nginx' not in calls.read_text()
    tool('identity-import','--cert',root/'issued.crt','--chain',ca['intermediate'])
    assert run('--apply').returncode==0
    assert 'reload nginx' in calls.read_text()


def test_near_expiry_only_creates_csr_and_never_replaces_identity(deployment):
    import json
    root,_,run,_,_=provision(deployment,days=1)
    directory=root/'etc/ssl/g3'
    original=(directory/'g3.crt').read_bytes()
    key=(directory/'g3.key').read_bytes()
    assert run().returncode==0
    assert (directory/'g3.crt').read_bytes()==original
    assert (directory/'g3.key').read_bytes()==key
    assert json.loads((directory/'renewal-status.json').read_text())['renewal_required']


def test_missing_ca_identity_creates_csr_but_no_leaf_or_nginx_configuration(deployment):
    root,_,run=deployment
    result=run()
    assert result.returncode!=0
    assert (root/'etc/ssl/g3/g3.csr').is_file()
    assert not (root/'etc/ssl/g3/g3.crt').exists()
    assert not (root/'etc/nginx/conf.d/g3_https.conf').exists()


def test_certificate_digest_recovers_missing_reload_marker_and_failed_reload_retries(deployment):
    root,_,run,tool,ca=provision(deployment)
    assert run('--apply').returncode==0
    from pki_test_helpers import sign_csr
    leaf=sign_csr(root/'etc/ssl/g3/g3.csr',root/'new-identity.crt',ca,
                  ips=['192.168.2.136','192.168.3.136'])
    tool('identity-import','--cert',leaf,'--chain',ca['intermediate'])
    marker=root/'etc/ssl/g3/.reload-required'
    marker.unlink()
    calls=root/'calls';calls.write_text('')
    assert run('--apply').returncode==0
    assert 'reload nginx' in calls.read_text()
    tool('identity-import','--cert',leaf,'--chain',ca['intermediate'])
    assert run('--apply',FAIL_RELOAD='1').returncode!=0
    assert marker.exists()
    assert run('--apply').returncode==0
    assert not marker.exists()
