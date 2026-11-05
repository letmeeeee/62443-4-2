#define _POSIX_C_SOURCE 200809L
#include "modbus_transport.h"
#include "app_config.h"
#include <errno.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <unistd.h>

#include <openssl/ssl.h>
#include <openssl/x509v3.h>
#include "modbus_identity.h"
#include <openssl/err.h>
#include "zlog.h"
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <time.h>

/* Registry keeps existing fd-based Modbus APIs. Each SSL has its own IO lock. */
typedef struct Connection {
    int fd, refs, failed;
    SSL *ssl;
    pthread_mutex_t io;
    unsigned char frame[260];
    size_t used, target;
    int64_t frame_deadline;
    struct Connection *next;
} Connection;
static Connection *connections;
static pthread_mutex_t registry = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t released = PTHREAD_COND_INITIALIZER;
static pthread_once_t server_once = PTHREAD_ONCE_INIT;
static pthread_once_t client_once = PTHREAD_ONCE_INIT;
static pthread_once_t library_once = PTHREAD_ONCE_INIT;
static SSL_CTX *server_ctx, *client_ctx;

/* Drain this thread's OpenSSL queue into the existing default zlog category. */
static void log_tls_errors(const char *stage, int server, int fd)
{
    unsigned long code;
    char description[256];
    int saved_errno = errno;
    dzlog_error("Modbus TLS %s failed role=%s fd=%d errno=%d",
                stage, server ? "slave" : "master", fd, saved_errno);
    while ((code = ERR_get_error()) != 0) {
        ERR_error_string_n(code, description, sizeof(description));
        dzlog_error("Modbus TLS %s role=%s fd=%d openssl=0x%lx error=%s",
                    stage, server ? "slave" : "master", fd, code, description);
    }
    errno = saved_errno;
}

/* The application loads this setting before starting communication threads. */
static int tls_enabled(void)
{
    sysPara* sys_cfg = SysConf_GetInfo();
    if (!sys_cfg || sys_cfg->modbus_tls_enabled > 1) {
        errno = EINVAL;
        return -1;
    }
    INT8U modbus_tls_enabled = sys_cfg->modbus_tls_enabled;
#ifdef ISPLANT_V
    if (modbus_tls_enabled) {
        errno = EPROTONOSUPPORT;
        return -1;
    }
#endif
    return modbus_tls_enabled;
}

static int64_t now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (int64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

static void library_init(void)
{
    /* Existing Modbus writers also ignore SIGPIPE; do so before any handshake. */
    signal(SIGPIPE, SIG_IGN);
    OPENSSL_init_ssl(0, NULL);
}

static int identity_purpose(X509 *certificate, int server_identity)
{
    BASIC_CONSTRAINTS *constraints = X509_get_ext_d2i(certificate, NID_basic_constraints, NULL, NULL);
    EXTENDED_KEY_USAGE *usage = X509_get_ext_d2i(certificate, NID_ext_key_usage, NULL, NULL);
    ASN1_BIT_STRING *key_usage = X509_get_ext_d2i(certificate, NID_key_usage, NULL, NULL);
    int valid = constraints && !constraints->ca && key_usage && ASN1_BIT_STRING_get_bit(key_usage, 0), found = 0, other = 0;
    int expected = server_identity ? NID_server_auth : NID_client_auth;
    if (usage) for (int i = 0; i < sk_ASN1_OBJECT_num(usage); i++) {
        int nid = OBJ_obj2nid(sk_ASN1_OBJECT_value(usage, i));
        if (nid == expected) found = 1;
        if (nid == (server_identity ? NID_client_auth : NID_server_auth)) other = 1;
    }
    BASIC_CONSTRAINTS_free(constraints); EXTENDED_KEY_USAGE_free(usage); ASN1_BIT_STRING_free(key_usage);
    return valid && found && !other;
}

static int ca_store_valid(X509_STORE *store)
{
    STACK_OF(X509_OBJECT) *objects = X509_STORE_get0_objects(store);
    int anchors = 0;
    for (int i = 0; i < sk_X509_OBJECT_num(objects); i++) {
        X509_OBJECT *object = sk_X509_OBJECT_value(objects, i);
        if (X509_OBJECT_get_type(object) != X509_LU_X509) continue;
        X509 *root = X509_OBJECT_get0_X509(object);
        BASIC_CONSTRAINTS *constraints = X509_get_ext_d2i(root, NID_basic_constraints, NULL, NULL);
        ASN1_BIT_STRING *usage = X509_get_ext_d2i(root, NID_key_usage, NULL, NULL);
        EVP_PKEY *key = X509_get_pubkey(root);
        int valid = constraints && constraints->ca && usage && ASN1_BIT_STRING_get_bit(usage, 5) && key &&
            X509_NAME_cmp(X509_get_subject_name(root), X509_get_issuer_name(root)) == 0 && X509_verify(root, key) == 1 &&
            X509_cmp_current_time(X509_get0_notBefore(root)) < 0 && X509_cmp_current_time(X509_get0_notAfter(root)) > 0;
        BASIC_CONSTRAINTS_free(constraints); ASN1_BIT_STRING_free(usage); EVP_PKEY_free(key);
        if (!valid) return 0;
        anchors++;
    }
    return anchors > 0;
}

static int verify_peer(int verified, X509_STORE_CTX *context)
{
    if (!verified || X509_STORE_CTX_get_error_depth(context) != 0) return verified;
    SSL *ssl = X509_STORE_CTX_get_ex_data(context, SSL_get_ex_data_X509_STORE_CTX_idx());
    /* A slave expects a clientAuth master; a master expects a serverAuth slave. */
    return ssl && identity_purpose(X509_STORE_CTX_get_current_cert(context), !SSL_is_server(ssl));
}

static int verify_local_chain(SSL_CTX *context, int server)
{
    X509_STORE_CTX *verification = X509_STORE_CTX_new();
    STACK_OF(X509) *chain = NULL;
    X509 *identity = SSL_CTX_get0_certificate(context);
    int ok = 0;
    SSL_CTX_get0_chain_certs(context, &chain);
    if (!verification || !identity_purpose(identity, server) ||
        X509_STORE_CTX_init(verification, SSL_CTX_get_cert_store(context), identity, chain) != 1 ||
        X509_STORE_CTX_set_purpose(verification, server ? X509_PURPOSE_SSL_SERVER : X509_PURPOSE_SSL_CLIENT) != 1)
        goto out;
    X509_VERIFY_PARAM *parameters = X509_STORE_CTX_get0_param(verification);
    X509_VERIFY_PARAM_set_auth_level(parameters, 2);
    X509_VERIFY_PARAM_set_depth(parameters, 8);
    ok = X509_verify_cert(verification) == 1;
out:
    X509_STORE_CTX_free(verification);
    return ok;
}

static SSL_CTX *make_context(int server)
{
    pthread_once(&library_once, library_init);
    int ca_mode = Modbus_Certificate_Mode();
    if (ca_mode < 0) { errno = EINVAL; return NULL; }
    SSL_CTX *ctx = SSL_CTX_new(server ? TLS_server_method() : TLS_client_method());
    if (!ctx) {
        log_tls_errors("context allocation", server, -1);
        return NULL;
    }
    const char *certificate_path = server ? MODBUS_TLS_SERVER_CERT : MODBUS_TLS_CLIENT_CERT;
    EVP_PKEY *key = Modbus_Identity_Key(server ? 1 : 0, certificate_path);
    int identity_ok = key &&
        SSL_CTX_use_certificate_chain_file(ctx, server ? MODBUS_TLS_SERVER_CERT : MODBUS_TLS_CLIENT_CERT) == 1 &&
        SSL_CTX_use_PrivateKey(ctx, key) == 1 && SSL_CTX_check_private_key(ctx) == 1 &&
        Modbus_Identity_Check(SSL_CTX_get0_certificate(ctx), server ? 1 : 0, certificate_path);
    EVP_PKEY_free(key);
    if (!identity_ok || SSL_CTX_set_min_proto_version(ctx, TLS1_2_VERSION) != 1 ||
        SSL_CTX_set_cipher_list(ctx, "ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384") != 1 ||
        SSL_CTX_set1_sigalgs_list(ctx, "rsa_pss_rsae_sha256:rsa_pss_rsae_sha384:rsa_pss_rsae_sha512:rsa_pkcs1_sha256:rsa_pkcs1_sha384:rsa_pkcs1_sha512") != 1)
        goto fail;
    {
        if (SSL_CTX_load_verify_locations(ctx, Modbus_CA_File(), NULL) != 1 ||
            !ca_store_valid(SSL_CTX_get_cert_store(ctx)) || !verify_local_chain(ctx, server))
            goto fail;
        if (server) {
            STACK_OF(X509_NAME) *names = SSL_load_client_CA_file(Modbus_CA_File());
            if (!names) goto fail;
            SSL_CTX_set_client_CA_list(ctx, names);
        }
        SSL_CTX_set_verify(ctx, SSL_VERIFY_PEER | (server ? SSL_VERIFY_FAIL_IF_NO_PEER_CERT : 0), verify_peer);
        SSL_CTX_set_session_cache_mode(ctx, SSL_SESS_CACHE_OFF);
        SSL_CTX_set_options(ctx, SSL_OP_NO_TICKET);
        X509_VERIFY_PARAM_set_auth_level(SSL_CTX_get0_param(ctx), 2);
        SSL_CTX_set_verify_depth(ctx, 8);
    }
    return ctx;
fail:
    log_tls_errors("certificate/key/trust configuration", server, -1);
    SSL_CTX_free(ctx);
    return NULL;
}
static void server_init(void) { server_ctx = make_context(1); }
static void client_init(void) { client_ctx = make_context(0); }

int Modbus_Server_Init(void)
{
    int enabled = tls_enabled();
    if (enabled <= 0) return enabled;
    pthread_once(&server_once, server_init);
    if (!server_ctx) { errno = EPROTO; return -1; }
    return 0;
}

/* Returns -1 with EAGAIN on deadline, or a terminal socket error. */
static int wait_io(int fd, int error, int64_t deadline)
{
    struct pollfd p = { fd, error == SSL_ERROR_WANT_WRITE ? POLLOUT : POLLIN, 0 };
    for (;;) {
        int64_t left = deadline - now_ms();
        if (left <= 0) { errno = EAGAIN; return -1; }
        int n = poll(&p, 1, left > INT_MAX ? INT_MAX : (int)left);
        if (n > 0) {
            if (p.revents & POLLNVAL) { errno = EBADF; return -1; }
            return 0; /* SSL consumes EOF/errors as well as readable data. */
        }
        if (n == 0) { errno = EAGAIN; return -1; }
        if (errno != EINTR) return -1;
    }
}

static int attach(int fd, int server)
{
    int enabled = tls_enabled();
    if (enabled <= 0) return enabled;
    SSL_CTX *ctx;
    if (server) {
        if (Modbus_Server_Init() < 0) return -1;
        ctx = server_ctx;
    } else {
        pthread_once(&client_once, client_init);
        ctx = client_ctx;
    }
    if (!ctx) { errno = EPROTO; return -1; }
    int flags = fcntl(fd, F_GETFL, 0);
    if (flags < 0 || fcntl(fd, F_SETFL, flags | O_NONBLOCK) < 0) return -1;
    Connection *c = calloc(1, sizeof(*c));
    if (!c) return -1;
    c->fd = fd;
    c->target = 6;
    c->ssl = SSL_new(ctx);
    if (!c->ssl || SSL_set_fd(c->ssl, fd) != 1) goto fail;
    if (!server) {
        struct sockaddr_storage peer;
        socklen_t length = sizeof(peer);
        char address[INET6_ADDRSTRLEN];
        if (getpeername(fd, (struct sockaddr *)&peer, &length) < 0) goto fail;
        const void *binary = peer.ss_family == AF_INET ?
            (const void *)&((struct sockaddr_in *)&peer)->sin_addr : peer.ss_family == AF_INET6 ?
            (const void *)&((struct sockaddr_in6 *)&peer)->sin6_addr : NULL;
        if (!binary || !inet_ntop(peer.ss_family, binary, address, sizeof(address)) ||
            X509_VERIFY_PARAM_set1_ip_asc(SSL_get0_param(c->ssl), address) != 1) goto fail;
    }
    int64_t deadline = now_ms() + MODBUS_TLS_HANDSHAKE_MS;
    for (;;) {
        ERR_clear_error();
        int rc = server ? SSL_accept(c->ssl) : SSL_connect(c->ssl);
        if (rc == 1) break;
        int e = SSL_get_error(c->ssl, rc);
        if (e != SSL_ERROR_WANT_READ && e != SSL_ERROR_WANT_WRITE) goto fail;
        if (wait_io(fd, e, deadline) < 0) goto fail;
    }
    if (pthread_mutex_init(&c->io, NULL) != 0) goto fail;
    pthread_mutex_lock(&registry);
    c->next = connections;
    connections = c;
    pthread_mutex_unlock(&registry);
    return 0;
fail:
    log_tls_errors("handshake", server, fd);
    SSL_free(c->ssl);
    free(c);
    errno = EPROTO;
    return -1;
}
int Modbus_Client_Attach(int fd) { return attach(fd, 0); }
int Modbus_Server_Attach(int fd) { return attach(fd, 1); }

static Connection *acquire(int fd)
{
    pthread_mutex_lock(&registry);
    Connection *c;
    for (c = connections; c && c->fd != fd; c = c->next) {}
    if (c) ++c->refs;
    pthread_mutex_unlock(&registry);
    if (c) pthread_mutex_lock(&c->io);
    else errno = ENOTCONN; /* Never silently send plaintext in TLS mode. */
    return c;
}
static void release(Connection *c)
{
    int saved = errno;
    pthread_mutex_unlock(&c->io);
    pthread_mutex_lock(&registry);
    --c->refs;
    pthread_cond_broadcast(&released);
    pthread_mutex_unlock(&registry);
    errno = saved;
}
static int timeout_ms(int fd, int option)
{
    struct timeval tv = {0};
    socklen_t n = sizeof(tv);
    if (getsockopt(fd, SOL_SOCKET, option, &tv, &n) == 0 && (tv.tv_sec || tv.tv_usec)) {
        int64_t ms = (int64_t)tv.tv_sec * 1000 + (tv.tv_usec + 999) / 1000;
        return ms > INT_MAX ? INT_MAX : (int)ms;
    }
    return MODBUS_TLS_FRAME_MS;
}

ssize_t Modbus_Recv(int fd, void *buf, size_t capacity)
{
    int enabled = tls_enabled();
    if (enabled < 0) return -1;
    if (!enabled) return recv(fd, buf, capacity, 0);
    Connection *c = acquire(fd);
    if (!c) return -1;
    ssize_t result = -1;
    int64_t deadline = now_ms() + timeout_ms(fd, SO_RCVTIMEO);
    if (c->failed) { errno = EPROTO; goto done; }
    for (;;) {
        if (c->used && now_ms() >= c->frame_deadline) {
            errno = ETIMEDOUT; c->failed = 1; goto done;
        }
        if (c->used == c->target) {
            if (c->target == 6) {
                size_t length = ((size_t)c->frame[4] << 8) | c->frame[5];
                if (c->frame[2] || c->frame[3] || length < 2 || length > 254) {
                    errno = EPROTO; c->failed = 1; goto done;
                }
                c->target = 6 + length;
            } else {
                if (c->target > capacity) { errno = EMSGSIZE; c->failed = 1; goto done; }
                memcpy(buf, c->frame, c->target);
                result = (ssize_t)c->target;
                c->used = 0;
                c->target = 6;
                goto done;
            }
        }
        ERR_clear_error();
        int rc = SSL_read(c->ssl, c->frame + c->used, (int)(c->target - c->used));
        if (rc > 0) {
            if (!c->used) c->frame_deadline = now_ms() + MODBUS_TLS_FRAME_MS;
            c->used += (size_t)rc;
            continue;
        }
        int e = SSL_get_error(c->ssl, rc);
        if (e == SSL_ERROR_ZERO_RETURN) {
            result = c->used ? -1 : 0;
            errno = ECONNRESET; c->failed = 1; goto done;
        }
        if (e != SSL_ERROR_WANT_READ && e != SSL_ERROR_WANT_WRITE) {
            errno = EPROTO; c->failed = 1; goto done;
        }
        int64_t until = deadline;
        if (c->used && c->frame_deadline < until) until = c->frame_deadline;
        if (wait_io(fd, e, until) < 0) {
            if (c->used && now_ms() >= c->frame_deadline) {
                errno = ETIMEDOUT; c->failed = 1;
            } else if (errno != EAGAIN) c->failed = 1;
            goto done;
        }
    }
done:
    release(c);
    return result;
}

ssize_t Modbus_Send(int fd, const void *buf, size_t length)
{
    int enabled = tls_enabled();
    if (enabled < 0) return -1;
    if (!enabled) return send(fd, buf, length, MSG_NOSIGNAL);
    Connection *c = acquire(fd);
    if (!c) return -1;
    ssize_t result = -1;
    size_t sent = 0;
    int64_t deadline = now_ms() + timeout_ms(fd, SO_SNDTIMEO);
    if (c->failed || length > INT_MAX) { errno = EPROTO; goto done; }
    while (sent < length) {
        ERR_clear_error();
        int rc = SSL_write(c->ssl, (const unsigned char *)buf + sent, (int)(length - sent));
        if (rc > 0) { sent += (size_t)rc; continue; }
        int e = SSL_get_error(c->ssl, rc);
        if ((e != SSL_ERROR_WANT_READ && e != SSL_ERROR_WANT_WRITE) || wait_io(fd, e, deadline) < 0) {
            /* A timed-out write must not be retried as a new Modbus request. */
            c->failed = 1; errno = EIO; goto done;
        }
    }
    result = (ssize_t)sent;
done:
    release(c);
    return result;
}

int Modbus_Close(int fd)
{
    /* Release any attached TLS session regardless of the current config. */
    pthread_mutex_lock(&registry);
    Connection **link = &connections;
    while (*link && (*link)->fd != fd) link = &(*link)->next;
    Connection *c = *link;
    if (c) {
        *link = c->next;
        while (c->refs) pthread_cond_wait(&released, &registry);
    }
    pthread_mutex_unlock(&registry);
    if (c) {
        /* Nonblocking, best-effort close_notify; never wait on a dead peer. */
        if (!c->failed) SSL_shutdown(c->ssl);
        SSL_free(c->ssl);
        pthread_mutex_destroy(&c->io);
        free(c);
    }
    return close(fd);
}
