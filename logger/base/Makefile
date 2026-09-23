# Compatibility entry only; all build rules are maintained in ../Makefile/CMakeLists.txt.
MAKEFLAGS += --no-print-directory
LOGGER_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
.DEFAULT_GOAL := all
.PHONY: all build configure prepare clean
all build configure prepare clean:
	+$(MAKE) -C "$(LOGGER_DIR)" $@
