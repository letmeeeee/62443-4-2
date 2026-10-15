/* OpenSSL 1.1.1 EVP signing adapter for non-exportable OP-TEE RSA keys. */
#include "modbus_tee.h"
#include "crypto_ta.h"
#include <tee_client_api.h>
#include <openssl/engine.h>
#include <openssl/rsa.h>
#include <pthread.h>
#include <stdio.h>
#include <stdint.h>

static ENGINE *engine;
static EVP_PKEY_METHOD *method;
static RSA_METHOD *rsa_method;
static int role_index = -1;
static pthread_once_t once = PTHREAD_ONCE_INIT;

static int invoke(unsigned command, TEEC_Operation *op)
{
    TEEC_Context context;
    TEEC_Session session;
    static const TEEC_UUID uuid = TA_CRYPTO_UUID;
    TEEC_Result result;
    uint32_t origin = 0;
    result = TEEC_InitializeContext(NULL, &context);
    if (result != TEEC_SUCCESS) goto error;
    result = TEEC_OpenSession(&context, &session, &uuid, TEEC_LOGIN_PUBLIC,
                              NULL, NULL, &origin);
    if (result != TEEC_SUCCESS) { TEEC_FinalizeContext(&context); goto error; }
    result = TEEC_InvokeCommand(&session, command, op, &origin);
    TEEC_CloseSession(&session);
    TEEC_FinalizeContext(&context);
    if (result == TEEC_SUCCESS) return 1;
error:
    fprintf(stderr, "Modbus TA command=%u result=0x%08x origin=0x%08x\n",
            command, result, origin);
    return 0;
}

int Modbus_TEE_Ensure(unsigned role)
{
    TEEC_Operation op = {0};
    if (role > CRYPTO_MODBUS_SLAVE) return 0;
    op.paramTypes = TEEC_PARAM_TYPES(TEEC_VALUE_INPUT, TEEC_NONE, TEEC_NONE, TEEC_NONE);
    op.params[0].value.a = role;
    return invoke(CRYPTO_MODBUS_ENSURE_RSA, &op);
}

static int sign_digest(EVP_PKEY_CTX *ctx, unsigned char *sig, size_t *siglen,
                       const unsigned char *digest, size_t digest_len)
{
    const EVP_MD *md = NULL, *mgf = NULL;
    RSA *rsa = EVP_PKEY_get0_RSA(EVP_PKEY_CTX_get0_pkey(ctx));
    int padding = 0, salt = 0, nid;
    uint32_t scheme;
    TEEC_Operation op = {0};
    uintptr_t encoded_role;
    if (!rsa || !siglen) return 0;
    encoded_role = (uintptr_t)RSA_get_ex_data(rsa, role_index);
    if (encoded_role < 1 || encoded_role > 2) return 0;
    if (!sig) { *siglen = 384; return 1; }
    if (*siglen < 384 || EVP_PKEY_CTX_get_signature_md(ctx, &md) <= 0 || !md ||
        EVP_PKEY_CTX_get_rsa_padding(ctx, &padding) <= 0) return 0;
    nid = EVP_MD_type(md);
    if (nid == NID_sha256) scheme = CRYPTO_RSA_PKCS1_SHA256;
    else if (nid == NID_sha384) scheme = CRYPTO_RSA_PKCS1_SHA384;
    else if (nid == NID_sha512) scheme = CRYPTO_RSA_PKCS1_SHA512;
    else return 0;
    if (digest_len != (size_t)EVP_MD_size(md)) return 0;
    if (padding == RSA_PKCS1_PSS_PADDING) {
        if (EVP_PKEY_CTX_get_rsa_mgf1_md(ctx, &mgf) <= 0 || !mgf ||
            EVP_MD_type(mgf) != nid || EVP_PKEY_CTX_get_rsa_pss_saltlen(ctx, &salt) <= 0 ||
            (salt != RSA_PSS_SALTLEN_DIGEST && salt != (int)digest_len)) return 0;
        scheme += 3;
    } else if (padding != RSA_PKCS1_PADDING) return 0;
    op.paramTypes = TEEC_PARAM_TYPES(TEEC_MEMREF_TEMP_INPUT, TEEC_MEMREF_TEMP_OUTPUT,
                                    TEEC_VALUE_INPUT, TEEC_NONE);
    op.params[0].tmpref.buffer = (void *)digest;
    op.params[0].tmpref.size = digest_len;
    op.params[1].tmpref.buffer = sig;
    op.params[1].tmpref.size = *siglen;
    op.params[2].value.a = (uint32_t)(encoded_role - 1);
    op.params[2].value.b = scheme;
    if (!invoke(CRYPTO_MODBUS_SIGN_DIGEST, &op) || op.params[1].tmpref.size != 384) return 0;
    *siglen = op.params[1].tmpref.size;
    return 1;
}

static int methods(ENGINE *e, EVP_PKEY_METHOD **out, const int **nids, int nid)
{
    static const int supported[] = {EVP_PKEY_RSA};
    (void)e;
    if (!out) { *nids = supported; return 1; }
    if (nid != EVP_PKEY_RSA) { *out = NULL; return 0; }
    *out = method;
    return 1;
}

static int deny_private(int len, const unsigned char *from, unsigned char *to,
                        RSA *rsa, int padding)
{
    (void)len; (void)from; (void)to; (void)rsa; (void)padding;
    return -1; /* No RSA decryption, raw signing, or software private fallback. */
}

static void initialize(void)
{
    ENGINE *candidate = NULL;
    role_index = RSA_get_ex_new_index(0, NULL, NULL, NULL, NULL);
    method = EVP_PKEY_meth_new(EVP_PKEY_RSA, 0);
    rsa_method = RSA_meth_dup(RSA_get_default_method());
    candidate = ENGINE_new();
    if (role_index < 0 || !method || !rsa_method || !candidate) goto fail;
    EVP_PKEY_meth_copy(method, EVP_PKEY_meth_find(EVP_PKEY_RSA));
    EVP_PKEY_meth_set_sign(method, NULL, sign_digest);
    RSA_meth_set_flags(rsa_method, RSA_meth_get_flags(rsa_method) | RSA_FLAG_EXT_PKEY);
    RSA_meth_set_priv_enc(rsa_method, deny_private);
    RSA_meth_set_priv_dec(rsa_method, deny_private);
    if (!ENGINE_set_id(candidate, "modbus-optee") ||
        !ENGINE_set_name(candidate, "Modbus OP-TEE RSA signer") ||
        !ENGINE_set_RSA(candidate, rsa_method) ||
        !ENGINE_set_pkey_meths(candidate, methods) || !ENGINE_init(candidate)) goto fail;
    engine = candidate;
    return;
fail:
    ENGINE_free(candidate);
    EVP_PKEY_meth_free(method); method = NULL;
    RSA_meth_free(rsa_method); rsa_method = NULL;
}

EVP_PKEY *Modbus_TEE_Key(unsigned role)
{
    unsigned char modulus[384], exponent[8];
    TEEC_Operation op = {0};
    RSA *rsa = NULL;
    EVP_PKEY *key = NULL;
    BIGNUM *n = NULL, *e = NULL;
    if (role > CRYPTO_MODBUS_SLAVE) return NULL;
    pthread_once(&once, initialize);
    if (!engine) return NULL;
    op.paramTypes = TEEC_PARAM_TYPES(TEEC_MEMREF_TEMP_OUTPUT, TEEC_MEMREF_TEMP_OUTPUT,
                                    TEEC_VALUE_INPUT, TEEC_NONE);
    op.params[0].tmpref.buffer = modulus; op.params[0].tmpref.size = sizeof(modulus);
    op.params[1].tmpref.buffer = exponent; op.params[1].tmpref.size = sizeof(exponent);
    op.params[2].value.a = role;
    if (!invoke(CRYPTO_MODBUS_GET_PUBLIC, &op) || op.params[0].tmpref.size != sizeof(modulus) ||
        !op.params[1].tmpref.size || op.params[1].tmpref.size > sizeof(exponent)) return NULL;
    n = BN_bin2bn(modulus, (int)op.params[0].tmpref.size, NULL);
    e = BN_bin2bn(exponent, (int)op.params[1].tmpref.size, NULL);
    rsa = RSA_new_method(engine); key = EVP_PKEY_new();
    if (!n || !e || !rsa || !key || !RSA_set0_key(rsa, n, e, NULL)) goto fail;
    n = e = NULL;
    if (!RSA_set_ex_data(rsa, role_index, (void *)(uintptr_t)(role + 1)) ||
        !EVP_PKEY_assign_RSA(key, rsa)) goto fail;
    rsa = NULL;
    if (!EVP_PKEY_set1_engine(key, engine)) goto fail;
    return key;
fail:
    BN_free(n); BN_free(e); RSA_free(rsa); EVP_PKEY_free(key);
    return NULL;
}

int Modbus_TEE_Check(X509 *certificate, unsigned role)
{
    static const unsigned char challenge[] = "Modbus TA identity self-test v1";
    unsigned char digest[32], signature[384];
    unsigned int length = 0;
    size_t siglen = sizeof(signature);
    EVP_PKEY *key = Modbus_TEE_Key(role), *public_key = X509_get_pubkey(certificate);
    EVP_PKEY_CTX *ctx = NULL;
    TEEC_Operation op = {0};
    int ok = 0;
    if (!key || !public_key || EVP_PKEY_cmp(key, public_key) != 1) goto out;
    ctx = EVP_PKEY_CTX_new(key, NULL);
    if (!ctx || EVP_Digest(challenge, sizeof(challenge), digest, &length, EVP_sha256(), NULL) != 1 ||
        EVP_PKEY_sign_init(ctx) <= 0 || EVP_PKEY_CTX_set_rsa_padding(ctx, RSA_PKCS1_PADDING) <= 0 ||
        EVP_PKEY_CTX_set_signature_md(ctx, EVP_sha256()) <= 0 ||
        EVP_PKEY_sign(ctx, signature, &siglen, digest, length) <= 0) goto out;
    op.paramTypes = TEEC_PARAM_TYPES(TEEC_MEMREF_TEMP_INPUT, TEEC_MEMREF_TEMP_INPUT,
                                    TEEC_VALUE_INOUT, TEEC_NONE);
    op.params[0].tmpref.buffer = digest; op.params[0].tmpref.size = length;
    op.params[1].tmpref.buffer = signature; op.params[1].tmpref.size = siglen;
    op.params[2].value.a = role; op.params[2].value.b = CRYPTO_RSA_PKCS1_SHA256;
    ok = invoke(CRYPTO_MODBUS_VERIFY_DIGEST, &op) && op.params[2].value.a == 0;
out:
    EVP_PKEY_CTX_free(ctx); EVP_PKEY_free(key); EVP_PKEY_free(public_key);
    return ok;
}
