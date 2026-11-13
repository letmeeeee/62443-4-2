#define _POSIX_C_SOURCE 200809L
#include "modbus_peers.h"
#include "../cJSON/cJSON.h"
#include "zlog.h"
#include <openssl/pem.h>
#include <arpa/inet.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define PEER_LIMIT 256
#define DEFAULT_DIRECTORY "/run/lc400/modbus-peers"

typedef struct Peer {
    int fd, server, port;
    unsigned long sequence;
    char ip[INET6_ADDRSTRLEN];
    time_t connected;
    X509 *certificate;
    struct Peer *next;
} Peer;
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t changed = PTHREAD_COND_INITIALIZER;
static pthread_once_t once = PTHREAD_ONCE_INIT;
static pthread_t publisher;
static Peer *peers;
static unsigned long sequence;
static int count, incomplete, stopping, started, enabled;
static char instance[96];

static unsigned long long process_start(void)
{
    char buffer[4096];
    FILE *file = fopen("/proc/self/stat", "r");
    if (!file) return 0;
    char *read = fgets(buffer, sizeof(buffer), file);
    fclose(file);
    char *position = read ? strrchr(buffer, ')') : NULL;
    if (!position) return 0;
    position += 2;
    for (int field = 3; field < 22; ++field) {
        position = strchr(position, ' ');
        if (!position) return 0;
        ++position;
    }
    return strtoull(position, NULL, 10);
}

static void timestamp(time_t value, char output[32])
{
    struct tm utc;
    gmtime_r(&value, &utc);
    strftime(output, 32, "%Y-%m-%dT%H:%M:%SZ", &utc);
}

static void free_list(Peer *list)
{
    while (list) {
        Peer *next = list->next;
        X509_free(list->certificate);
        free(list);
        list = next;
    }
}

/* Caller owns copy; no disk/PEM work while holding the transport-facing lock. */
static Peer *copy_list(int *complete)
{
    Peer *copy = NULL;
    pthread_mutex_lock(&lock);
    *complete = !incomplete;
    for (Peer *peer = peers; peer; peer = peer->next) {
        Peer *entry = malloc(sizeof(*entry));
        if (!entry) { *complete = 0; break; }
        *entry = *peer;
        if (!X509_up_ref(entry->certificate)) { free(entry); *complete = 0; break; }
        entry->next = copy;
        copy = entry;
    }
    pthread_mutex_unlock(&lock);
    return copy;
}

static void filename(const Peer *peer, char output[160])
{
    snprintf(output, 160, "peer-%s-%lu.pem", instance, peer->sequence);
}

static int atomic_file(int directory, const char *name, const void *data, size_t length)
{
    int fd = openat(directory, ".publish.tmp", O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW | O_CLOEXEC, 0640);
    if (fd < 0) return 0;
    if (fchmod(fd, 0640) < 0) { close(fd); return 0; }
    size_t offset = 0;
    int ok = 1;
    while (offset < length) {
        ssize_t written = write(fd, (const char *)data + offset, length - offset);
        if (written < 0 && errno == EINTR) continue;
        if (written <= 0) { ok = 0; break; }
        offset += (size_t)written;
    }
    if (close(fd) < 0) ok = 0;
    if (ok && renameat(directory, ".publish.tmp", directory, name) == 0) return 1;
    unlinkat(directory, ".publish.tmp", 0);
    return 0;
}

/* Delete only our PEM names. Other files in the directory are never touched. */
static void cleanup(int directory, Peer *current)
{
    int scan = openat(directory, ".", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    DIR *stream = scan < 0 ? NULL : fdopendir(scan);
    if (!stream) { if (scan >= 0) close(scan); return; }
    struct dirent *entry;
    while ((entry = readdir(stream))) {
        size_t length = strlen(entry->d_name);
        if (strncmp(entry->d_name, "peer-", 5) || length < 9 || strcmp(entry->d_name + length - 4, ".pem")) continue;
        int keep = 0;
        for (Peer *peer = current; peer; peer = peer->next) {
            char name[160]; filename(peer, name);
            if (!strcmp(name, entry->d_name)) { keep = 1; break; }
        }
        if (!keep) unlinkat(directory, entry->d_name, 0);
    }
    closedir(stream);
}

static int publish(int directory, Peer *current, int complete, unsigned long long start)
{
    cJSON *root = cJSON_CreateObject(), *array = cJSON_CreateArray();
    if (!root || !array) { cJSON_Delete(root); cJSON_Delete(array); return 0; }
    cJSON_AddItemToObject(root, "peers", array);
    char now[32]; timestamp(time(NULL), now);
    struct timespec monotonic;
    clock_gettime(CLOCK_MONOTONIC, &monotonic);
    cJSON_AddNumberToObject(root, "schemaVersion", 1);
    cJSON_AddStringToObject(root, "instanceId", instance);
    cJSON_AddNumberToObject(root, "producerPid", getpid());
    char ticks[32]; snprintf(ticks, sizeof(ticks), "%llu", start);
    cJSON_AddStringToObject(root, "producerStartTicks", ticks);
    cJSON_AddStringToObject(root, "updatedAt", now);
    cJSON_AddNumberToObject(root, "heartbeatMonotonic", monotonic.tv_sec + monotonic.tv_nsec / 1e9);
    pthread_mutex_lock(&lock);
    int tls = enabled;
    pthread_mutex_unlock(&lock);
    cJSON_AddBoolToObject(root, "tlsEnabled", tls);
    cJSON_AddBoolToObject(root, "complete", complete);
    int ok = 1;
    for (Peer *peer = current; peer; peer = peer->next) {
        char name[160], connected[32], id[128]; filename(peer, name);
        struct stat metadata;
        if (fstatat(directory, name, &metadata, AT_SYMLINK_NOFOLLOW) < 0) {
            BIO *pem = BIO_new(BIO_s_mem());
            char *data = NULL;
            if (!pem || PEM_write_bio_X509(pem, peer->certificate) != 1) {
                BIO_free(pem); ok = 0; break;
            }
            long length = BIO_get_mem_data(pem, &data);
            ok = length > 0 && atomic_file(directory, name, data, (size_t)length);
            BIO_free(pem);
            if (!ok) break;
        }
        cJSON *item = cJSON_CreateObject();
        if (!item) { ok = 0; break; }
        cJSON_AddItemToArray(array, item);
        snprintf(id, sizeof(id), "%s-%lu", instance, peer->sequence);
        timestamp(peer->connected, connected);
        cJSON_AddStringToObject(item, "connectionId", id);
        cJSON_AddStringToObject(item, "localRole", peer->server ? "slave" : "master");
        cJSON_AddStringToObject(item, "peerIp", peer->ip);
        cJSON_AddNumberToObject(item, "peerPort", peer->port);
        cJSON_AddStringToObject(item, "transport", "tls");
        cJSON_AddStringToObject(item, "connectionStatus", "connected");
        cJSON_AddStringToObject(item, "authenticationStatus", "verified");
        cJSON_AddStringToObject(item, "connectedAt", connected);
        cJSON_AddStringToObject(item, "certificateFile", name);
    }
    char *data = ok ? cJSON_PrintUnformatted(root) : NULL;
    ok = data && atomic_file(directory, "status.json", data, strlen(data));
    free(data);
    cJSON_Delete(root);
    return ok;
}

static void *worker(void *unused)
{
    (void)unused;
    const char *path = getenv("MODBUS_PEER_STATE_DIR");
    if (!path || !*path) { path = DEFAULT_DIRECTORY; mkdir("/run/lc400", 0750); }
    if (mkdir(path, 0750) < 0 && errno != EEXIST) goto fail;
    int directory = open(path, O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    struct stat metadata;
    if (directory < 0) goto fail;
    if (fstat(directory, &metadata) || metadata.st_uid != geteuid() || (metadata.st_mode & 0022)) {
        close(directory); goto fail;
    }
    int ownership = openat(directory, ".lock", O_RDWR | O_CREAT | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (ownership < 0 || flock(ownership, LOCK_EX | LOCK_NB) < 0) {
        if (ownership >= 0) close(ownership);
        close(directory); goto fail;
    }
    cleanup(directory, NULL);
    unlinkat(directory, "status.json", 0);
    unsigned long long start = process_start();
    int warned = 0;
    for (;;) {
        int complete;
        Peer *snapshot = copy_list(&complete);
        int ok = start && publish(directory, snapshot, complete, start);
        /* Delete disconnected certificates even if publishing the new JSON failed. */
        cleanup(directory, snapshot);
        free_list(snapshot);
        if (!ok && !warned) dzlog_warn("Modbus peer telemetry publication failed; communication continues");
        warned = !ok;
        pthread_mutex_lock(&lock);
        if (!stopping) {
            struct timespec deadline;
            clock_gettime(CLOCK_REALTIME, &deadline); ++deadline.tv_sec;
            pthread_cond_timedwait(&changed, &lock, &deadline);
        }
        int stop = stopping;
        pthread_mutex_unlock(&lock);
        if (stop) break;
    }
    unlinkat(directory, "status.json", 0);
    cleanup(directory, NULL);
    unlinkat(directory, ".publish.tmp", 0);
    close(ownership); close(directory);
    return NULL;
fail:
    dzlog_warn("Modbus peer telemetry directory unavailable; communication continues");
    return NULL;
}

static void stop_worker(void)
{
    pthread_mutex_lock(&lock);
    stopping = 1;
    pthread_cond_signal(&changed);
    pthread_mutex_unlock(&lock);
    if (started) pthread_join(publisher, NULL);
}

static void initialize(void)
{
    struct timespec now;
    clock_gettime(CLOCK_REALTIME, &now);
    snprintf(instance, sizeof(instance), "%ld-%lld-%ld", (long)getpid(), (long long)now.tv_sec, now.tv_nsec);
    if (pthread_create(&publisher, NULL, worker, NULL) == 0) {
        started = 1;
        atexit(stop_worker);
    } else dzlog_warn("Modbus peer telemetry thread unavailable; communication continues");
}

void Modbus_Peers_Start(int tls_enabled)
{
    int saved = errno;
    pthread_mutex_lock(&lock);
    enabled = tls_enabled > 0;
    pthread_mutex_unlock(&lock);
    pthread_once(&once, initialize);
    errno = saved;
}

void Modbus_Peers_Add(int fd, int server, SSL *ssl)
{
    int saved = errno;
    X509 *certificate = SSL_get_peer_certificate(ssl);
    struct sockaddr_storage address;
    socklen_t size = sizeof(address);
    Peer *entry = calloc(1, sizeof(*entry));
    if (!entry || !certificate || SSL_get_verify_result(ssl) != X509_V_OK ||
        getpeername(fd, (struct sockaddr *)&address, &size) < 0) goto fail;
    const void *binary = address.ss_family == AF_INET ? (void *)&((struct sockaddr_in *)&address)->sin_addr :
        address.ss_family == AF_INET6 ? (void *)&((struct sockaddr_in6 *)&address)->sin6_addr : NULL;
    if (!binary || !inet_ntop(address.ss_family, binary, entry->ip, sizeof(entry->ip))) goto fail;
    entry->port = ntohs(address.ss_family == AF_INET ? ((struct sockaddr_in *)&address)->sin_port :
                        ((struct sockaddr_in6 *)&address)->sin6_port);
    entry->fd = fd; entry->server = server; entry->certificate = certificate; entry->connected = time(NULL);
    pthread_mutex_lock(&lock);
    if (count >= PEER_LIMIT) {
        incomplete = 1; pthread_mutex_unlock(&lock); goto fail;
    }
    entry->sequence = ++sequence; entry->next = peers; peers = entry; ++count;
    pthread_cond_signal(&changed);
    pthread_mutex_unlock(&lock);
    errno = saved;
    return;
fail:
    free(entry); X509_free(certificate);
    pthread_mutex_lock(&lock); incomplete = 1; pthread_cond_signal(&changed); pthread_mutex_unlock(&lock);
    errno = saved;
}

void Modbus_Peers_Remove(int fd)
{
    int saved = errno;
    pthread_mutex_lock(&lock);
    Peer **position = &peers;
    while (*position && (*position)->fd != fd) position = &(*position)->next;
    Peer *entry = *position;
    if (entry) { *position = entry->next; --count; }
    pthread_cond_signal(&changed);
    pthread_mutex_unlock(&lock);
    if (entry) { X509_free(entry->certificate); free(entry); }
    errno = saved;
}
