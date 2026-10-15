# GNU Make predefines CC=cc, so `CC ?= gcc` would never take effect.
# Respect an explicit CC; otherwise use CROSS_COMPILE (if set) or gcc.
ifeq ($(origin CC),default)
CC := $(if $(CROSS_COMPILE),$(CROSS_COMPILE)gcc,gcc)
endif

SYSROOT ?=
OPTEE_CLIENT_ROOT ?= ../../../logger/.deps/optee-arm64
CPPFLAGS ?=
override CPPFLAGS += -I../../../optee_ta_examples/ta/crypto_ta/include -I$(OPTEE_CLIENT_ROOT)/include
CFLAGS ?= -O2 -Wall -Wextra -Werror
LDFLAGS ?=
override LDFLAGS += -L$(OPTEE_CLIENT_ROOT)/lib
LDLIBS ?= -lteec

ifneq ($(strip $(SYSROOT)),)
CPPFLAGS += --sysroot=$(SYSROOT)
LDFLAGS += --sysroot=$(SYSROOT)
endif

TARGET := crypto_ta_client

.PHONY: all check-toolchain clean install

all: check-toolchain $(TARGET)

check-toolchain:
	@command -v "$(firstword $(CC))" >/dev/null 2>&1 || { \
		echo "error: C compiler not found: $(firstword $(CC))" >&2; \
		echo "build in the target SDK, e.g. make CROSS_COMPILE=aarch64-linux-gnu-" >&2; \
		exit 127; \
	}

$(TARGET): crypto_ta_client.c | check-toolchain
	$(CC) $(CPPFLAGS) $(CFLAGS) $(LDFLAGS) -o $@ $< $(LDLIBS)

install: $(TARGET)
	install -D -m 0755 $(TARGET) $(DESTDIR)/home/zlg/app/bin/$(TARGET)
	install -D -m 0755 ../script/crypto_ta.sh $(DESTDIR)/home/zlg/app/scripts/crypto_ta.sh

clean:
	$(RM) $(TARGET)
