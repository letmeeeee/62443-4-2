ROOT := ../..
CROSS_COMPILE ?= aarch64-linux-gnu-
CC = $(CROSS_COMPILE)gcc
OPTEE_CLIENT_INC ?= $(ROOT)/logger/.deps/optee-arm64/include
LIBTEEC_LIB ?= $(ROOT)/logger/.deps/optee-arm64/lib
CPPFLAGS += -I$(ROOT)/origin/optee_ta_examples/ta/crypto_ta/include -I$(OPTEE_CLIENT_INC)
CFLAGS ?= -O2 -g
CFLAGS += -std=c99 -Wall -Wextra -Werror
LDFLAGS += -L$(LIBTEEC_LIB)
# Use the deployed system SONAME without embedding workstation paths in RPATH.
LDLIBS += -l:libteec.so.2

.PHONY: all
all: crypto_persistence

crypto_persistence: crypto_persistence.c $(ROOT)/origin/optee_ta_examples/ta/crypto_ta/include/crypto_ta.h
	$(CC) $(CPPFLAGS) $(CFLAGS) $(LDFLAGS) -o $@ $< $(LDLIBS)

