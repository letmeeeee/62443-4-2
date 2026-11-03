#define _GNU_SOURCE
#include "modbus_identity.h"
#ifndef MODBUS_WITH_TEE
#define MODBUS_WITH_TEE 1
#endif
#if MODBUS_WITH_TEE
#include "modbus_tee.h"
#endif
#include <openssl/pem.h>
#include <openssl/rsa.h>
#include <openssl/rand.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static pthread_once_t backend_once = PTHREAD_ONCE_INIT;
static const char *backend;

static void select_backend(void)
{
    const char *value = getenv("MODBUS_KEY_BACKEND");
    if (!value || !strcmp(value, "file")) backend = "file";
    else if (!strcmp(value, "tee")) {
#if MODBUS_WITH_TEE
        backend = "tee";
#else
        fprintf(stderr, "Modbus identity: TEE backend is not included in this build\n");
#endif
    } else fprintf(stderr, "Invalid MODBUS_KEY_BACKEND: expected file or tee\n");
    if (backend) fprintf(stderr, "Modbus identity backend=%s\n", backend);
}

const char *Modbus_Identity_Backend(void)
{
    pthread_once(&backend_once, select_backend);
    return backend;
}

/* Open the containing directory once; key access and publication use that fd. */
static int key_directory(const char *certificate_path, char name[NAME_MAX + 1])
{
    char directory[PATH_MAX], *base;
    size_t length;
    struct stat st;
    int fd;
    if (!certificate_path || strlen(certificate_path) >= sizeof(directory)) return -1;
    strcpy(directory, certificate_path);
    base = strrchr(directory, '/');
    base = base ? base + 1 : directory;
    length = strlen(base);
    if (length < 5 || length > NAME_MAX || strcmp(base + length - 4, ".crt")) return -1;
    memcpy(name, base, length + 1);
    strcpy(name + length - 4, ".key");
    if (base == directory) strcpy(directory, ".");
    else if (base == directory + 1) directory[1] = '\0';
    else base[-1] = '\0';
    fd = open(directory, O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) { perror("Modbus private key directory"); return -1; }
    if (fstat(fd, &st) || st.st_uid != geteuid() || (st.st_mode & 0022)) {
        fprintf(stderr, "Modbus private key directory must be owned by the running user and not writable by group/others\n");
        close(fd);
        return -1;
    }
    return fd;
}

static int no_password(char *buffer, int size, int writing, void *arg)
{
    (void)buffer; (void)size; (void)writing; (void)arg;
    return 0;
}

static EVP_PKEY *read_key(int directory, const char *name)
{
    struct stat st;
    EVP_PKEY *key = NULL;
    FILE *file;
    int fd = openat(directory, name, O_RDONLY | O_NONBLOCK | O_NOFOLLOW | O_CLOEXEC);
    if (fd < 0) { perror("Modbus private key open"); return NULL; }
    if (fstat(fd, &st) || !S_ISREG(st.st_mode) || st.st_uid != geteuid() ||
        (st.st_mode & 0077)) {
        fprintf(stderr, "Modbus private key must be a regular file owned by the running user with mode 0600\n");
        close(fd);
        return NULL;
    }
    file = fdopen(fd, "r");
    if (!file) { close(fd); return NULL; }
    key = PEM_read_PrivateKey(file, NULL, no_password, NULL);
    fclose(file);
    if (!key || EVP_PKEY_base_id(key) != EVP_PKEY_RSA || EVP_PKEY_bits(key) != 3072 ||
        RSA_check_key(EVP_PKEY_get0_RSA(key)) != 1) {
        fprintf(stderr, "Modbus private key must contain a valid unencrypted RSA-3072 keypair\n");
        EVP_PKEY_free(key);
        return NULL;
    }
    return key;
}

EVP_PKEY *Modbus_Identity_Key(unsigned role, const char *certificate_path)
{
    const char *selected = Modbus_Identity_Backend();
    char name[NAME_MAX + 1];
    EVP_PKEY *key;
    int fd;
    if (!selected || role > 1) return NULL;
#if MODBUS_WITH_TEE
    if (!strcmp(selected, "tee")) return Modbus_TEE_Key(role);
#endif
    fd = key_directory(certificate_path, name);
    if (fd < 0) return NULL;
    key = read_key(fd, name);
    close(fd);
    return key;
}

int Modbus_Identity_Ensure(unsigned role, const char *certificate_path)
{
    const char *selected = Modbus_Identity_Backend();
    char name[NAME_MAX + 1], temporary[64] = {0};
    unsigned char random[16];
    struct stat st;
    EVP_PKEY_CTX *ctx = NULL;
    EVP_PKEY *key = NULL;
    FILE *file = NULL;
    int directory, fd = -1, ok = 0;
    if (!selected || role > 1) return 0;
#if MODBUS_WITH_TEE
    if (!strcmp(selected, "tee")) return Modbus_TEE_Ensure(role);
#endif
    directory = key_directory(certificate_path, name);
    if (directory < 0) return 0;
    if (fstatat(directory, name, &st, AT_SYMLINK_NOFOLLOW) == 0) {
        key = read_key(directory, name);
        ok = key != NULL;
        goto out;
    }
    if (errno != ENOENT) goto out;
    ctx = EVP_PKEY_CTX_new_id(EVP_PKEY_RSA, NULL);
    if (!ctx || EVP_PKEY_keygen_init(ctx) <= 0 ||
        EVP_PKEY_CTX_set_rsa_keygen_bits(ctx, 3072) <= 0 || EVP_PKEY_keygen(ctx, &key) <= 0 ||
        RAND_bytes(random, sizeof(random)) != 1) goto out;
    strcpy(temporary, ".modbus-key-");
    for (size_t i = 0; i < sizeof(random); ++i) sprintf(temporary + 12 + i * 2, "%02x", random[i]);
    fd = openat(directory, temporary, O_CREAT | O_EXCL | O_WRONLY | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (fd < 0) goto out;
    file = fdopen(fd, "w");
    if (!file) goto out;
    fd = -1; /* file owns the descriptor */
    if (PEM_write_PKCS8PrivateKey(file, key, NULL, NULL, 0, NULL, NULL) != 1 ||
        fflush(file) || fsync(fileno(file))) goto out;
    if (fclose(file)) { file = NULL; goto out; }
    file = NULL;
    /* Atomic no-replace publication: never overwrite an existing identity. */
    if (linkat(directory, temporary, directory, name, 0)) goto out;
    if (unlinkat(directory, temporary, 0)) goto out;
    temporary[0] = '\0';
    if (fsync(directory)) goto out;
    ok = 1;
out:
    if (file) fclose(file);
    if (fd >= 0) close(fd);
    if (temporary[0]) unlinkat(directory, temporary, 0);
    close(directory);
    EVP_PKEY_free(key);
    EVP_PKEY_CTX_free(ctx);
    return ok;
}

int Modbus_Identity_Check(X509 *certificate, unsigned role, const char *certificate_path)
{
    static const unsigned char challenge[] = "Modbus file identity self-test v1";
    const char *selected = Modbus_Identity_Backend();
    EVP_PKEY *key = NULL, *public_key = NULL;
    EVP_MD_CTX *sign = NULL, *verify = NULL;
    unsigned char signature[384];
    size_t length = sizeof(signature);
    int ok = 0;
    if (!selected || !certificate || role > 1) return 0;
#if MODBUS_WITH_TEE
    if (!strcmp(selected, "tee")) return Modbus_TEE_Check(certificate, role);
#endif
    key = Modbus_Identity_Key(role, certificate_path);
    public_key = X509_get_pubkey(certificate);
    sign = EVP_MD_CTX_new(); verify = EVP_MD_CTX_new();
    if (!key || !public_key || !sign || !verify || X509_check_private_key(certificate, key) != 1) goto out;
    ok = EVP_DigestSignInit(sign, NULL, EVP_sha256(), NULL, key) == 1 &&
        EVP_DigestSign(sign, signature, &length, challenge, sizeof(challenge) - 1) == 1 &&
        EVP_DigestVerifyInit(verify, NULL, EVP_sha256(), NULL, public_key) == 1 &&
        EVP_DigestVerify(verify, signature, length, challenge, sizeof(challenge) - 1) == 1;
out:
    EVP_MD_CTX_free(sign); EVP_MD_CTX_free(verify);
    EVP_PKEY_free(key); EVP_PKEY_free(public_key);
    return ok;
}
