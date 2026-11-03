# SPDX-License-Identifier: BSD-2-Clause
#
# Host clients (CAs). Need optee_client's tee_client_api.h + libteec.
CC = $(CROSS_COMPILE)gcc
CFLAGS ?= -Wall -O2

INC = -I../ta/crypto_ta/include \
      -I$(OPTEE_CLIENT_INC)
LDFLAGS = -L$(LIBTEEC_LIB)
LDLIBS = -lteec

BINS = crypto_test_ta

.PHONY: all clean
all: $(BINS)

%: %.c
	$(CC) $(CFLAGS) $(INC) -o $@ $< $(LDFLAGS) $(LDLIBS)

clean:
	rm -f $(BINS)
