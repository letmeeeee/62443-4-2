// SPDX-License-Identifier: BSD-2-Clause
/*
 * crypto_ta：示例 TA，同时支持
 *   - AES-128：CMAC 计算/校验（CRYPTO_MAC_AES_128_KEY / CRYPTO_VERIFY_AES_128_KEY）
 *   - RSA-3072：PSS 签名/验签（CRYPTO_MAC_RSA_3072_KEY / CRYPTO_VERIFY_RSA_3072_KEY）
 * 两把密钥均持久化（幂等生成），并支持导出 RSA 公钥
 * （CRYPTO_GET_RSA_3072_PUB_KEY）。
 *
 * RSA 签名/验签用 "Digest" 变体：先 SHA-256 摘要，再对摘要做 PSS。
 */
#include <tee_internal_api.h>
#include <tee_internal_api_extensions.h>
#include "crypto_ta.h"
#include "../../common.h"

#define AES_KEY_BITS	128
#define RSA_KEY_BITS	3072
#define RSA_SIG_SIZE	(RSA_KEY_BITS / 8)	/* 384 */
#define DIGEST_SIZE	32			/* SHA-256 */

/* 持久对象访问标志：可读 / 可写 / 可改元数据 / 创建时覆盖同名。 */
#define PERSIST_FLAGS	(TEE_DATA_FLAG_ACCESS_READ | \
			 TEE_DATA_FLAG_ACCESS_WRITE | \
			 TEE_DATA_FLAG_ACCESS_WRITE_META | \
			 TEE_DATA_FLAG_OVERWRITE)

/* 确保持久密钥已存在：已创建则直接返回；否则生成一把并落盘。幂等。
 * obj_id/type/bits 决定具体是 AES 密钥还是 RSA 密钥对。 */
static TEE_Result ensure_key(const void *obj_id, size_t obj_id_len,
			     uint32_t type, uint32_t bits)
{
	TEE_ObjectHandle pers = TEE_HANDLE_NULL;	/* 持久对象句柄 */
	TEE_ObjectHandle trans = TEE_HANDLE_NULL;	/* 瞬态对象句柄 */
	TEE_Result res = TEE_SUCCESS;

	/* 先尝试打开；能打开说明已建好，直接返回（幂等）。
	 * 注意：OVERWRITE 是 Create 专属标志，Open 的 flags 不能带它，
	 * 否则 core 返回 BAD_PARAMETERS（见 tee_svc_storage.c 的 obj_open
	 * valid_flags）。此处仅探测存在性，用只读即可。 */
	res = TEE_OpenPersistentObject(TESTTA_STORAGE_ID, obj_id, obj_id_len,
				       TEE_DATA_FLAG_ACCESS_READ, &pers);
	if (res == TEE_SUCCESS) {
		TEE_CloseObject(pers);
		return TEE_SUCCESS;
	}
	/* 除「不存在」外的其它错误直接上报。 */
	if (res != TEE_ERROR_ITEM_NOT_FOUND)
		return res;

	/* 未见则生成：1) 建瞬态对象；2) 生成密钥；3) 以瞬态对象为属性源落盘。 */
	res = TEE_AllocateTransientObject(type, bits, &trans);
	if (res)
		return res;
	res = TEE_GenerateKey(trans, bits, NULL, 0);
	if (res)
		goto out;
	/* 把瞬态对象里的密钥材料写进持久对象；成功后关闭持久句柄。 */
	res = TEE_CreatePersistentObject(TESTTA_STORAGE_ID, obj_id, obj_id_len,
					 PERSIST_FLAGS, trans, NULL, 0, &pers);
	if (res == TEE_SUCCESS)
		TEE_CloseObject(pers);
out:
	/* 无论成败都释放瞬态对象。 */
	if (trans != TEE_HANDLE_NULL)
		TEE_FreeTransientObject(trans);
	return res;
}

/* 打开持久密钥，把密钥材料拷进瞬态对象。TEE_SetCryptoKey 只接受瞬态对象，
 * 所以持久对象不能直接喂给加密操作。 */
static TEE_Result load_key(const void *obj_id, size_t obj_id_len,
			   uint32_t type, uint32_t bits,
			   TEE_ObjectHandle *pers, TEE_ObjectHandle *trans)
{
	TEE_Result res = TEE_SUCCESS;

	/* 输出参数先置空，便于出错路径统一清理。 */
	*pers = TEE_HANDLE_NULL;
	*trans = TEE_HANDLE_NULL;

	/* 只读打开持久密钥对象。 */
	res = TEE_OpenPersistentObject(TESTTA_STORAGE_ID, obj_id, obj_id_len,
				       TEE_DATA_FLAG_ACCESS_READ, pers);
	if (res)
		return res;
	/* 分配一个空的瞬态对象，用来承载密钥材料。 */
	res = TEE_AllocateTransientObject(type, bits, trans);
	if (res)
		goto err;
	/* 把持久对象的密钥属性拷进瞬态对象（SetCryptoKey 只收瞬态）。 */
	res = TEE_CopyObjectAttributes1(*trans, *pers);
	if (res)
		goto err;
	return TEE_SUCCESS;
err:
	/* 出错：释放瞬态对象、关闭持久对象，并把输出复位为空。 */
	if (*trans != TEE_HANDLE_NULL)
		TEE_FreeTransientObject(*trans);
	TEE_CloseObject(*pers);
	*pers = TEE_HANDLE_NULL;
	*trans = TEE_HANDLE_NULL;
	return res;
}

/* 释放 load_key 取得的两个句柄（瞬态在前、持久在后）。 */
static void release_key(TEE_ObjectHandle pers, TEE_ObjectHandle trans)
{
	if (trans != TEE_HANDLE_NULL)
		TEE_FreeTransientObject(trans);
	if (pers != TEE_HANDLE_NULL)
		TEE_CloseObject(pers);
}

/* 对 data 做一次性 SHA-256，输出 32 字节摘要。 */
static TEE_Result sha256(const void *data, size_t data_len,
			 uint8_t digest[DIGEST_SIZE])
{
	TEE_OperationHandle op = TEE_HANDLE_NULL;
	TEE_Result res = TEE_SUCCESS;
	size_t dlen = DIGEST_SIZE;

	/* 分配 SHA-256 摘要操作（密钥位宽参数对摘要算法无意义，传 0）。 */
	res = TEE_AllocateOperation(&op, TEE_ALG_SHA256, TEE_MODE_DIGEST, 0);
	if (res)
		return res;
	/* 一次性完成：喂入全部数据，直接输出摘要。 */
	res = TEE_DigestDoFinal(op, data, data_len, digest, &dlen);
	TEE_FreeOperation(op);
	return res;
}

/* CRYPTO_MAC_AES_128_KEY：对 params[0] 的数据计算 CMAC，写入 params[1]（16 字节）。 */
static TEE_Result cmd_mac_aes(uint32_t pt, TEE_Param params[4])
{
	TEE_ObjectHandle pers = TEE_HANDLE_NULL;
	TEE_ObjectHandle trans = TEE_HANDLE_NULL;
	TEE_OperationHandle op = TEE_HANDLE_NULL;
	TEE_Result res = TEE_SUCCESS;
	size_t tag_len = 16;	/* AES 分块大小，即 CMAC 标签长度 */

	/* 校验参数类型：[0]=待认证数据输入，[1]=标签输出。 */
	if (TEE_PARAM_TYPE_GET(pt, 0) != TEE_PARAM_TYPE_MEMREF_INPUT ||
	    TEE_PARAM_TYPE_GET(pt, 1) != TEE_PARAM_TYPE_MEMREF_OUTPUT)
		return TEE_ERROR_BAD_PARAMETERS;
	/* 输出缓冲区至少要能放下一个 16 字节标签。 */
	if (params[1].memref.size < tag_len)
		return TEE_ERROR_SHORT_BUFFER;

	/* 载入持久 AES 密钥到瞬态对象。 */
	res = load_key(CRYPTO_AES_KEY_OBJ_ID, sizeof(CRYPTO_AES_KEY_OBJ_ID),
		       TEE_TYPE_AES, AES_KEY_BITS, &pers, &trans);
	if (res)
		goto out;
	/* 分配 AES-CMAC 的 MAC 操作（密钥位宽 128）。 */
	res = TEE_AllocateOperation(&op, TEE_ALG_AES_CMAC, TEE_MODE_MAC,
				    AES_KEY_BITS);
	if (res)
		goto out;
	res = TEE_SetOperationKey(op, trans);	/* 把瞬态密钥绑定到操作 */
	if (res)
		goto out;
	TEE_MACInit(op, NULL, 0);	/* 初始化；CMAC 无 IV，传 NULL/0 */
	/* 一次性计算：对输入数据算 CMAC，写入输出缓冲。 */
	res = TEE_MACComputeFinal(op, params[0].memref.buffer,
				  params[0].memref.size,
				  params[1].memref.buffer, &tag_len);
	if (res)
		goto out;
	params[1].memref.size = tag_len;	/* 回写实际标签长度给调用方 */
out:
	/* 释放操作句柄与密钥句柄。 */
	if (op != TEE_HANDLE_NULL)
		TEE_FreeOperation(op);
	release_key(pers, trans);
	return res;
}

/* CRYPTO_VERIFY_AES_128_KEY：用同一密钥校验 params[1] 是否为 params[0] 的 CMAC。
 * 结果写 params[2].value.a：0=一致，1=不一致。 */
static TEE_Result cmd_verify_aes(uint32_t pt, TEE_Param params[4])
{
	TEE_ObjectHandle pers = TEE_HANDLE_NULL;
	TEE_ObjectHandle trans = TEE_HANDLE_NULL;
	TEE_OperationHandle op = TEE_HANDLE_NULL;
	TEE_Result res = TEE_SUCCESS;

	/* 校验参数类型：[0]=数据输入，[1]=待验标签输入，[2]=结果输出(value)。 */
	if (TEE_PARAM_TYPE_GET(pt, 0) != TEE_PARAM_TYPE_MEMREF_INPUT ||
	    TEE_PARAM_TYPE_GET(pt, 1) != TEE_PARAM_TYPE_MEMREF_INPUT ||
	    TEE_PARAM_TYPE_GET(pt, 2) != TEE_PARAM_TYPE_VALUE_OUTPUT)
		return TEE_ERROR_BAD_PARAMETERS;

	/* 载入密钥、分配 MAC 操作并绑定（与 cmd_mac_aes 同一套密钥）。 */
	res = load_key(CRYPTO_AES_KEY_OBJ_ID, sizeof(CRYPTO_AES_KEY_OBJ_ID),
		       TEE_TYPE_AES, AES_KEY_BITS, &pers, &trans);
	if (res)
		goto out;
	res = TEE_AllocateOperation(&op, TEE_ALG_AES_CMAC, TEE_MODE_MAC,
				    AES_KEY_BITS);
	if (res)
		goto out;
	res = TEE_SetOperationKey(op, trans);
	if (res)
		goto out;
	TEE_MACInit(op, NULL, 0);
	/* 一次性比较：用同一密钥重算 CMAC 并与传入标签比对。 */
	res = TEE_MACCompareFinal(op, params[0].memref.buffer,
				  params[0].memref.size,
				  params[1].memref.buffer,
				  params[1].memref.size);
	/* CompareFinal 不一致时返回非 SUCCESS；统一映射成 0/1 给调用方。 */
	params[2].value.a = (res == TEE_SUCCESS) ? 0 : 1;
	res = TEE_SUCCESS;	/* 命令本身执行成功，比对结果在 value.a */
out:
	if (op != TEE_HANDLE_NULL)
		TEE_FreeOperation(op);
	release_key(pers, trans);
	return res;
}

/* CRYPTO_MAC_RSA_3072_KEY：对 params[0] 数据做 PSS 签名，输出到 params[1]（384 字节）。
 * 先 SHA-256 摘要，再对摘要做 RSA-PSS 签名。 */
static TEE_Result cmd_sign_rsa(uint32_t pt, TEE_Param params[4])
{
	TEE_ObjectHandle pers = TEE_HANDLE_NULL;
	TEE_ObjectHandle trans = TEE_HANDLE_NULL;
	TEE_OperationHandle op = TEE_HANDLE_NULL;
	TEE_Result res = TEE_SUCCESS;
	uint8_t digest[DIGEST_SIZE];
	size_t sig_len = 0;

	/* 校验参数类型：[0]=待签名数据输入，[1]=签名输出。 */
	if (TEE_PARAM_TYPE_GET(pt, 0) != TEE_PARAM_TYPE_MEMREF_INPUT ||
	    TEE_PARAM_TYPE_GET(pt, 1) != TEE_PARAM_TYPE_MEMREF_OUTPUT)
		return TEE_ERROR_BAD_PARAMETERS;
	/* 输出缓冲区至少能放下 384 字节签名。 */
	if (params[1].memref.size < RSA_SIG_SIZE)
		return TEE_ERROR_SHORT_BUFFER;

	/* 1) 先对数据做 SHA-256 摘要。 */
	res = sha256(params[0].memref.buffer, params[0].memref.size, digest);
	if (res)
		goto out;
	/* 2) 载入持久 RSA 密钥对到瞬态对象。 */
	res = load_key(CRYPTO_RSA_KEY_OBJ_ID, sizeof(CRYPTO_RSA_KEY_OBJ_ID),
		       TEE_TYPE_RSA_KEYPAIR, RSA_KEY_BITS, &pers, &trans);
	if (res)
		goto out;
	/* 3) 分配 RSA-PSS(SHA256) 签名操作并绑定密钥。 */
	res = TEE_AllocateOperation(&op, TEE_ALG_RSASSA_PKCS1_PSS_MGF1_SHA256,
				    TEE_MODE_SIGN, RSA_KEY_BITS);
	if (res)
		goto out;
	res = TEE_SetOperationKey(op, trans);
	if (res)
		goto out;
	sig_len = params[1].memref.size;
	/* 4) 对「已算好的摘要」做 PSS 签名（digest 即输入，无需再哈希）。 */
	res = TEE_AsymmetricSignDigest(op, NULL, 0, digest, DIGEST_SIZE,
				       params[1].memref.buffer, &sig_len);
	if (res)
		goto out;
	params[1].memref.size = sig_len;	/* 回写实际签名长度 */
out:
	/* 释放操作句柄与密钥句柄。 */
	if (op != TEE_HANDLE_NULL)
		TEE_FreeOperation(op);
	release_key(pers, trans);
	return res;
}

/* CRYPTO_VERIFY_RSA_3072_KEY：校验 params[1] 是否为 params[0] 数据的合法 PSS 签名。
 * 结果写 params[2].value.a：0=有效，1=无效。 */
static TEE_Result cmd_verify_rsa(uint32_t pt, TEE_Param params[4])
{
	TEE_ObjectHandle pers = TEE_HANDLE_NULL;
	TEE_ObjectHandle trans = TEE_HANDLE_NULL;
	TEE_OperationHandle op = TEE_HANDLE_NULL;
	TEE_Result res = TEE_SUCCESS;
	uint8_t digest[DIGEST_SIZE];

	/* 校验参数类型：[0]=数据输入，[1]=待验签名输入，[2]=结果输出(value)。 */
	if (TEE_PARAM_TYPE_GET(pt, 0) != TEE_PARAM_TYPE_MEMREF_INPUT ||
	    TEE_PARAM_TYPE_GET(pt, 1) != TEE_PARAM_TYPE_MEMREF_INPUT ||
	    TEE_PARAM_TYPE_GET(pt, 2) != TEE_PARAM_TYPE_VALUE_OUTPUT)
		return TEE_ERROR_BAD_PARAMETERS;

	/* 1) 先对数据做 SHA-256 摘要。 */
	res = sha256(params[0].memref.buffer, params[0].memref.size, digest);
	if (res)
		goto out;
	/* 2) 载入密钥对、分配验签操作并绑定。 */
	res = load_key(CRYPTO_RSA_KEY_OBJ_ID, sizeof(CRYPTO_RSA_KEY_OBJ_ID),
		       TEE_TYPE_RSA_KEYPAIR, RSA_KEY_BITS, &pers, &trans);
	if (res)
		goto out;
	res = TEE_AllocateOperation(&op, TEE_ALG_RSASSA_PKCS1_PSS_MGF1_SHA256,
				    TEE_MODE_VERIFY, RSA_KEY_BITS);
	if (res)
		goto out;
	res = TEE_SetOperationKey(op, trans);
	if (res)
		goto out;
	/* 3) 用持久 keypair 验证「摘要 + 签名」是否匹配。 */
	res = TEE_AsymmetricVerifyDigest(op, NULL, 0, digest, DIGEST_SIZE,
					 params[1].memref.buffer,
					 params[1].memref.size);
	/* VerifyDigest 无效时返回非 SUCCESS；统一映射成 0/1 给调用方。 */
	params[2].value.a = (res == TEE_SUCCESS) ? 0 : 1;
	res = TEE_SUCCESS;	/* 命令本身执行成功，验签结果在 value.a */
out:
	if (op != TEE_HANDLE_NULL)
		TEE_FreeOperation(op);
	release_key(pers, trans);
	return res;
}

/* CRYPTO_GET_RSA_3072_PUB_KEY：导出 RSA 公钥的模数 n 与公钥指数 e。
 * params[0]=n 输出(memref,384)，params[1]=e 输出(memref,通常 3 字节)。
 * n、e 为 PUBLIC 属性，可直接从持久 keypair 读取，无需拷到瞬态。 */
static TEE_Result cmd_get_rsa_pub_key(uint32_t pt, TEE_Param params[4])
{
	TEE_ObjectHandle pers = TEE_HANDLE_NULL;
	TEE_Result res = TEE_SUCCESS;
	size_t n_len = 0;
	size_t e_len = 0;

	/* 校验参数类型：[0]=n 输出，[1]=e 输出。 */
	if (TEE_PARAM_TYPE_GET(pt, 0) != TEE_PARAM_TYPE_MEMREF_OUTPUT ||
	    TEE_PARAM_TYPE_GET(pt, 1) != TEE_PARAM_TYPE_MEMREF_OUTPUT)
		return TEE_ERROR_BAD_PARAMETERS;

	/* 只读打开持久 RSA 密钥对。 */
	res = TEE_OpenPersistentObject(TESTTA_STORAGE_ID, CRYPTO_RSA_KEY_OBJ_ID,
				       sizeof(CRYPTO_RSA_KEY_OBJ_ID),
				       TEE_DATA_FLAG_ACCESS_READ, &pers);
	if (res)
		return res;

	/* 读模数 n：size 既是入参（缓冲容量）也是出参（实际长度）。 */
	n_len = params[0].memref.size;
	res = TEE_GetObjectBufferAttribute(pers, TEE_ATTR_RSA_MODULUS,
					   params[0].memref.buffer, &n_len);
	if (res)
		goto out;
	/* 读公钥指数 e。 */
	e_len = params[1].memref.size;
	res = TEE_GetObjectBufferAttribute(pers, TEE_ATTR_RSA_PUBLIC_EXPONENT,
					   params[1].memref.buffer, &e_len);
	if (res)
		goto out;
	params[0].memref.size = n_len;	/* 回写实际长度 */
	params[1].memref.size = e_len;
out:
	TEE_CloseObject(pers);
	return res;
}

/* TA 生命周期入口：本例无需初始化/清理，直接返回成功。 */
TEE_Result TA_CreateEntryPoint(void)
{
	return TEE_SUCCESS;
}

void TA_DestroyEntryPoint(void)
{
}

TEE_Result TA_OpenSessionEntryPoint(uint32_t pt __unused,
				    TEE_Param params[4] __unused,
				    void **sess __unused)
{
	return TEE_SUCCESS;
}

void TA_CloseSessionEntryPoint(void *sess __unused)
{
}

/* 命令分发：按 cmd 路由到对应处理函数。 */
TEE_Result TA_InvokeCommandEntryPoint(void *sess __unused, uint32_t cmd,
				      uint32_t pt, TEE_Param params[4])
{
	switch (cmd) {
	case CRYPTO_GEN_AES_128_KEY:
		return ensure_key(CRYPTO_AES_KEY_OBJ_ID,
				  sizeof(CRYPTO_AES_KEY_OBJ_ID),
				  TEE_TYPE_AES, AES_KEY_BITS);
	case CRYPTO_GEN_RSA_3072_KEY:
		return ensure_key(CRYPTO_RSA_KEY_OBJ_ID,
				  sizeof(CRYPTO_RSA_KEY_OBJ_ID),
				  TEE_TYPE_RSA_KEYPAIR, RSA_KEY_BITS);
	case CRYPTO_MAC_AES_128_KEY:
		return cmd_mac_aes(pt, params);
	case CRYPTO_MAC_RSA_3072_KEY:
		return cmd_sign_rsa(pt, params);
	case CRYPTO_VERIFY_AES_128_KEY:
		return cmd_verify_aes(pt, params);
	case CRYPTO_VERIFY_RSA_3072_KEY:
		return cmd_verify_rsa(pt, params);
	case CRYPTO_GET_RSA_3072_PUB_KEY:
		return cmd_get_rsa_pub_key(pt, params);
	default:
		return TEE_ERROR_BAD_PARAMETERS;
	}
}
