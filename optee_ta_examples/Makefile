# SPDX-License-Identifier: BSD-2-Clause
#
# Top-level Makefile for the testta example TAs + host clients.
#
# Prerequisites:
#   1. Build the OP-TEE OS dev kit once:
#        make PLATFORM=k3-am65x
#      (produces out/k3-am65x/export-ta_arm64)
#   2. Have the aarch64 cross toolchain (CROSS_COMPILE).
#   3. For the host clients: optee_client headers (tee_client_api.h) and
#      libteec. On a Debian arm64 board/devroot these come from libteec-dev
#      (or build optee_client). Point OPTEE_CLIENT_INC / LIBTEEC_LIB at them.
#
# Usage:
#   make                            # build all TAs + CAs
#   make TA_DEV_KIT_DIR=/path/to/export-ta_arm64 CROSS_COMPILE=... \
#        OPTEE_CLIENT_INC=/usr/include LIBTEEC_LIB=/usr/lib
#   make tas | make cas             # build only TAs / only CAs
#   make install DESTDIR=/mnt/rootfs

TA_DEV_KIT_DIR ?= $(CURDIR)/dev_kit
CROSS_COMPILE  ?= aarch64-linux-gnu-
OPTEE_CLIENT_INC ?= $(abspath $(CURDIR)/../logger/.deps/optee-arm64/include)
LIBTEEC_LIB    ?= $(abspath $(CURDIR)/../logger/.deps/optee-arm64/lib)
DESTDIR        ?= /

TA_DIRS = ta/crypto_ta
TA_BINS = ta/crypto_ta/5319e0a0-0001-4e2a-9c01-0c34da100001.ta

.PHONY: all tas cas clean install
all: tas cas

tas:
	@for d in $(TA_DIRS); do \
	  echo "  BUILD  $$d"; \
	  $(MAKE) -C $$d TA_DEV_KIT_DIR=$(TA_DEV_KIT_DIR) \
	    CROSS_COMPILE=$(CROSS_COMPILE) || exit 1; \
	done

cas:
	$(MAKE) -C host CROSS_COMPILE=$(CROSS_COMPILE) \
	  OPTEE_CLIENT_INC=$(OPTEE_CLIENT_INC) LIBTEEC_LIB=$(LIBTEEC_LIB)

install:
	install -d $(DESTDIR)/usr/lib/optee_armtz $(DESTDIR)/usr/bin
	install -m 0644 $(TA_BINS) $(DESTDIR)/usr/lib/optee_armtz/
	install -m 0755 host/crypto_test_ta $(DESTDIR)/usr/bin/

clean:
	@for d in $(TA_DIRS); do \
	  $(MAKE) -C $$d clean TA_DEV_KIT_DIR=$(TA_DEV_KIT_DIR) \
	    CROSS_COMPILE=$(CROSS_COMPILE) 2>/dev/null || true; \
	done
	$(MAKE) -C host clean 2>/dev/null || true
