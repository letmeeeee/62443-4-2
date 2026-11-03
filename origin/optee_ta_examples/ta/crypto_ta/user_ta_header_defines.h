/* SPDX-License-Identifier: BSD-2-Clause */
/*
 * TA-specific defines for user_ta_header.c. Mirrors the optee-os TA pattern
 * (cf. ta/trusted_keys/user_ta_header_defines.h). The dev kit does not
 * generate this header; each TA must provide it.
 */
#ifndef USER_TA_HEADER_DEFINES_H
#define USER_TA_HEADER_DEFINES_H

#include <crypto_ta.h>

#define TA_UUID			TA_CRYPTO_UUID

#define TA_FLAGS		(TA_FLAG_SINGLE_INSTANCE | \
				 TA_FLAG_MULTI_SESSION | \
				 TA_FLAG_DEVICE_ENUM)

#define TA_STACK_SIZE		(4 * 1024)
#define TA_DATA_SIZE		(32 * 1024)

#define TA_VERSION		"1.0"
#define TA_DESCRIPTION		"testta crypto (AES-128 CMAC + RSA-3072 PSS)"

#endif /* USER_TA_HEADER_DEFINES_H */
