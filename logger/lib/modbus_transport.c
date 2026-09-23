#define _POSIX_C_SOURCE 200809L
#include "modbus_transport.h"
#include "app_config.h"
#include <errno.h>
#include <sys/socket.h>
#include <unistd.h>

#include <openssl/ssl.h>
#include <openssl/err.h>
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

static SSL_CTX *make_context(int server)
{
    pthread_once(&library_once, library_init);
    SSL_CTX *ctx = SSL_CTX_new(server ? TLS_server_method() : TLS_client_method());
    if (!ctx) return NULL;
    if (SSL_CTX_set_min_proto_version(ctx, TLS1_2_VERSION) != 1 ||
        SSL_CTX_use_certificate_chain_file(ctx, server ? MODBUS_TLS_SERVER_CERT : MODBUS_TLS_CLIENT_CERT) != 1 ||
        SSL_CTX_use_PrivateKey_file(ctx, server ? MODBUS_TLS_SERVER_KEY : MODBUS_TLS_CLIENT_KEY, SSL_FILETYPE_PEM) != 1 ||
        SSL_CTX_check_private_key(ctx) != 1)
        goto fail;
    if (server) {
        if (SSL_CTX_load_verify_locations(ctx, MODBUS_TLS_CLIENT_CA, NULL) != 1)
            goto fail;
        STACK_OF(X509_NAME) *names = SSL_load_client_CA_file(MODBUS_TLS_CLIENT_CA);
        if (!names) goto fail;
        SSL_CTX_set_client_CA_list(ctx, names);
        SSL_CTX_set_verify(ctx, SSL_VERIFY_PEER | SSL_VERIFY_FAIL_IF_NO_PEER_CERT, NULL);
        /* Every new connection must authenticate with a current certificate. */
        SSL_CTX_set_session_cache_mode(ctx, SSL_SESS_CACHE_OFF);
        SSL_CTX_set_options(ctx, SSL_OP_NO_TICKET);
    } else {
        /* Requirement: present client identity, do not verify slave identity. */
        SSL_CTX_set_verify(ctx, SSL_VERIFY_NONE, NULL);
    }
    return ctx;
fail:
    fprintf(stderr, "Modbus TLS: failed to load %s certificate/key/CA\n", server ? "server" : "client");
    ERR_print_errors_fp(stderr);
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
    fprintf(stderr, "Modbus TLS: %s handshake failed fd=%d\n", server ? "server" : "client", fd);
    ERR_print_errors_fp(stderr);
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
