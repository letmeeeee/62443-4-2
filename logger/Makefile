# Single build entry point. Source files/toolchain/libraries live in CMakeLists.txt.
MAKEFLAGS += --no-print-directory
LOGGER_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
BUILD_DIR ?= $(LOGGER_DIR)/build
CMAKE ?= cmake
CMAKE_ARGS ?=
OPENSSL_DEB ?=
OPENSSL_INCLUDE_DIR ?=

.DEFAULT_GOAL := all
.PHONY: all build configure prepare clean

all: build

build: configure
	+$(CMAKE) --build "$(BUILD_DIR)"

configure: prepare
	$(CMAKE) -S "$(LOGGER_DIR)" -B "$(BUILD_DIR)" \
		-DMODBUS_OPENSSL_INCLUDE_DIR="$(OPENSSL_INCLUDE_DIR)" $(CMAKE_ARGS)

prepare:
ifneq ($(strip $(OPENSSL_INCLUDE_DIR)),)
	@echo "Using target OpenSSL SDK: $(OPENSSL_INCLUDE_DIR)"
else ifneq ($(strip $(OPENSSL_DEB)),)
	sh "$(LOGGER_DIR)/scripts/prepare_openssl_headers.sh" --deb "$(OPENSSL_DEB)"
else
	sh "$(LOGGER_DIR)/scripts/prepare_openssl_headers.sh"
endif

# Cleaning never downloads dependencies or configures a fresh build directory.
clean:
	@if [ -f "$(BUILD_DIR)/CMakeCache.txt" ]; then \
		$(CMAKE) --build "$(BUILD_DIR)" --target clean; \
	else \
		echo "No configured build to clean: $(BUILD_DIR)"; \
	fi
