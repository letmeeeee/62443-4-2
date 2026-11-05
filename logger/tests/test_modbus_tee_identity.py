"""End-to-end certificate CLI/script tests using a software TEEC substitute."""
import os
import sys
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def run(*args, env=None, success=True):
    result = subprocess.run(list(map(str, args)), env=env, capture_output=True)
    if success and result.returncode:
        raise AssertionError(result.stderr.decode())
    if not success and not result.returncode:
        raise AssertionError('operation unexpectedly succeeded')
    return result.stdout


def main():
    header = os.environ.get('OPTEE_CLIENT_INCLUDE_DIR', str(ROOT / 'logger/.deps/optee-arm64/include'))
    with tempfile.TemporaryDirectory(prefix='modbus-tee-test-') as temp:
        directory = Path(temp)
        executable = directory / 'modbus_tee_identity'
        store = directory / 'mock-ta-store'
        store.mkdir(mode=0o700)
        run('cc', '-std=c99', '-Wall', '-Wextra', '-Werror',
            '-Wno-deprecated-declarations', '-DMODBUS_TEE_STUB_ONLY',
            '-I' + str(ROOT / 'logger/lib'), '-I' + header,
            '-I' + str(ROOT / 'optee_ta_examples/ta/crypto_ta/include'),
            ROOT / 'logger/scripts/modbus_tee_identity.c',
            ROOT / 'logger/lib/modbus_identity.c',
            ROOT / 'logger/lib/modbus_tee.c', ROOT / 'logger/tests/test_modbus_tee.c',
            '-lssl', '-lcrypto', '-lpthread', '-o', executable)
        env = dict(os.environ, MODBUS_TEE_IDENTITY=str(executable),
                   MODBUS_TEE_TEST_STORE=str(store), MODBUS_KEY_BACKEND='tee')
        script = ROOT / 'exec/app/script/modbus_certs.py'
        certdir = directory / 'certs'
        base = ['python3', script, '--dir', certdir]
        sys.path.insert(0,str(ROOT/'exec/app/tests'))
        from pki_test_helpers import make_ca,sign_csr
        ca=make_ca(directory/'offline-ca')
        config=directory/'device.ini'
        config.write_text('[TLS]\nca_file='+str(certdir/'ca-roots.crt')+'\n')
        base += ['--config',config]
        run(*base,'ca-import','--cert',ca['root'],env=env)
        for role in ('master','slave'):
            ips=['127.0.0.1'] if role=='slave' else []
            flags=[value for ip in ips for value in ('--ip',ip)]
            run(*base,'csr','--role',role,'--name','device-'+role,*flags,env=env)
            leaf=sign_csr(certdir/(role+'.csr'),directory/(role+'.crt'),ca,
                role='client' if role=='master' else 'server',ips=ips)
            run(*base,'identity-import','--role',role,'--cert',leaf,'--chain',ca['intermediate'],env=env)
            run(*base,'check','--role',role,env=env)
        assert not list(certdir.glob('*.key'))
        master=certdir/'master.crt'
        public=run('openssl','x509','-in',master,'-pubkey','-noout')
        run(*base,'csr','--role','master','--name','device-master',env=env)
        assert run('openssl','req','-in',certdir/'master.csr','-pubkey','-noout')==public
        run(executable,'--dir',certdir,'check','slave',master,env=env,success=False)
        (store/'0.pem').unlink()
        run(*base,'check','--role','master',env=env,success=False)
        run(*base,'csr','--role','master','--name','device-master',env=env,success=False)
        assert not (store/'0.pem').exists()
        print('PASS: TEE CSR signing and CA identity import, stable independent roles, no private-key export/fallback, missing key rejected')


if __name__ == '__main__':
    main()
