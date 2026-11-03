"""Real file identities and production Modbus TLS transport, without libteec."""
import os
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

static sysPara config = {1};
sysPara *SysConf_GetInfo(void) { return &config; }
void dzlog(const char *file, size_t fl, const char *func, size_t fn,
           long line, int level, const char *format, ...) {
    (void)file; (void)fl; (void)func; (void)fn; (void)line; (void)level;
    va_list args; va_start(args, format); vfprintf(stderr, format, args); va_end(args);
}
static const unsigned char adu[] = {0,1,0,0,0,6,1,3,0,0,0,1};
static void *server(void *arg) {
    int fd = *(int *)arg;
    unsigned char received[260];
    assert(Modbus_Server_Attach(fd) == 0);
    ssize_t n;
    do { n = Modbus_Recv(fd, received, sizeof(received)); } while (n < 0 && errno == EAGAIN);
    assert(n == sizeof(adu) && !memcmp(adu, received, sizeof(adu)));
    assert(Modbus_Send(fd, received, n) == n);
    Modbus_Close(fd);
    return NULL;
}
int main(void) {
    int pair[2]; pthread_t thread; unsigned char received[260];
    assert(Modbus_Server_Init() == 0);
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    assert(pthread_create(&thread, NULL, server, &pair[0]) == 0);
    assert(Modbus_Client_Attach(pair[1]) == 0);
    assert(Modbus_Send(pair[1], adu, sizeof(adu)) == sizeof(adu));
    ssize_t n;
    do { n = Modbus_Recv(pair[1], received, sizeof(received)); } while (n < 0 && errno == EAGAIN);
    assert(n == sizeof(adu) && !memcmp(adu, received, sizeof(adu)));
    Modbus_Close(pair[1]); pthread_join(thread, NULL);
    return 0;
}
'''


def main():
    with tempfile.TemporaryDirectory(prefix='modbus-file-test-') as temp:
        directory = Path(temp)
        executable = directory / 'identity'
        compile_base = ['cc', '-std=c99', '-Wall', '-Wextra', '-Werror',
                        '-Wno-deprecated-declarations', '-DMODBUS_WITH_TEE=0',
                        '-I' + str(ROOT / 'logger/lib')]
        run(*compile_base, ROOT / 'logger/scripts/modbus_tee_identity.c',
            ROOT / 'logger/lib/modbus_identity.c', '-lcrypto', '-lpthread', '-o', executable)
        assert b'libteec' not in run('ldd', executable)
        env = dict(os.environ, MODBUS_TEE_IDENTITY=str(executable))
        env.pop('MODBUS_KEY_BACKEND', None)
        certdir = directory / 'certs'
        base = ['python3', ROOT / 'logger/scripts/modbus_certs.py', '--dir', certdir]
        for role in ('master', 'slave'):
            run(*base, 'generate', '--role', role, '--name', 'device-' + role, env=env)
            key = certdir / (role + '.key')
            assert key.stat().st_mode & 0o777 == 0o600
            assert key.read_bytes().startswith(b'-----BEGIN PRIVATE KEY-----')
            run(*base, 'check', '--role', role, env=env)
        master = certdir / 'master.crt'
        key = certdir / 'master.key'
        original_key = key.read_bytes()
        original_cert = master.read_bytes()
        public = run('openssl', 'x509', '-in', master, '-pubkey', '-noout')
        run(*base, 'generate', '--role', 'master', '--name', 'duplicate', env=env, success=False)
        run(*base, 'renew', '--role', 'master', '--name', 'device-master', env=env)
        assert master.read_bytes() != original_cert
        assert key.read_bytes() == original_key
        assert run('openssl', 'x509', '-in', master, '-pubkey', '-noout') == public
        run(*base, 'trust-add', '--cert', master, env=env)
        run(executable, '--dir', certdir, 'check', 'slave', master, env=env, success=False)

        # Run the unchanged transport IO against its real identity-loading seam.
        (directory / 'transport.c').write_text(TRANSPORT_TEST)
        (directory / 'config.h').write_text(
            '#define _GNU_SOURCE\n#include <errno.h>\n#define APPCONF_H_\n'
            'typedef unsigned char INT8U;\n'
            'typedef struct { INT8U modbus_tls_enabled; } sysPara;\n'
            'sysPara *SysConf_GetInfo(void);\n')
        transport = directory / 'transport'
        defines = [f'-D{name}="{certdir / path}"' for name, path in (
            ('MODBUS_TLS_SERVER_CERT', 'slave.crt'),
            ('MODBUS_TLS_CLIENT_CERT', 'master.crt'),
            ('MODBUS_TLS_CLIENT_CA', 'master-ca.crt'))]
        run(*compile_base, *defines, '-include', directory / 'config.h',
            directory / 'transport.c', ROOT / 'logger/lib/modbus_transport.c',
            ROOT / 'logger/lib/modbus_identity.c', '-lssl', '-lcrypto', '-lpthread', '-o', transport)
        run(transport, env=env)
        run(transport, env=dict(env, MODBUS_KEY_BACKEND='file'))

        for value in ('', 'invalid', 'tee'):
            bad = dict(env, MODBUS_KEY_BACKEND=value)
            run(*base, 'check', '--role', 'master', env=bad, success=False)
            run(executable, 'check', 'master', master, env=bad, success=False)
            assert key.read_bytes() == original_key

        saved = certdir / 'saved.key'
        key.rename(saved)
        for operation in ('check', 'renew'):
            args = ['--name', 'device-master'] if operation == 'renew' else []
            run(*base, operation, '--role', 'master', *args, env=env, success=False)
            assert not key.exists()
        key.symlink_to(saved)
        run(*base, 'check', '--role', 'master', env=env, success=False)
        run(executable, '--dir', certdir, 'ensure', 'master', env=env, success=False)
        key.unlink(); saved.rename(key)
        key.chmod(0o644)
        run(*base, 'check', '--role', 'master', env=env, success=False)
        key.chmod(0o600)
        key.write_bytes((certdir / 'slave.key').read_bytes())
        run(*base, 'check', '--role', 'master', env=env, success=False)
        key.write_bytes(b'not a private key')
        run(*base, 'check', '--role', 'master', env=env, success=False)
        key.write_bytes(original_key)
        run(*base, 'check', '--role', 'master', env=env)
        assert master.read_bytes() != original_cert
        print('PASS: default/explicit file backend, persisted RSA keys, renewal reuses key, '
              'production TLS exchange, no libteec dependency/fallback, missing/mismatched/'
              'symlink/insecure/corrupt key rejection')


if __name__ == '__main__':
    main()
