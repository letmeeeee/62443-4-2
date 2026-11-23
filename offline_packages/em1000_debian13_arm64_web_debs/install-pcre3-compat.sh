#!/bin/bash
set -Eeuo pipefail
BUNDLE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
err() { echo "[ERROR] $*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || err "Run as root"
[ "$(dpkg --print-architecture)" = arm64 ] || err "ARM64 is required"
. /etc/os-release
[ "$ID" = debian ] && [ "$VERSION_ID" = 13 ] || err "Debian 13 is required"
case "${1:-}" in
    --check-only|"") ;;
    *) err "Usage: bash install-pcre3-compat.sh [--check-only]" ;;
esac
[ "$#" -le 1 ] || err "Too many arguments"
deb="$BUNDLE_DIR/debs/libpcre3_8.39-15_arm64.deb"
[ -f "$deb" ] || err "Missing $deb"
printf '%s  %s\n' ffff38112e92b032688c0efdc19673686feb2aff8b85f65f54d9f2f6b55992d9 "$deb" | sha256sum -c -
libc_version=$(dpkg-query -W -f='${Version}' libc6:arm64)
dpkg --compare-versions "$libc_version" ge 2.34 || err "libc6 >= 2.34 is required"
current=$(dpkg-query -W -f='${Version}' libpcre3:arm64 2>/dev/null || true)
if [ -n "$current" ] && dpkg --compare-versions "$current" gt 2:8.39-15; then
    err "A newer libpcre3 is installed; preserve it and inspect its files"
fi
if [ "${1:-}" = --check-only ]; then
    echo "[INFO] PCRE3 package checksum and target dependency checks passed; no changes made"
    exit 0
fi
dpkg -i "$deb"
ldconfig
# Keep the existing Nginx executable and configuration, then verify/restart it.
/usr/sbin/nginx -t
systemctl restart nginx.service
systemctl is-active --quiet nginx.service
echo "[INFO] libpcre.so.3 compatibility library installed; existing Nginx is active"
