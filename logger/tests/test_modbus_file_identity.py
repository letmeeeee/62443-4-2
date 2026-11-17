"""Real file identities and production Modbus TLS transport, without libteec."""
import os
import json
import time
import sys
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def run(*args, env=None, success=True):
    result = subprocess.run(list(map(str, args)), env=env, capture_output=True, timeout=90)
    if (result.returncode == 0) != success:
        raise AssertionError(result.stderr.decode(errors='replace'))
    return result.stdout


TRANSPORT_TEST = r'''
#include "modbus_transport.h"
#include <assert.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <unistd.h>

static sysPara config = {1};
sysPara *SysConf_GetInfo(void) { return &config; }
void dzlog(const char *file, size_t fl, const char *func, size_t fn,
           long line, int level, const char *format, ...) {
    (void)file; (void)fl; (void)func; (void)fn; (void)line; (void)level;
    va_list args; va_start(args, format); vfprintf(stderr, format, args); va_end(args);
}
static int expected_failure;
static const unsigned char adu[] = {0,1,0,0,0,6,1,3,0,0,0,1};
static void *server(void *arg) {
    int fd = *(int *)arg;
    unsigned char received[260];
    int attached = Modbus_Server_Attach(fd);
    if (expected_failure) { assert(attached < 0); close(fd); return NULL; }
    assert(attached == 0);
    ssize_t n;
    do { n = Modbus_Recv(fd, received, sizeof(received)); } while (n < 0 && errno == EAGAIN);
    assert(n == sizeof(adu) && !memcmp(adu, received, sizeof(adu)));
    assert(Modbus_Send(fd, received, n) == n);
    Modbus_Close(fd);
    return NULL;
}
int main(int argc, char **argv) {
    (void)argv; expected_failure = argc > 1;
    int pair[2]; pthread_t thread; unsigned char received[260];
    assert(Modbus_Server_Init() == 0);
    int listener = socket(AF_INET, SOCK_STREAM, 0);
    assert(listener >= 0);
    struct sockaddr_in address = {0}; address.sin_family = AF_INET;
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    assert(bind(listener, (struct sockaddr *)&address, sizeof(address)) == 0);
    socklen_t length = sizeof(address);
    assert(getsockname(listener, (struct sockaddr *)&address, &length) == 0);
    assert(listen(listener, 1) == 0);
    pair[1] = socket(AF_INET, SOCK_STREAM, 0);
    assert(connect(pair[1], (struct sockaddr *)&address, sizeof(address)) == 0);
    pair[0] = accept(listener, NULL, NULL); close(listener);
    assert(pair[0] >= 0);
    assert(pthread_create(&thread, NULL, server, &pair[0]) == 0);
    int attached = Modbus_Client_Attach(pair[1]);
    if (expected_failure) { assert(attached < 0); close(pair[1]); pthread_join(thread, NULL); return 0; }
    assert(attached == 0);
    assert(Modbus_Send(pair[1], adu, sizeof(adu)) == sizeof(adu));
    ssize_t n;
    do { n = Modbus_Recv(pair[1], received, sizeof(received)); } while (n < 0 && errno == EAGAIN);
    assert(n == sizeof(adu) && !memcmp(adu, received, sizeof(adu)));
    Modbus_Close(pair[1]); pthread_join(thread, NULL);
    return 0;
}
'''


def main():
    sys.path.insert(0,str(ROOT/'exec/app/tests'))
    from pki_test_helpers import make_ca,sign_csr
    with tempfile.TemporaryDirectory(prefix='modbus-file-ca-') as temp:
        directory=Path(temp)
        executable=directory/'identity'
        compile_base=['cc','-std=c99','-Wall','-Wextra','-Werror','-Wno-deprecated-declarations',
                      '-DMODBUS_WITH_TEE=0','-I'+str(ROOT/'logger/lib')]
        run(*compile_base,ROOT/'logger/scripts/modbus_tee_identity.c',ROOT/'logger/lib/modbus_identity.c',
            '-lcrypto','-lpthread','-o',executable)
        assert b'libteec' not in run('ldd',executable)
        certdir=directory/'certs'
        ca=make_ca(directory/'offline-ca')
        config=directory/'device.ini'
        config.write_text('[TLS]\nca_file='+str(certdir/'ca-roots.crt')+'\n')
        env=dict(os.environ,MODBUS_TEE_IDENTITY=str(executable),LC_INI_PATH=str(config),
                 MODBUS_PEER_STATE_DIR=str(directory/'peers'))
        env.pop('MODBUS_KEY_BACKEND',None)
        base=['python3',ROOT/'exec/app/script/modbus_certs.py','--config',config,'--dir',certdir]
        run(*base,'ca-import','--cert',ca['root'],env=env)
        def issue(role,ips=()):
            args=[value for ip in ips for value in ('--ip',ip)]
            run(*base,'csr','--role',role,'--name','device-'+role,*args,env=env)
            leaf=sign_csr(certdir/(role+'.csr'),directory/(role+'-issued.crt'),ca,
                          role='client' if role=='master' else 'server',ips=ips)
            run(*base,'identity-import','--role',role,'--cert',leaf,'--chain',ca['intermediate'],env=env)
        issue('master');issue('slave',['127.0.0.1'])
        master=certdir/'master.crt';key=certdir/'master.key'
        original_key=key.read_bytes();original_cert=master.read_bytes()
        for role in ('master','slave'):
            assert (certdir/(role+'.key')).stat().st_mode&0o777==0o600
            run(*base,'check','--role',role,env=env)
        assert (certdir/'slave.key').read_bytes()!=original_key
        issue('master')
        assert master.read_bytes()!=original_cert and key.read_bytes()==original_key
        assert list((certdir/'backups').glob('*/master.crt'))
        run(executable,'--dir',certdir,'check','slave',master,env=env,success=False)
        run(*base,'generate','--role','master','--name','forbidden',env=env,success=False)
        run(executable,'--dir',certdir,'cert','master','forbidden','365','',env=env,success=False)
        peer_test = TRANSPORT_TEST.replace('#include <assert.h>', '#include <assert.h>\n#include <stdlib.h>')
        peer_test = peer_test.replace('static int expected_failure;',
            'static int expected_failure, release_server;\n'
            'static pthread_mutex_t gate = PTHREAD_MUTEX_INITIALIZER;\n'
            'static pthread_cond_t release_gate = PTHREAD_COND_INITIALIZER;')
        peer_test = peer_test.replace('    Modbus_Close(fd);',
            '    if (getenv("PEER_TEST_HOLD")) {\n'
            '        pthread_mutex_lock(&gate);\n'
            '        while (!release_server) pthread_cond_wait(&release_gate, &gate);\n'
            '        pthread_mutex_unlock(&gate);\n'
            '    }\n    Modbus_Close(fd);')
        peer_test = peer_test.replace('    Modbus_Close(pair[1]); pthread_join(thread, NULL);',
            '    if (getenv("PEER_TEST_HOLD")) { puts("CONNECTED"); fflush(stdout); getchar(); }\n'
            '    Modbus_Close(pair[1]);\n'
            '    if (getenv("PEER_TEST_HOLD")) { puts("CLIENT_CLOSED"); fflush(stdout); getchar(); }\n'
            '    pthread_mutex_lock(&gate); release_server = 1;\n'
            '    pthread_cond_signal(&release_gate); pthread_mutex_unlock(&gate);\n'
            '    pthread_join(thread, NULL);\n'
            '    if (getenv("PEER_TEST_HOLD")) { puts("CLOSED"); fflush(stdout); getchar(); }')
        (directory/'transport.c').write_text(peer_test)
        (directory/'config.h').write_text('#define _GNU_SOURCE\n#include <errno.h>\n#define APPCONF_H_\n'
            'typedef unsigned char INT8U;\ntypedef struct { INT8U modbus_tls_enabled; } sysPara;\n'
            'sysPara *SysConf_GetInfo(void);\n')
        transport=directory/'transport'
        defines=[f'-D{name}="{certdir/path}"' for name,path in
                 (('MODBUS_TLS_SERVER_CERT','slave.crt'),('MODBUS_TLS_CLIENT_CERT','master.crt'))]
        run(*compile_base,*defines,'-include',directory/'config.h',directory/'transport.c',
            ROOT/'logger/lib/modbus_transport.c',ROOT/'logger/lib/modbus_identity.c',
            ROOT/'logger/lib/modbus_peers.c',ROOT/'logger/cJSON/cJSON.c',
            '-lssl','-lcrypto','-lpthread','-o',transport)
        run(transport,env=env)
        state_directory = directory/'peers'
        state_directory.mkdir(exist_ok=True)
        (state_directory/'peer-obsolete.pem').write_text('old')
        hold_env = dict(env, PEER_TEST_HOLD='1')
        process = subprocess.Popen([str(transport)], env=hold_env, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def wait_state(expected):
            deadline = time.monotonic()+8
            while time.monotonic() < deadline:
                try:
                    state=json.loads((state_directory/'status.json').read_text())
                    files=list(state_directory.glob('peer-*.pem'))
                    if state['complete'] and len(state['peers']) == expected and len(files) == expected:
                        return state
                except (OSError, ValueError):
                    pass
                time.sleep(0.05)
            raise AssertionError('peer state did not converge: '+str(expected))
        try:
            assert process.stdout.readline().strip() == 'CONNECTED'
            state = wait_state(2)
            assert not (state_directory/'peer-obsolete.pem').exists()
            assert {entry['localRole'] for entry in state['peers']} == {'master','slave'}
            assert len({entry['connectionId'] for entry in state['peers']}) == 2
            for entry in state['peers']:
                assert entry['authenticationStatus'] == 'verified'
                pem=(state_directory/entry['certificateFile']).read_bytes()
                assert b'BEGIN CERTIFICATE' in pem and b'PRIVATE KEY' not in pem
            # Query the production Flask-side reader against the real C snapshot and PEMs.
            from flask import Flask
            sys.path.insert(0,str(ROOT/'exec/app'))
            from utils.modbus_peers import peer_status
            app=Flask(__name__)
            app.config['MODBUS_PEER_STATE_DIR']=str(state_directory)
            with app.app_context():
                result=peer_status()
                assert result['liveAuthenticationTelemetryAvailable'] and len(result['data']) == 2
            process.stdin.write('\n'); process.stdin.flush()
            assert process.stdout.readline().strip() == 'CLIENT_CLOSED'
            wait_state(1)
            process.stdin.write('\n'); process.stdin.flush()
            assert process.stdout.readline().strip() == 'CLOSED'
            wait_state(0)
            with app.app_context():
                assert peer_status()['liveAuthenticationTelemetryAvailable']
                assert peer_status()['data'] == []
            process.stdin.write('\n'); process.stdin.flush()
            assert process.wait(timeout=8) == 0
            assert not list(state_directory.glob('peer-*.pem'))
            assert not (state_directory/'status.json').exists()
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=5)
        # Abrupt termination must not turn leftover PEMs into connected peers.
        process = subprocess.Popen([str(transport)], env=hold_env, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            assert process.stdout.readline().strip() == 'CONNECTED'
            wait_state(2)
            process.kill(); process.wait(timeout=8)
            with app.app_context():
                result=peer_status()
                assert not result['liveAuthenticationTelemetryAvailable'] and not result['data']
            # Next producer clears stale certificates left by a killed process.
            run(transport, env=env)
            assert not list(state_directory.glob('peer-*.pem'))
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=5)
        # Publication failures must not break real TLS traffic.
        (directory/'not-a-directory').write_text('blocked')
        run(transport,env=dict(env,MODBUS_PEER_STATE_DIR=str(directory/'not-a-directory'/'peers')))
        issue('slave',['192.0.2.99'])
        run(transport,'reject',env=env)
        issue('slave',['127.0.0.1'])
        anchors=(certdir/'ca-roots.crt').read_bytes()
        (certdir/'ca-roots.crt').write_bytes(master.read_bytes()+(certdir/'slave.crt').read_bytes())
        run(transport,env=env,success=False)
        (certdir/'ca-roots.crt').write_bytes(anchors)
        valid_master=master.read_bytes()
        expired=sign_csr(certdir/'master.csr',directory/'expired-master.crt',ca,role='client',days=-1)
        master.write_bytes(expired.read_bytes()+ca['intermediate'].read_bytes())
        run(transport,'reject',env=env)
        master.write_bytes(valid_master)
        for value in ('','invalid','tee'):
            bad=dict(env,MODBUS_KEY_BACKEND=value)
            run(*base,'check','--role','master',env=bad,success=False)
        saved=certdir/'saved.key';key.rename(saved)
        for operation in ('check','csr'):
            args=['--name','device-master'] if operation=='csr' else []
            run(*base,operation,'--role','master',*args,env=env,success=False)
            assert not key.exists()
        key.symlink_to(saved)
        run(*base,'check','--role','master',env=env,success=False)
        key.unlink();saved.rename(key)
        key.chmod(0o644)
        run(*base,'check','--role','master',env=env,success=False)
        key.chmod(0o600)
        for content in ((certdir/'slave.key').read_bytes(),b'not a private key'):
            key.write_bytes(content)
            run(*base,'check','--role','master',env=env,success=False)
        key.write_bytes(original_key)
        run(*base,'check','--role','master',env=env)
        # Mixed-size peers must still perform the production mutual-TLS/Modbus exchange.
        for master_bits, slave_bits in ((3072, 2048), (2048, 3072)):
            for role, bits in (('master', master_bits), ('slave', slave_bits)):
                path = certdir/(role+'.key')
                run('openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt',
                    'rsa_keygen_bits:'+str(bits), '-out', path)
                path.chmod(0o600)
                before = path.read_bytes()
                issue(role, ['127.0.0.1'] if role == 'slave' else ())
                assert path.read_bytes() == before
                assert (str(bits)+' bit').encode() in run(
                    'openssl', 'req', '-in', certdir/(role+'.csr'), '-text', '-noout')
            run(transport, env=env)
        print('PASS: file CSR/CA-chain import, independent persisted keys, mutual TLS Modbus exchange, '
              'RSA-2048/3072 mixed-size peers and existing-key reuse, '
              'peer IP SAN rejection, no self-signing/fallback, missing/mismatched/insecure keys rejected; '
              'live peer snapshot/Flask read, disconnect cleanup, crash recovery and I/O failure isolation')


if __name__=='__main__':
    main()
