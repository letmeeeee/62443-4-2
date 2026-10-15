#!/bin/sh
# Import target public headers/runtime library into this checkout; no deployment.
set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
logger_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
sdk_dir="$logger_dir/.deps/optee-arm64"
device=''
header=''
library=''
check_only=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --device|--header|--library)
            [ "$#" -ge 2 ] || { echo "Missing argument: $1" >&2; exit 2; }
            case "$1" in
                --device) device=$2 ;;
                --header) header=$2 ;;
                --library) library=$2 ;;
            esac
            shift 2 ;;
        --check) check_only=1; shift ;;
        *) echo "usage: $0 --device root@HOST [--header REMOTE_PATH --library REMOTE_PATH] | --header FILE --library FILE | --check" >&2; exit 2 ;;
    esac
done
if [ "$check_only" -eq 1 ]; then
    [ -f "$sdk_dir/SHA256SUMS" ] || { echo "SDK missing: $sdk_dir" >&2; exit 1; }
    (cd "$sdk_dir" && sha256sum -c SHA256SUMS)
    exit 0
fi
[ ! -e "$sdk_dir" ] || { echo "SDK already exists: $sdk_dir; use --check. Move it aside before importing a replacement." >&2; exit 1; }
mkdir -p "$logger_dir/.deps"
staging=$(mktemp -d "$logger_dir/.deps/.optee-import.XXXXXX")
trap 'rm -rf -- "$staging"' EXIT HUP INT TERM
mkdir -p "$staging/include" "$staging/lib"
if [ -n "$device" ]; then
    case "$device" in -*|*:*|*/*) echo "Invalid device host" >&2; exit 2;; esac
    header=${header:-/usr/include/tee_client_api.h}
    library=${library:-/usr/lib/aarch64-linux-gnu/libteec.so.2.0.0}
    case "$header:$library" in /*:/*) ;; *) echo "Remote paths must be absolute" >&2; exit 2;; esac
    scp -- "$device:$header" "$staging/include/tee_client_api.h"
    scp -- "$device:$library" "$staging/lib/imported-library"
else
    [ -f "$header" ] && [ -f "$library" ] || { echo "Specify real --header and --library files" >&2; exit 2; }
    cp -- "$header" "$staging/include/tee_client_api.h"
    cp -- "$library" "$staging/lib/imported-library"
fi
grep -q TEEC_OpenSession "$staging/include/tee_client_api.h" || { echo "Not a real OP-TEE Client header" >&2; exit 1; }
if grep -q TEST_TEE_CLIENT_API_H "$staging/include/tee_client_api.h"; then
    echo "Test stub headers cannot be imported as a device SDK" >&2; exit 1
fi
LC_ALL=C readelf -h "$staging/lib/imported-library" > "$staging/elf-info"
grep -q 'Machine:.*AArch64' "$staging/elf-info" || { echo "Library is not AArch64" >&2; exit 1; }
if grep 'Machine:' "$staging/elf-info" | grep -v AArch64 >/dev/null; then
    echo "Library contains non-AArch64 objects" >&2; exit 1
fi
case "$library" in
    *.a) mv "$staging/lib/imported-library" "$staging/lib/libteec.a" ;;
    *)
        soname=$(LC_ALL=C readelf -d "$staging/lib/imported-library" | sed -n 's/.*(SONAME).*\[\([^]]*\)\].*/\1/p')
        case "$soname" in libteec.so|libteec.so.[0-9]*) ;; *) echo "Invalid/missing libteec SONAME: $soname" >&2; exit 1;; esac
        case "$soname" in */*|*' '*|*'..'*) echo "Invalid SONAME" >&2; exit 1;; esac
        mv "$staging/lib/imported-library" "$staging/lib/$soname"
        if [ "$soname" != libteec.so ]; then ln -s "$soname" "$staging/lib/libteec.so"; fi
        ;;
esac
rm -- "$staging/elf-info"
printf 'Source device: %s\nHeader: %s\nLibrary: %s\n' "$device" "$header" "$library" > "$staging/SOURCE.txt"
(cd "$staging" && sha256sum include/tee_client_api.h lib/libteec.* > SHA256SUMS)
mv -- "$staging" "$sdk_dir"
trap - EXIT HUP INT TERM
echo "Project OP-TEE Client SDK ready: $sdk_dir"
