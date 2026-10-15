#!/bin/sh
# Compatibility entry point: dependency preparation and build live in Makefile.
set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec make -C "$script_dir" "$@"
