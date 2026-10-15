#include "modbus_tee.h"
#include <openssl/pem.h>
#include <openssl/rand.h>
#include <openssl/x509v3.h>
#include <openssl/err.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int extension(X509 *cert, int nid, const char *value)
{
    X509V3_CTX ctx;
    X509_EXTENSION *ext;
    X509V3_set_ctx(&ctx, cert, cert, NULL, NULL, 0);
    ext = X509V3_EXT_conf_nid(NULL, &ctx, nid, (char *)value);
    if (!ext) return 0;
    int ok = X509_add_ext(cert, ext, -1);
    X509_EXTENSION_free(ext);
    return ok;
}

int main(int argc, char **argv)
{
    unsigned role;
    EVP_PKEY *key = NULL;
    X509 *cert = NULL;
    BIO *bio = NULL;
    int ok = 0;
    if (argc < 3 || (strcmp(argv[2], "master") && strcmp(argv[2], "slave"))) goto out;
    role = !strcmp(argv[2], "slave");
    if (!strcmp(argv[1], "ensure") && argc == 3) {
        ok = Modbus_TEE_Ensure(role);
        goto out;
    }
    if (!strcmp(argv[1], "check") && argc == 4) {
        bio = BIO_new_file(argv[3], "r");
        if (bio) cert = PEM_read_bio_X509(bio, NULL, NULL, NULL);
        ok = cert && Modbus_TEE_Check(cert, role);
        goto out;
    }
    if (strcmp(argv[1], "cert") || argc != 6) goto out;
    char *end = NULL;
    long days = strtol(argv[4], &end, 10);
    if (!end || *end || days < 1 || days > 3650 || !*argv[3] || strlen(argv[3]) > 64) goto out;
    if (!Modbus_TEE_Ensure(role)) goto out;
    key = Modbus_TEE_Key(role); cert = X509_new();
    unsigned char random[16];
    BIGNUM *serial = NULL;
    if (!key || !cert || RAND_bytes(random, sizeof(random)) != 1) goto out;
    random[0] &= 0x7f; random[0] |= 1;
    serial = BN_bin2bn(random, sizeof(random), NULL);
    if (!serial) goto out;
    int serial_ok = BN_to_ASN1_INTEGER(serial, X509_get_serialNumber(cert)) != NULL;
    BN_free(serial);
    X509_NAME *name = X509_get_subject_name(cert);
    if (!serial_ok || !X509_set_version(cert, 2) ||
        !X509_gmtime_adj(X509_getm_notBefore(cert), 0) ||
        !X509_gmtime_adj(X509_getm_notAfter(cert), days * 86400) ||
        !X509_NAME_add_entry_by_txt(name, "CN", MBSTRING_ASC,
            (const unsigned char *)argv[3], -1, -1, 0) ||
        !X509_set_issuer_name(cert, name) || !X509_set_pubkey(cert, key) ||
        !extension(cert, NID_basic_constraints, "critical,CA:FALSE") ||
        !extension(cert, NID_ext_key_usage, role ? "serverAuth" : "clientAuth") ||
        !extension(cert, NID_subject_key_identifier, "hash") ||
        (*argv[5] && !extension(cert, NID_subject_alt_name, argv[5])) ||
        !X509_sign(cert, key, EVP_sha256()) || !Modbus_TEE_Check(cert, role)) goto out;
    ok = PEM_write_X509(stdout, cert);
out:
    if (!ok) {
        fprintf(stderr, "Modbus TA identity failed. usage: %s ensure ROLE | check ROLE CERT | cert ROLE CN DAYS SAN\n", argv[0]);
        ERR_print_errors_fp(stderr);
    }
    BIO_free(bio); X509_free(cert); EVP_PKEY_free(key);
    return ok ? 0 : 1;
}
