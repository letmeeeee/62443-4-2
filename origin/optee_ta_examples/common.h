/* SPDX-License-Identifier: BSD-2-Clause */
/*
 * testta 共享定义（仅 TA 侧使用；host CA 不用）。
 */
#ifndef TESTTA_COMMON_H
#define TESTTA_COMMON_H

/*
 * 持久化存储后端。
 *
 * TEE_STORAGE_PRIVATE (0x1)：平台默认。CFG_RPMB_FS=n 时为 REE FS；
 *   CFG_RPMB_FS=y 时变为 RPMB。
 * TEE_STORAGE_PRIVATE_RPMB (0x80000100)：强制 RPMB（需 CFG_RPMB_FS=y 且
 *   eMMC RPMB 分区已就绪，否则创建失败）。
 */
#define TESTTA_STORAGE_ID	0x00000001

/* 持久对象标识。命名空间按 TA UUID 划分，故同属 crypto_ta 的两把密钥用不同
 * obj_id 即可区分（AES 密钥 / RSA 密钥对各自独立）。 */
#define CRYPTO_AES_KEY_OBJ_ID	"aes128_key"
#define CRYPTO_RSA_KEY_OBJ_ID	"rsa3072_kp"

#endif /* TESTTA_COMMON_H */
