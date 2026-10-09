// SPDX-License-Identifier: BSD-2-Clause
/*
 * crypto_test_ta：crypto_ta 的测试客户端。一次会话内跑完全部用例，按
 *   [PASS/FAIL] test-name: description
 * 逐条打印结果，末尾给汇总；任一失败则退出码非 0。
 *
 * 每个用例封装为一个 test_* 函数，共用一份 test_ctx（会话、输入数据，以及
 * 在用例间传递的 tag/sig/pubkey 缓冲）。
 */
#include <tee_client_api.h>
#include <stdio.h>
#include <string.h>
#include "crypto_ta.h"

static const TEEC_UUID uuid = TA_CRYPTO_UUID;

static int g_pass = 0;
static int g_fail = 0;

/* 跨用例共享的状态：会话、输入数据、以及用例间传递的缓冲。 */
struct test_ctx {
	TEEC_Session *sess;
	const char *data;
	size_t len;
	uint8_t tag[16];	/* AES CMAC tag：aes-mac 写、aes-verify 读 */
	uint8_t sig[384];	/* RSA 签名：rsa-sign 写、rsa-verify 读 */
	uint8_t n[384];		/* RSA 模数，最长 384 字节 */
	uint8_t e[8];		/* RSA 公钥指数，通常 3 字节(65537) */
};

/* 打印一行结果并计数：ok=1 通过，ok=0 失败。 */
static void report(int ok, const char *name, const char *desc)
{
	printf("[%s] %s: %s\n", ok ? "PASS" : "FAIL", name, desc);
	if (ok)
		g_pass++;
	else
		g_fail++;
}

/* 生成/持久化 AES-128 密钥。 */
static void test_aes_gen(struct test_ctx *c)
{
	TEEC_Operation op = { 0 };
	uint32_t origin = 0;
	TEEC_Result r = TEEC_SUCCESS;

	op.paramTypes = TEEC_PARAM_TYPES(TEEC_NONE, TEEC_NONE, TEEC_NONE,
					 TEEC_NONE);
	r = TEEC_InvokeCommand(c->sess, CRYPTO_GEN_AES_128_KEY, &op, &origin);
	report(r == TEEC_SUCCESS, "aes-gen", "generate/persist AES-128 key");
}

/* 计算 CMAC tag（预期 16 字节）。 */
static void test_aes_mac(struct test_ctx *c)
{
	TEEC_Operation op = { 0 };
	uint32_t origin = 0;
	TEEC_Result r = TEEC_SUCCESS;

	op.params[0].tmpref.buffer = (void *)c->data;
	op.params[0].tmpref.size = c->len;
	op.params[1].tmpref.buffer = c->tag;
	op.params[1].tmpref.size = sizeof(c->tag);
	op.paramTypes = TEEC_PARAM_TYPES(TEEC_MEMREF_TEMP_INPUT,
					 TEEC_MEMREF_TEMP_OUTPUT, TEEC_NONE,
					 TEEC_NONE);
	r = TEEC_InvokeCommand(c->sess, CRYPTO_MAC_AES_128_KEY, &op, &origin);
	report(r == TEEC_SUCCESS && op.params[1].tmpref.size == 16,
	       "aes-mac", "compute AES-128 CMAC tag");
}

/* 校验正确标签，预期 MATCH(value.a==0)。 */
static void test_aes_verify_good(struct test_ctx *c)
{
	TEEC_Operation op = { 0 };
	uint32_t origin = 0;
	TEEC_Result r = TEEC_SUCCESS;

	op.params[0].tmpref.buffer = (void *)c->data;
	op.params[0].tmpref.size = c->len;
	op.params[1].tmpref.buffer = c->tag;
	op.params[1].tmpref.size = sizeof(c->tag);
	op.paramTypes = TEEC_PARAM_TYPES(TEEC_MEMREF_TEMP_INPUT,
					 TEEC_MEMREF_TEMP_INPUT,
					 TEEC_VALUE_OUTPUT, TEEC_NONE);
	r = TEEC_InvokeCommand(c->sess, CRYPTO_VERIFY_AES_128_KEY, &op, &origin);
	report(r == TEEC_SUCCESS && op.params[2].value.a == 0,
	       "aes-verify-good", "verify correct CMAC tag");
}

/* 篡改标签后校验，预期 MISMATCH(value.a==1)。 */
static void test_aes_verify_tampered(struct test_ctx *c)
{
	TEEC_Operation op = { 0 };
	uint32_t origin = 0;
	TEEC_Result r = TEEC_SUCCESS;

	c->tag[0] ^= 0xff;	/* 篡改 */
	op.params[0].tmpref.buffer = (void *)c->data;
	op.params[0].tmpref.size = c->len;
	op.params[1].tmpref.buffer = c->tag;
	op.params[1].tmpref.size = sizeof(c->tag);
	op.paramTypes = TEEC_PARAM_TYPES(TEEC_MEMREF_TEMP_INPUT,
					 TEEC_MEMREF_TEMP_INPUT,
					 TEEC_VALUE_OUTPUT, TEEC_NONE);
	r = TEEC_InvokeCommand(c->sess, CRYPTO_VERIFY_AES_128_KEY, &op, &origin);
	report(r == TEEC_SUCCESS && op.params[2].value.a == 1,
	       "aes-verify-tampered", "verify tampered CMAC tag");
}

/* 生成/持久化 RSA-3072 密钥对。 */
static void test_rsa_gen(struct test_ctx *c)
{
	TEEC_Operation op = { 0 };
	uint32_t origin = 0;
	TEEC_Result r = TEEC_SUCCESS;

	op.paramTypes = TEEC_PARAM_TYPES(TEEC_NONE, TEEC_NONE, TEEC_NONE,
					 TEEC_NONE);
	r = TEEC_InvokeCommand(c->sess, CRYPTO_GEN_RSA_3072_KEY, &op, &origin);
	report(r == TEEC_SUCCESS, "rsa-gen", "generate/persist RSA-3072 keypair");
}

/* 导出公钥 n、e（预期非空）。 */
static void test_rsa_pubkey(struct test_ctx *c)
{
	TEEC_Operation op = { 0 };
	uint32_t origin = 0;
	TEEC_Result r = TEEC_SUCCESS;

	op.params[0].tmpref.buffer = c->n;
	op.params[0].tmpref.size = sizeof(c->n);
	op.params[1].tmpref.buffer = c->e;
	op.params[1].tmpref.size = sizeof(c->e);
	op.paramTypes = TEEC_PARAM_TYPES(TEEC_MEMREF_TEMP_OUTPUT,
					 TEEC_MEMREF_TEMP_OUTPUT, TEEC_NONE,
					 TEEC_NONE);
	r = TEEC_InvokeCommand(c->sess, CRYPTO_GET_RSA_3072_PUB_KEY, &op,
			       &origin);
	report(r == TEEC_SUCCESS && op.params[0].tmpref.size > 0 &&
	       op.params[1].tmpref.size > 0,
	       "rsa-pubkey", "export RSA-3072 public key (n,e)");
}

/* 签名（预期 384 字节）。 */
static void test_rsa_sign(struct test_ctx *c)
{
	TEEC_Operation op = { 0 };
	uint32_t origin = 0;
	TEEC_Result r = TEEC_SUCCESS;

	op.params[0].tmpref.buffer = (void *)c->data;
	op.params[0].tmpref.size = c->len;
	op.params[1].tmpref.buffer = c->sig;
	op.params[1].tmpref.size = sizeof(c->sig);
	op.paramTypes = TEEC_PARAM_TYPES(TEEC_MEMREF_TEMP_INPUT,
					 TEEC_MEMREF_TEMP_OUTPUT, TEEC_NONE,
					 TEEC_NONE);
	r = TEEC_InvokeCommand(c->sess, CRYPTO_MAC_RSA_3072_KEY, &op, &origin);
	report(r == TEEC_SUCCESS && op.params[1].tmpref.size == 384,
	       "rsa-sign", "compute RSA-3072 PSS signature");
}

/* 校验正确签名，预期 VALID(value.a==0)。 */
static void test_rsa_verify_good(struct test_ctx *c)
{
	TEEC_Operation op = { 0 };
	uint32_t origin = 0;
	TEEC_Result r = TEEC_SUCCESS;

	op.params[0].tmpref.buffer = (void *)c->data;
	op.params[0].tmpref.size = c->len;
	op.params[1].tmpref.buffer = c->sig;
	op.params[1].tmpref.size = sizeof(c->sig);
	op.paramTypes = TEEC_PARAM_TYPES(TEEC_MEMREF_TEMP_INPUT,
					 TEEC_MEMREF_TEMP_INPUT,
					 TEEC_VALUE_OUTPUT, TEEC_NONE);
	r = TEEC_InvokeCommand(c->sess, CRYPTO_VERIFY_RSA_3072_KEY, &op, &origin);
	report(r == TEEC_SUCCESS && op.params[2].value.a == 0,
	       "rsa-verify-good", "verify correct RSA signature");
}

/* 篡改签名后校验，预期 INVALID(value.a==1)。 */
static void test_rsa_verify_tampered(struct test_ctx *c)
{
	TEEC_Operation op = { 0 };
	uint32_t origin = 0;
	TEEC_Result r = TEEC_SUCCESS;

	c->sig[0] ^= 0xff;	/* 篡改 */
	op.params[0].tmpref.buffer = (void *)c->data;
	op.params[0].tmpref.size = c->len;
	op.params[1].tmpref.buffer = c->sig;
	op.params[1].tmpref.size = sizeof(c->sig);
	op.paramTypes = TEEC_PARAM_TYPES(TEEC_MEMREF_TEMP_INPUT,
					 TEEC_MEMREF_TEMP_INPUT,
					 TEEC_VALUE_OUTPUT, TEEC_NONE);
	r = TEEC_InvokeCommand(c->sess, CRYPTO_VERIFY_RSA_3072_KEY, &op, &origin);
	report(r == TEEC_SUCCESS && op.params[2].value.a == 1,
	       "rsa-verify-tampered", "verify tampered RSA signature");
}

int main(void)
{
	TEEC_Context ctx = { 0 };
	TEEC_Session sess = { 0 };
	TEEC_Result r = TEEC_SUCCESS;
	uint32_t origin = 0;
	struct test_ctx c = { 0 };

	c.data = "hello optee crypto";
	c.len = strlen(c.data);

	/* 建立 context 并打开到 crypto_ta 的会话。 */
	r = TEEC_InitializeContext(NULL, &ctx);
	if (r) {
		printf("InitializeContext: 0x%x\n", r);
		return 1;
	}
	r = TEEC_OpenSession(&ctx, &sess, &uuid, TEEC_LOGIN_PUBLIC, NULL, NULL,
			     &origin);
	if (r) {
		printf("OpenSession: 0x%x (origin 0x%x)\n", r, origin);
		TEEC_FinalizeContext(&ctx);
		return 1;
	}
	c.sess = &sess;

	/* ===== AES-128 CMAC ===== */
	test_aes_gen(&c);
	test_aes_mac(&c);
	test_aes_verify_good(&c);
	test_aes_verify_tampered(&c);

	/* ===== RSA-3072 PSS ===== */
	test_rsa_gen(&c);
	test_rsa_pubkey(&c);
	test_rsa_sign(&c);
	test_rsa_verify_good(&c);
	test_rsa_verify_tampered(&c);

	TEEC_CloseSession(&sess);
	TEEC_FinalizeContext(&ctx);

	printf("\n%d passed, %d failed\n", g_pass, g_fail);
	return g_fail ? 1 : 0;
}
