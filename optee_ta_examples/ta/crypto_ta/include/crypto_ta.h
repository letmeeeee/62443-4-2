/* SPDX-License-Identifier: BSD-2-Clause */
/*
 * crypto_ta：示例 TA，同时支持 AES-128 CMAC 与 RSA-3072 PSS。
 * 共享 UUID 与命令 ID。TA（crypto_ta.c）与测试客户端（crypto_test_ta.c）
 * 都包含本头。
 */
#ifndef CRYPTO_TA_H
#define CRYPTO_TA_H

#define TA_CRYPTO_UUID {					\
	0x5319e0a0, 0x0001, 0x4e2a,				\
	{ 0x9c, 0x01, 0x0c, 0x34, 0xda, 0x10, 0x00, 0x01 } }

/* 命令 ID。AES 走 CMAC；RSA 的 MAC/VERIFY 实为 PSS 签名/验签。 */
#define CRYPTO_GEN_AES_128_KEY		0	/* 生成/持久化 AES-128 密钥（幂等） */
#define CRYPTO_GEN_RSA_3072_KEY		1	/* 生成/持久化 RSA-3072 密钥对（幂等） */
#define CRYPTO_MAC_AES_128_KEY		2	/* 输入: data(memref) -> 输出: tag(memref,16) */
#define CRYPTO_MAC_RSA_3072_KEY		3	/* 输入: data(memref) -> 输出: sig(memref,384)，PSS 签名 */
#define CRYPTO_VERIFY_AES_128_KEY	4	/* 输入: data(memref)+tag(memref) -> 输出: match(value) */
#define CRYPTO_VERIFY_RSA_3072_KEY	5	/* 输入: data(memref)+sig(memref) -> 输出: valid(value)，PSS 验签 */
#define CRYPTO_GET_RSA_3072_PUB_KEY	6	/* 输出: n(memref)+e(memref) <- RSA 公钥 */
#define CRYPTO_ROTATE_RSA_3072_KEY	7	/* 显式生成新 RSA-3072 密钥对并覆盖旧对象 */

/* Modbus TLS extension; existing commands 0..7 retain their ABI.
 * Slot values are logical roles, never persistent storage object IDs.
 * 8: (VALUE_INPUT,NONE,NONE,NONE), p0.a=slot
 * 9: (MEMREF_OUTPUT,MEMREF_OUTPUT,VALUE_INPUT,NONE), p2.a=slot
 * 10: (MEMREF_INPUT,MEMREF_OUTPUT,VALUE_INPUT,NONE), digest -> signature
 * 11: (MEMREF_INPUT,MEMREF_INPUT,VALUE_INOUT,NONE), digest + signature
 * For 10/11: p2.a=slot, p2.b=scheme; 11 returns p2.a=0 valid, 1 invalid.
 * Digest inputs are already hashed; PSS uses MGF1 with the same hash and
 * salt length equal to digest length. All signatures are 384 bytes.
 */
#define CRYPTO_MODBUS_ENSURE_RSA 8
#define CRYPTO_MODBUS_GET_PUBLIC 9
#define CRYPTO_MODBUS_SIGN_DIGEST 10
#define CRYPTO_MODBUS_VERIFY_DIGEST 11
#define CRYPTO_MODBUS_MASTER 0
#define CRYPTO_MODBUS_SLAVE 1
#define CRYPTO_RSA_PKCS1_SHA256 1
#define CRYPTO_RSA_PKCS1_SHA384 2
#define CRYPTO_RSA_PKCS1_SHA512 3
#define CRYPTO_RSA_PSS_SHA256 4
#define CRYPTO_RSA_PSS_SHA384 5
#define CRYPTO_RSA_PSS_SHA512 6

#endif /* CRYPTO_TA_H */
