#!/bin/sh
# Prepare target headers only; never install packages or replace runtime libraries.
set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
logger_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
sdk_dir="$logger_dir/.deps/openssl-arm64"
url='https://ports.ubuntu.com/ubuntu-ports/pool/main/o/openssl/libssl-dev_1.1.1f-1ubuntu2.24_arm64.deb'
sha='a664d282a0b19fb687c1b9f5a06abcf879bc5643c6e8be435f13c187d13a5b6a'
package=''
if [ "$#" -gt 0 ]; then
    if [ "$#" -ne 2 ] || [ "$1" != '--deb' ]; then
        echo "Usage: $0 [--deb /path/to/libssl-dev_1.1.1f-1ubuntu2.24_arm64.deb]" >&2
        exit 2
    fi
    package=$2
fi
if [ -d "$sdk_dir" ]; then
    if [ -f "$sdk_dir/SHA256SUMS" ] && (cd "$sdk_dir" && sha256sum -c SHA256SUMS >/dev/null); then
        echo "Target OpenSSL headers ready: $sdk_dir/include"
        exit 0
    fi
    echo "Existing SDK is incomplete: $sdk_dir; preserve/move it before preparing a fresh SDK." >&2
    exit 1
fi
mkdir -p "$logger_dir/.deps"
tmp=$(mktemp -d "$logger_dir/.deps/.openssl-XXXXXX")
trap 'rm -rf -- "$tmp"' EXIT HUP INT TERM
if [ -z "$package" ]; then
    package="$tmp/libssl-dev-arm64.deb"
    curl -fL --connect-timeout 15 --max-time 120 "$url" -o "$package"
fi
actual=$(sha256sum "$package")
actual=${actual%% *}
if [ "$actual" != "$sha" ]; then
    echo 'OpenSSL development package checksum mismatch; nothing installed.' >&2
    exit 1
fi
[ "$(dpkg-deb -f "$package" Architecture)" = arm64 ]
[ "$(dpkg-deb -f "$package" Package)" = libssl-dev ]
dpkg-deb -x "$package" "$tmp/extracted"
mkdir -p "$tmp/sdk/include"
cp -R "$tmp/extracted/usr/include/openssl" "$tmp/sdk/include/"
cp "$tmp/extracted/usr/include/aarch64-linux-gnu/openssl/opensslconf.h" "$tmp/sdk/include/openssl/"
printf '%s\n' "Source: $url" "Package SHA256: $sha" 'Architecture: arm64' > "$tmp/sdk/SOURCE.txt"
(cd "$tmp/sdk" && sha256sum include/openssl/*.h > SHA256SUMS)
mv "$tmp/sdk" "$sdk_dir"
echo "Target OpenSSL headers ready: $sdk_dir/include"
