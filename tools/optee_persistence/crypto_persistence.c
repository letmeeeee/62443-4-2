/* SPDX-License-Identifier: BSD-2-Clause */
/* Client for the unchanged vendor crypto_ta ABI (commands 0 through 6). */
#include <tee_client_api.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "crypto_ta.h"

static int invoke(TEEC_Session *session, uint32_t command, TEEC_Operation *op)
{
    uint32_t origin = 0;
    TEEC_Result result = TEEC_InvokeCommand(session, command, op, &origin);
    fprintf(stderr, "stage=InvokeCommand command=%u result=0x%08x origin=0x%08x\n",
            command, result, origin);
    return result == TEEC_SUCCESS;
}

static int verify_key(TEEC_Session *session)
{
    static const char message[] = "vendor crypto_ta persistence probe v1";
    unsigned char n[384], e[8], signature[384];
    size_t n_len, e_len, signature_len;
    TEEC_Operation op = {0};

    op.paramTypes = TEEC_PARAM_TYPES(TEEC_MEMREF_TEMP_OUTPUT,
                                    TEEC_MEMREF_TEMP_OUTPUT, TEEC_NONE, TEEC_NONE);
    op.params[0].tmpref.buffer = n;
    op.params[0].tmpref.size = sizeof(n);
    op.params[1].tmpref.buffer = e;
    op.params[1].tmpref.size = sizeof(e);
    if (!invoke(session, CRYPTO_GET_RSA_3072_PUB_KEY, &op)) return 0;
    n_len = op.params[0].tmpref.size;
    e_len = op.params[1].tmpref.size;
    if (n_len != sizeof(n) || !e_len || e_len > sizeof(e)) {
        fprintf(stderr, "Invalid returned public key lengths: n=%zu e=%zu\n", n_len, e_len);
        return 0;
    }

    memset(&op, 0, sizeof(op));
    op.paramTypes = TEEC_PARAM_TYPES(TEEC_MEMREF_TEMP_INPUT,
                                    TEEC_MEMREF_TEMP_OUTPUT, TEEC_NONE, TEEC_NONE);
    /* The TA hashes the original message internally. */
    op.params[0].tmpref.buffer = (void *)message;
    op.params[0].tmpref.size = sizeof(message) - 1;
    op.params[1].tmpref.buffer = signature;
    op.params[1].tmpref.size = sizeof(signature);
    if (!invoke(session, CRYPTO_MAC_RSA_3072_KEY, &op)) return 0;
    signature_len = op.params[1].tmpref.size;
    if (signature_len != sizeof(signature)) {
        fprintf(stderr, "Invalid returned signature length: %zu\n", signature_len);
        return 0;
    }

    memset(&op, 0, sizeof(op));
    op.paramTypes = TEEC_PARAM_TYPES(TEEC_MEMREF_TEMP_INPUT,
                                    TEEC_MEMREF_TEMP_INPUT, TEEC_VALUE_OUTPUT, TEEC_NONE);
    op.params[0].tmpref.buffer = (void *)message;
    op.params[0].tmpref.size = sizeof(message) - 1;
    op.params[1].tmpref.buffer = signature;
    op.params[1].tmpref.size = signature_len;
    if (!invoke(session, CRYPTO_VERIFY_RSA_3072_KEY, &op)) return 0;
    if (op.params[2].value.a != 0) {
        fprintf(stderr, "RSA signature verification failed: status=%u\n", op.params[2].value.a);
        return 0;
    }

    /* Stable public data only. PSS signatures vary and must not be compared. */
    printf("n=");
    for (size_t i = 0; i < n_len; ++i) printf("%02x", n[i]);
    printf("\ne=");
    for (size_t i = 0; i < e_len; ++i) printf("%02x", e[i]);
    printf("\n");
    if (fflush(stdout) != 0) {
        perror("public key output");
        return 0;
    }
    fprintf(stderr, "PASS: public key read, private key signing and verification succeeded\n");
    return 1;
}

int main(int argc, char **argv)
{
    static const TEEC_UUID uuid = TA_CRYPTO_UUID;
    TEEC_Context context = {0};
    TEEC_Session session = {0};
    TEEC_Operation op = {0};
    TEEC_Result result;
    uint32_t origin = 0;
    int ok = 0;

    if (argc != 2 || (strcmp(argv[1], "init") && strcmp(argv[1], "check"))) {
        fprintf(stderr, "Usage: %s init|check\n"
                "init: ensure vendor RSA key exists, then check it\n"
                "check: read/sign/verify only; never create a key\n", argv[0]);
        return 2;
    }
    result = TEEC_InitializeContext(NULL, &context);
    fprintf(stderr, "stage=InitializeContext result=0x%08x\n", result);
    if (result != TEEC_SUCCESS) return 1;
    result = TEEC_OpenSession(&context, &session, &uuid, TEEC_LOGIN_PUBLIC,
                              NULL, NULL, &origin);
    fprintf(stderr, "stage=OpenSession result=0x%08x origin=0x%08x\n", result, origin);
    if (result != TEEC_SUCCESS) {
        TEEC_FinalizeContext(&context);
        return 1;
    }
    if (!strcmp(argv[1], "init")) {
        op.paramTypes = TEEC_PARAM_TYPES(TEEC_NONE, TEEC_NONE, TEEC_NONE, TEEC_NONE);
        if (!invoke(&session, CRYPTO_GEN_RSA_3072_KEY, &op)) goto out;
    }
    ok = verify_key(&session);
out:
    TEEC_CloseSession(&session);
    TEEC_FinalizeContext(&context);
    return ok ? 0 : 1;
}
