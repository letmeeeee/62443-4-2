#include "modbus_identity.h"
#include <openssl/pem.h>
#include <openssl/rand.h>
#include <openssl/x509v3.h>
#include <openssl/err.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int csr(unsigned role, const char *certificate_path, const char *name, const char *sans, int ensure)
{
    EVP_PKEY *key = NULL;
    X509_REQ *request = NULL;
    STACK_OF(X509_EXTENSION) *extensions = NULL;
    X509V3_CTX context;
    int ok = 0;
    if (!*name || strlen(name) > 64 || (ensure && !Modbus_Identity_Ensure(role, certificate_path))) goto out;
    key = Modbus_Identity_Key(role, certificate_path);
    request = X509_REQ_new();
    extensions = sk_X509_EXTENSION_new_null();
    if (!key || !request || !extensions || !X509_REQ_set_version(request, 0L) ||
        !X509_NAME_add_entry_by_txt(X509_REQ_get_subject_name(request), "CN", MBSTRING_ASC,
            (const unsigned char *)name, -1, -1, 0) || !X509_REQ_set_pubkey(request, key)) goto out;
    X509V3_set_ctx(&context, NULL, NULL, request, NULL, 0);
    int nids[] = {NID_basic_constraints, NID_key_usage, NID_ext_key_usage, NID_subject_alt_name};
    const char *values[] = {"critical,CA:FALSE", "critical,digitalSignature,keyEncipherment",
                          role ? "serverAuth" : "clientAuth", sans};
    for (unsigned i = 0; i < sizeof(nids) / sizeof(nids[0]); i++) {
        if (!*values[i]) continue;
        X509_EXTENSION *item = X509V3_EXT_conf_nid(NULL, &context, nids[i], (char *)values[i]);
        if (!item) goto out;
        if (!sk_X509_EXTENSION_push(extensions, item)) { X509_EXTENSION_free(item); goto out; }
    }
    if (!X509_REQ_add_extensions(request, extensions) || !X509_REQ_sign(request, key, EVP_sha256())) goto out;
    EVP_PKEY *public_key = X509_REQ_get_pubkey(request);
    ok = public_key && X509_REQ_verify(request, public_key) == 1;
    EVP_PKEY_free(public_key);
    if (ok) ok = PEM_write_X509_REQ(stdout, request);
out:
    sk_X509_EXTENSION_pop_free(extensions, X509_EXTENSION_free);
    X509_REQ_free(request); EVP_PKEY_free(key);
    return ok;
}

int main(int argc, char **argv)
{
    unsigned role;
    EVP_PKEY *key = NULL;
    X509 *cert = NULL;
    BIO *bio = NULL;
    int ok = 0;
    const char *directory = "/etc/ems/modbus";
    char certificate_path[4096];
    if (argc >= 3 && !strcmp(argv[1], "--dir")) {
        directory = argv[2];
        argc -= 2; argv += 2;
    }
    if (!Modbus_Identity_Backend()) goto out;
    if (argc < 3 || (strcmp(argv[2], "master") && strcmp(argv[2], "slave"))) goto out;
    role = !strcmp(argv[2], "slave");
    int count = snprintf(certificate_path, sizeof(certificate_path), "%s/%s.crt", directory, argv[2]);
    if (count < 0 || count >= (int)sizeof(certificate_path)) goto out;
    if ((!strcmp(argv[1], "csr") || !strcmp(argv[1], "csr-existing")) && argc == 5) {
        ok = csr(role, certificate_path, argv[3], argv[4], !strcmp(argv[1], "csr"));
        goto out;
    }
    if (!strcmp(argv[1], "check-csr") && argc == 4) {
        X509_REQ *request = NULL;
        EVP_PKEY *public_key = NULL;
        bio = BIO_new_file(argv[3], "r");
        if (bio) request = PEM_read_bio_X509_REQ(bio, NULL, NULL, NULL);
        key = Modbus_Identity_Key(role, certificate_path);
        if (request) public_key = X509_REQ_get_pubkey(request);
        ok = key && public_key && EVP_PKEY_cmp(key, public_key) == 1 && X509_REQ_verify(request, public_key) == 1;
        EVP_PKEY_free(public_key); X509_REQ_free(request);
        goto out;
    }
    if (!strcmp(argv[1], "ensure") && argc == 3) {
        ok = Modbus_Identity_Ensure(role, certificate_path);
        goto out;
    }
    if (!strcmp(argv[1], "check") && argc == 4) {
        bio = BIO_new_file(argv[3], "r");
        if (bio) cert = PEM_read_bio_X509(bio, NULL, NULL, NULL);
        ok = cert && Modbus_Identity_Check(cert, role, certificate_path);
        goto out;
    }
out:
    if (!ok) {
        fprintf(stderr, "Modbus identity failed. usage: modbus_tee_identity [--dir DIR] ensure ROLE | check ROLE CERT | check-csr ROLE CSR | csr[-existing] ROLE CN SAN\n");
        ERR_print_errors_fp(stderr);
    }
    BIO_free(bio); X509_free(cert); EVP_PKEY_free(key);
    return ok ? 0 : 1;
}
