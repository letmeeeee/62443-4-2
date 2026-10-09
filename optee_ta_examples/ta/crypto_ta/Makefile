# SPDX-License-Identifier: BSD-2-Clause
#
# Build crypto_ta with the OP-TEE TA dev kit. The dev kit signs the
# resulting .ta with keys/default.pem, so it loads under the prebuilt bl32.

BINARY ?= 5319e0a0-0001-4e2a-9c01-0c34da100001
TA_DEV_KIT_DIR ?= $(CURDIR)/../../dev_kit

include $(TA_DEV_KIT_DIR)/mk/ta_dev_kit.mk
