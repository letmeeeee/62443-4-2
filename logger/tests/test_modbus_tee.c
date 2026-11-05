/* Software TEEC substitute: tests TLS integration, never device storage. */
#include "modbus_tee.h"
#include "crypto_ta.h"
#include <tee_client_api.h>
#include <openssl/rsa.h>
#include <openssl/ssl.h>
#include <openssl/err.h>
#include <assert.h>
#include <string.h>
#include <stdio.h>
#include <openssl/pem.h>
#include <openssl/x509v3.h>
#include <stdlib.h>

static EVP_PKEY *software[2];
static unsigned signatures, verifications;
static int fail_ta;
TEEC_Result TEEC_InitializeContext(const char *name, TEEC_Context *ctx)
{ (void)name; memset(ctx, 0, sizeof(*ctx)); return 0; }
void TEEC_FinalizeContext(TEEC_Context *ctx) { (void)ctx; }
TEEC_Result TEEC_OpenSession(TEEC_Context *ctx, TEEC_Session *session,
    const TEEC_UUID *uuid, uint32_t login, const void *connection,
    TEEC_Operation *op, uint32_t *origin)
{
    static const TEEC_UUID expected = TA_CRYPTO_UUID;
    (void)ctx; (void)session; (void)connection; (void)op;
    assert(!memcmp(uuid, &expected, sizeof(expected))); assert(login == TEEC_LOGIN_PUBLIC);
    *origin = 4; return 0;
}
void TEEC_CloseSession(TEEC_Session *session) { (void)session; }
TEEC_Result TEEC_InvokeCommand(TEEC_Session *session, uint32_t command,
    TEEC_Operation *op, uint32_t *origin)
{
    (void)session; *origin = 4;
    if (fail_ta) return 0xffff0008;
    unsigned role = command == CRYPTO_MODBUS_ENSURE_RSA ? op->params[0].value.a : op->params[2].value.a;
    assert(role < 2);
    const char *store = getenv("MODBUS_TEE_TEST_STORE");
    char path[1024];
    if (store) {
        assert(snprintf(path, sizeof(path), "%s/%u.pem", store, role) < (int)sizeof(path));
        if (!software[role]) {
            FILE *file = fopen(path, "r");
            if (file) { software[role] = PEM_read_PrivateKey(file, NULL, NULL, NULL); fclose(file); }
        }
    }
    if (command == CRYPTO_MODBUS_ENSURE_RSA) {
        assert(op->paramTypes == TEEC_PARAM_TYPES(TEEC_VALUE_INPUT, 0, 0, 0));
        if (!software[role]) {
            EVP_PKEY_CTX *ctx = EVP_PKEY_CTX_new_id(EVP_PKEY_RSA, NULL);
            assert(ctx && EVP_PKEY_keygen_init(ctx) > 0);
            assert(EVP_PKEY_CTX_set_rsa_keygen_bits(ctx, 3072) > 0);
            assert(EVP_PKEY_keygen(ctx, &software[role]) > 0); EVP_PKEY_CTX_free(ctx);
            if (store) {
                FILE *file = fopen(path, "wx"); assert(file);
                assert(PEM_write_PrivateKey(file, software[role], NULL, NULL, 0, NULL, NULL)); fclose(file);
            }
        }
        return 0;
    }
    if (!software[role]) return TEEC_ERROR_ITEM_NOT_FOUND;
    if (command == CRYPTO_MODBUS_GET_PUBLIC) {
        const BIGNUM *n, *e;
        assert(op->paramTypes == TEEC_PARAM_TYPES(TEEC_MEMREF_TEMP_OUTPUT, TEEC_MEMREF_TEMP_OUTPUT, TEEC_VALUE_INPUT, 0));
        RSA_get0_key(EVP_PKEY_get0_RSA(software[role]), &n, &e, NULL);
        op->params[0].tmpref.size = BN_bn2bin(n, op->params[0].tmpref.buffer);
        op->params[1].tmpref.size = BN_bn2bin(e, op->params[1].tmpref.buffer);
        return 0;
    }
    int verify = command == CRYPTO_MODBUS_VERIFY_DIGEST;
    assert(command == CRYPTO_MODBUS_SIGN_DIGEST || verify);
    assert(op->paramTypes == TEEC_PARAM_TYPES(TEEC_MEMREF_TEMP_INPUT,
        verify ? TEEC_MEMREF_TEMP_INPUT : TEEC_MEMREF_TEMP_OUTPUT,
        verify ? TEEC_VALUE_INOUT : TEEC_VALUE_INPUT, 0));
    unsigned scheme = op->params[2].value.b;
    assert(scheme >= 1 && scheme <= 6);
    const EVP_MD *md = ((scheme - 1) % 3 == 0) ? EVP_sha256() :
        ((scheme - 1) % 3 == 1) ? EVP_sha384() : EVP_sha512();
    assert(op->params[0].tmpref.size == (size_t)EVP_MD_size(md));
    EVP_PKEY_CTX *ctx = EVP_PKEY_CTX_new(software[role], NULL);
    assert(ctx && (verify ? EVP_PKEY_verify_init(ctx) : EVP_PKEY_sign_init(ctx)) > 0);
    assert(EVP_PKEY_CTX_set_rsa_padding(ctx, scheme > 3 ? RSA_PKCS1_PSS_PADDING : RSA_PKCS1_PADDING) > 0);
    assert(EVP_PKEY_CTX_set_signature_md(ctx, md) > 0);
    if (scheme > 3) assert(EVP_PKEY_CTX_set_rsa_pss_saltlen(ctx, EVP_MD_size(md)) > 0);
    if (verify) {
        int valid = EVP_PKEY_verify(ctx, op->params[1].tmpref.buffer, op->params[1].tmpref.size,
            op->params[0].tmpref.buffer, op->params[0].tmpref.size);
        assert(valid >= 0); op->params[2].value.a = valid == 1 ? 0 : 1; verifications++;
    } else {
        assert(EVP_PKEY_sign(ctx, op->params[1].tmpref.buffer, &op->params[1].tmpref.size,
            op->params[0].tmpref.buffer, op->params[0].tmpref.size) > 0); signatures++;
    }
    EVP_PKEY_CTX_free(ctx); return 0;
}

#ifndef MODBUS_TEE_STUB_ONLY
static EVP_PKEY *ca_key;
static X509 *ca_certificate;
static void add_extension(X509 *cert, int nid, const char *value)
{
    X509_EXTENSION *extension = X509V3_EXT_conf_nid(NULL, NULL, nid, (char *)value);
    assert(extension && X509_add_ext(cert, extension, -1));
    X509_EXTENSION_free(extension);
}

static void create_test_ca(void)
{
    EVP_PKEY_CTX *ctx = EVP_PKEY_CTX_new_id(EVP_PKEY_RSA, NULL);
    assert(ctx && EVP_PKEY_keygen_init(ctx) > 0 && EVP_PKEY_CTX_set_rsa_keygen_bits(ctx, 2048) > 0);
    assert(EVP_PKEY_keygen(ctx, &ca_key) > 0); EVP_PKEY_CTX_free(ctx);
    ca_certificate = X509_new(); assert(ca_certificate);
    assert(X509_set_version(ca_certificate, 2));
    ASN1_INTEGER_set(X509_get_serialNumber(ca_certificate), 1);
    assert(X509_gmtime_adj(X509_getm_notBefore(ca_certificate), 0));
    assert(X509_gmtime_adj(X509_getm_notAfter(ca_certificate), 86400));
    assert(X509_NAME_add_entry_by_txt(X509_get_subject_name(ca_certificate), "CN", MBSTRING_ASC,
        (const unsigned char *)"offline-test-CA", -1, -1, 0));
    assert(X509_set_issuer_name(ca_certificate, X509_get_subject_name(ca_certificate)));
    assert(X509_set_pubkey(ca_certificate, ca_key));
    add_extension(ca_certificate, NID_basic_constraints, "critical,CA:TRUE");
    add_extension(ca_certificate, NID_key_usage, "critical,keyCertSign,cRLSign");
    assert(X509_sign(ca_certificate, ca_key, EVP_sha256()) > 0);
}

static X509 *certificate(EVP_PKEY *key, const char *cn)
{
    X509 *cert = X509_new(); assert(cert);
    assert(X509_set_version(cert, 2)); ASN1_INTEGER_set(X509_get_serialNumber(cert), 1);
    assert(X509_gmtime_adj(X509_getm_notBefore(cert), 0));
    assert(X509_gmtime_adj(X509_getm_notAfter(cert), 86400));
    assert(X509_NAME_add_entry_by_txt(X509_get_subject_name(cert), "CN", MBSTRING_ASC,
        (const unsigned char *)cn, -1, -1, 0));
    assert(X509_set_issuer_name(cert, X509_get_subject_name(ca_certificate)));
    add_extension(cert, NID_basic_constraints, "critical,CA:FALSE");
    add_extension(cert, NID_key_usage, "critical,digitalSignature,keyEncipherment");
    add_extension(cert, NID_ext_key_usage, !strcmp(cn, "slave") ? "serverAuth" : "clientAuth");
    assert(X509_set_pubkey(cert, key)); assert(X509_sign(cert, ca_key, EVP_sha256()) > 0);
    assert(X509_verify(cert, ca_key) == 1);
    return cert;
}

static void handshake(int version, X509 *master, EVP_PKEY *mk, X509 *slave, EVP_PKEY *sk)
{
    SSL_CTX *client = SSL_CTX_new(TLS_client_method()), *server = SSL_CTX_new(TLS_server_method());
    assert(client && server);
    assert(SSL_CTX_set_min_proto_version(client, version)); assert(SSL_CTX_set_max_proto_version(client, version));
    assert(SSL_CTX_set_min_proto_version(server, version)); assert(SSL_CTX_set_max_proto_version(server, version));
    assert(SSL_CTX_use_certificate(client, master)); assert(SSL_CTX_use_PrivateKey(client, mk));
    assert(SSL_CTX_use_certificate(server, slave)); assert(SSL_CTX_use_PrivateKey(server, sk));
    assert(X509_STORE_add_cert(SSL_CTX_get_cert_store(server), ca_certificate));
    assert(X509_STORE_add_cert(SSL_CTX_get_cert_store(client), ca_certificate));
    SSL_CTX_set_verify(server, SSL_VERIFY_PEER | SSL_VERIFY_FAIL_IF_NO_PEER_CERT, NULL);
    SSL_CTX_set_verify(client, SSL_VERIFY_PEER, NULL);
    assert(SSL_CTX_set_cipher_list(client, "ECDHE-RSA-AES128-GCM-SHA256"));
    assert(SSL_CTX_set_cipher_list(server, "ECDHE-RSA-AES128-GCM-SHA256"));
    SSL *c = SSL_new(client), *s = SSL_new(server); BIO *cb, *sb;
    assert(c && s && BIO_new_bio_pair(&cb, 0, &sb, 0));
    SSL_set_bio(c, cb, cb); SSL_set_bio(s, sb, sb);
    SSL_set_connect_state(c); SSL_set_accept_state(s);
    unsigned before = signatures;
    for (unsigned i = 0; i < 100 && (!SSL_is_init_finished(c) || !SSL_is_init_finished(s)); i++) {
        int cr = SSL_do_handshake(c), sr = SSL_do_handshake(s);
        int ce = SSL_get_error(c, cr), se = SSL_get_error(s, sr);
        if ((cr != 1 && ce != SSL_ERROR_WANT_READ && ce != SSL_ERROR_WANT_WRITE) ||
            (sr != 1 && se != SSL_ERROR_WANT_READ && se != SSL_ERROR_WANT_WRITE)) {
            ERR_print_errors_fp(stderr); assert(0);
        }
    }
    assert(SSL_is_init_finished(c) && SSL_is_init_finished(s));
    assert(signatures >= before + 2);
    const char message[] = "Modbus application data"; char buffer[64];
    assert(SSL_write(c, message, sizeof(message)) == sizeof(message));
    assert(SSL_read(s, buffer, sizeof(buffer)) == sizeof(message));
    assert(!memcmp(message, buffer, sizeof(message)));
    SSL_free(c); SSL_free(s); SSL_CTX_free(client); SSL_CTX_free(server);
}

int main(void)
{
    create_test_ca();
    assert(Modbus_TEE_Ensure(0) && Modbus_TEE_Ensure(1));
    EVP_PKEY *mk = Modbus_TEE_Key(0), *sk = Modbus_TEE_Key(1); assert(mk && sk);
    const BIGNUM *d; RSA_get0_key(EVP_PKEY_get0_RSA(mk), NULL, NULL, &d); assert(!d);
    assert(EVP_PKEY_cmp(mk, sk) != 1);
    X509 *master = certificate(mk, "master"), *slave = certificate(sk, "slave");
    assert(Modbus_TEE_Check(master, 0)); assert(Modbus_TEE_Check(slave, 1));
    assert(!Modbus_TEE_Check(master, 1)); assert(verifications >= 2);
    /* Exercise each negotiated digest/padding combination without rehashing. */
    for (unsigned scheme = 1; scheme <= 6; scheme++) {
        const EVP_MD *md = (scheme - 1) % 3 == 0 ? EVP_sha256() :
            (scheme - 1) % 3 == 1 ? EVP_sha384() : EVP_sha512();
        unsigned char digest[64], sig[384]; unsigned int dlen;
        size_t slen = sizeof(sig);
        EVP_PKEY_CTX *ctx = EVP_PKEY_CTX_new(mk, NULL);
        assert(ctx && EVP_PKEY_sign_init(ctx) > 0);
        assert(EVP_PKEY_CTX_set_signature_md(ctx, md) > 0);
        assert(EVP_PKEY_CTX_set_rsa_padding(ctx, scheme > 3 ? RSA_PKCS1_PSS_PADDING : RSA_PKCS1_PADDING) > 0);
        if (scheme > 3) assert(EVP_PKEY_CTX_set_rsa_pss_saltlen(ctx, RSA_PSS_SALTLEN_DIGEST) > 0);
        assert(EVP_Digest("challenge", 9, digest, &dlen, md, NULL));
        assert(EVP_PKEY_sign(ctx, sig, &slen, digest, dlen) > 0 && slen == 384);
        EVP_PKEY_CTX *verify = EVP_PKEY_CTX_new(software[0], NULL);
        assert(verify && EVP_PKEY_verify_init(verify) > 0);
        assert(EVP_PKEY_CTX_set_signature_md(verify, md) > 0);
        assert(EVP_PKEY_CTX_set_rsa_padding(verify, scheme > 3 ? RSA_PKCS1_PSS_PADDING : RSA_PKCS1_PADDING) > 0);
        if (scheme > 3) assert(EVP_PKEY_CTX_set_rsa_pss_saltlen(verify, RSA_PSS_SALTLEN_DIGEST) > 0);
        assert(EVP_PKEY_verify(verify, sig, slen, digest, dlen) == 1);
        sig[0] ^= 1; assert(EVP_PKEY_verify(verify, sig, slen, digest, dlen) == 0);
        fail_ta = 1; slen = sizeof(sig); assert(EVP_PKEY_sign(ctx, sig, &slen, digest, dlen) <= 0); fail_ta = 0;
        EVP_PKEY_CTX_free(ctx); EVP_PKEY_CTX_free(verify);
    }
    ERR_clear_error();
    handshake(TLS1_2_VERSION, master, mk, slave, sk);
    handshake(TLS1_3_VERSION, master, mk, slave, sk);
    fail_ta = 1; assert(!Modbus_TEE_Key(0)); assert(!Modbus_TEE_Check(master, 0));
    X509_free(master); X509_free(slave); EVP_PKEY_free(mk); EVP_PKEY_free(sk);
    X509_free(ca_certificate); EVP_PKEY_free(ca_key);
    puts("PASS: separate TA roles, no private export, matching/mismatched identity, all six signature schemes, TLS1.2/1.3 mTLS, fail closed");
    return 0;
}
#endif
