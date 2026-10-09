#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <tee_client_api.h>
#include "crypto_ta.h"

#define AES_CMAC_SIZE 16U
#define RSA_3072_SIZE 384U
#define RSA_EXPONENT_MAX_SIZE 8U
#define INPUT_MAX_SIZE ((1024U * 1024U) + RSA_3072_SIZE)

static const TEEC_UUID crypto_uuid = TA_CRYPTO_UUID;

struct tee_client {
    TEEC_Context context;
    TEEC_Session session;
    int context_open;
    int session_open;
};

static void close_client(struct tee_client *client)
{
    if (client->session_open)
        TEEC_CloseSession(&client->session);
    if (client->context_open)
        TEEC_FinalizeContext(&client->context);
}

static int open_client(struct tee_client *client)
{
    TEEC_Result result;
    uint32_t origin = 0;

    memset(client, 0, sizeof(*client));
    result = TEEC_InitializeContext(NULL, &client->context);
    if (result != TEEC_SUCCESS) {
        fprintf(stderr, "TEEC_InitializeContext failed: result=0x%08x\n", result);
        return -1;
    }
    client->context_open = 1;
    result = TEEC_OpenSession(&client->context, &client->session, &crypto_uuid,
                              TEEC_LOGIN_PUBLIC, NULL, NULL, &origin);
    if (result != TEEC_SUCCESS) {
        fprintf(stderr, "TEEC_OpenSession failed: result=0x%08x origin=0x%08x\n",
                result, origin);
        close_client(client);
        return -1;
    }
    client->session_open = 1;
    return 0;
}

static int invoke(struct tee_client *client, uint32_t command, TEEC_Operation *operation)
{
    TEEC_Result result;
    uint32_t origin = 0;

    result = TEEC_InvokeCommand(&client->session, command, operation, &origin);
    if (result != TEEC_SUCCESS) {
        fprintf(stderr, "TEEC_InvokeCommand(%u) failed: result=0x%08x origin=0x%08x\n",
                command, result, origin);
        return -1;
    }
    return 0;
}

static unsigned char *read_stdin(size_t *size)
{
    unsigned char *buffer = malloc(INPUT_MAX_SIZE ? INPUT_MAX_SIZE : 1U);
    size_t used = 0;
    size_t count;

    if (!buffer) {
        fprintf(stderr, "out of memory\n");
        return NULL;
    }
    while (used < INPUT_MAX_SIZE &&
           (count = fread(buffer + used, 1, INPUT_MAX_SIZE - used, stdin)) != 0)
        used += count;
    if (ferror(stdin)) {
        fprintf(stderr, "failed to read stdin: %s\n", strerror(errno));
        free(buffer);
        return NULL;
    }
    if (used == INPUT_MAX_SIZE && fgetc(stdin) != EOF) {
        fprintf(stderr, "input exceeds %u bytes\n", INPUT_MAX_SIZE);
        free(buffer);
        return NULL;
    }
    *size = used;
    return buffer;
}

static void print_hex(const unsigned char *data, size_t size)
{
    size_t index;
    for (index = 0; index < size; ++index)
        printf("%02x", data[index]);
}

static int generate_key(struct tee_client *client, uint32_t command)
{
    TEEC_Operation operation;
    memset(&operation, 0, sizeof(operation));
    operation.paramTypes = TEEC_PARAM_TYPES(TEEC_NONE, TEEC_NONE, TEEC_NONE, TEEC_NONE);
    if (invoke(client, command, &operation) != 0)
        return -1;
    puts("{\"ok\":true}");
    return 0;
}

static int calculate(struct tee_client *client, uint32_t command, size_t output_size)
{
    TEEC_Operation operation;
    unsigned char *message;
    unsigned char output[RSA_3072_SIZE];
    size_t message_size;

    message = read_stdin(&message_size);
    if (!message)
        return -1;
    memset(&operation, 0, sizeof(operation));
    operation.paramTypes = TEEC_PARAM_TYPES(TEEC_MEMREF_TEMP_INPUT,
                                             TEEC_MEMREF_TEMP_OUTPUT,
                                             TEEC_NONE, TEEC_NONE);
    operation.params[0].tmpref.buffer = message;
    operation.params[0].tmpref.size = message_size;
    operation.params[1].tmpref.buffer = output;
    operation.params[1].tmpref.size = output_size;
    if (invoke(client, command, &operation) != 0) {
        free(message);
        return -1;
    }
    free(message);
    printf("{\"ok\":true,\"value\":\"");
    print_hex(output, operation.params[1].tmpref.size);
    puts("\"}");
    return 0;
}

static int verify(struct tee_client *client, uint32_t command, size_t proof_size)
{
    TEEC_Operation operation;
    unsigned char *input;
    size_t input_size;

    input = read_stdin(&input_size);
    if (!input)
        return -1;
    if (input_size < proof_size) {
        fprintf(stderr, "verification input is shorter than proof\n");
        free(input);
        return -1;
    }
    memset(&operation, 0, sizeof(operation));
    operation.paramTypes = TEEC_PARAM_TYPES(TEEC_MEMREF_TEMP_INPUT,
                                             TEEC_MEMREF_TEMP_INPUT,
                                             TEEC_VALUE_OUTPUT, TEEC_NONE);
    operation.params[0].tmpref.buffer = input + proof_size;
    operation.params[0].tmpref.size = input_size - proof_size;
    operation.params[1].tmpref.buffer = input;
    operation.params[1].tmpref.size = proof_size;
    if (invoke(client, command, &operation) != 0) {
        free(input);
        return -1;
    }
    free(input);
    if (operation.params[2].value.a > 1U) {
        fprintf(stderr, "TA returned invalid verification status: %u\n",
                operation.params[2].value.a);
        return -1;
    }
    printf("{\"ok\":true,\"valid\":%s}\n",
           operation.params[2].value.a == 0U ? "true" : "false");
    return 0;
}

static int get_public_key(struct tee_client *client)
{
    TEEC_Operation operation;
    unsigned char modulus[RSA_3072_SIZE];
    unsigned char exponent[RSA_EXPONENT_MAX_SIZE];

    memset(&operation, 0, sizeof(operation));
    operation.paramTypes = TEEC_PARAM_TYPES(TEEC_MEMREF_TEMP_OUTPUT,
                                             TEEC_MEMREF_TEMP_OUTPUT,
                                             TEEC_NONE, TEEC_NONE);
    operation.params[0].tmpref.buffer = modulus;
    operation.params[0].tmpref.size = sizeof(modulus);
    operation.params[1].tmpref.buffer = exponent;
    operation.params[1].tmpref.size = sizeof(exponent);
    if (invoke(client, CRYPTO_GET_RSA_3072_PUB_KEY, &operation) != 0)
        return -1;
    printf("{\"ok\":true,\"n\":\"");
    print_hex(modulus, operation.params[0].tmpref.size);
    printf("\",\"e\":\"");
    print_hex(exponent, operation.params[1].tmpref.size);
    puts("\"}");
    return 0;
}

int main(int argc, char **argv)
{
    struct tee_client client;
    int status = -1;

    if (argc != 2) {
        fprintf(stderr, "usage: %s gen-aes|gen-rsa|rotate-rsa|cmac|sign|verify-cmac|verify-rsa|public-key\n",
                argv[0]);
        return 2;
    }
    if (open_client(&client) != 0)
        return 1;
    if (strcmp(argv[1], "gen-aes") == 0)
        status = generate_key(&client, CRYPTO_GEN_AES_128_KEY);
    else if (strcmp(argv[1], "gen-rsa") == 0)
        status = generate_key(&client, CRYPTO_GEN_RSA_3072_KEY);
    else if (strcmp(argv[1], "rotate-rsa") == 0)
        status = generate_key(&client, CRYPTO_ROTATE_RSA_3072_KEY);
    else if (strcmp(argv[1], "cmac") == 0)
        status = calculate(&client, CRYPTO_MAC_AES_128_KEY, AES_CMAC_SIZE);
    else if (strcmp(argv[1], "sign") == 0)
        status = calculate(&client, CRYPTO_MAC_RSA_3072_KEY, RSA_3072_SIZE);
    else if (strcmp(argv[1], "verify-cmac") == 0)
        status = verify(&client, CRYPTO_VERIFY_AES_128_KEY, AES_CMAC_SIZE);
    else if (strcmp(argv[1], "verify-rsa") == 0)
        status = verify(&client, CRYPTO_VERIFY_RSA_3072_KEY, RSA_3072_SIZE);
    else if (strcmp(argv[1], "public-key") == 0)
        status = get_public_key(&client);
    else
        fprintf(stderr, "unknown operation: %s\n", argv[1]);
    close_client(&client);
    return status == 0 ? 0 : 1;
}
