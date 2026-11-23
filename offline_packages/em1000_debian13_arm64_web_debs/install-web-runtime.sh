#!/bin/bash
set -Eeuo pipefail
BUNDLE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
log() { echo "[INFO] $*"; }
err() { echo "[ERROR] $*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || err "Run as root"
[ "$(dpkg --print-architecture)" = arm64 ] || err "ARM64 is required"
. /etc/os-release
[ "$ID" = debian ] && [ "$VERSION_ID" = 13 ] || err "Debian 13 is required"
MODE=install
case "${1:-}" in
    --check-only) MODE=check ;;
    "") ;;
    *) err "Usage: bash install-web-runtime.sh [--check-only]" ;;
esac
[ "$#" -le 1 ] || err "Too many arguments"
(cd "$BUNDLE_DIR" && sha256sum -c SHA256SUMS)

validate_removal_plan()
{
    local plan=$1 index=$2 action name rest replacement
    while read -r action name rest; do
        [ "$action" = Remv ] || continue
        name=${name%%:*}
        case "$name" in
            libcurl4) replacement=libcurl4t64 ;;
            libgeoip1) replacement=libgeoip1t64 ;;
            libgnutls30) replacement=libgnutls30t64 ;;
            libnettle8) replacement=libnettle8t64 ;;
            libhogweed6) replacement=libhogweed6t64 ;;
            libpsl5) replacement=libpsl5t64 ;;
            libssh2-1) replacement=libssh2-1t64 ;;
            libssl3) replacement=libssl3t64 ;;
            libpng16-16) replacement=libpng16-16t64 ;;
            libelf1) replacement=libelf1t64 ;;
            libtirpc3) replacement=libtirpc3t64 ;;
            libdb5.3) replacement=libdb5.3t64 ;;
            *) err "Unexpected removal in offline repair plan: $name; no packages changed" ;;
        esac
        grep -Fx "Package: $replacement" "$index" >/dev/null ||
            err "Replacement package is missing from offline bundle: $replacement"
        # The proposed solution must actually install/reinstall the replacement.
        awk -v wanted="$replacement" '$1 == "Inst" {split($2, n, ":"); if (n[1] == wanted) found=1} END {exit !found}' "$plan" ||
            err "Removal of $name has no replacement installation in the plan"
        log "Allowed package transition: $name -> $replacement"
    done < "$plan"
}

install_offline_debs()
(
    # Resolve selected offline packages against the device's actual status.
    local deb_dir=$1 repo deb metadata package version nginx_version="" requested
    local -a nginx_packages=() targets=()
    shift
    [ "$#" -gt 0 ] || err "No offline packages requested"
    repo=$(mktemp -d /tmp/em1000-apt.XXXXXX)
    trap 'rm -rf -- "$repo"' EXIT
    mkdir -p "$repo/debs" "$repo/lists/partial" "$repo/archives/partial" "$repo/empty"
    : > "$repo/Packages"
    for deb in "$deb_dir"/*.deb; do
        [ -f "$deb" ] || err "No offline debs in $deb_dir"
        ln -s "$deb" "$repo/debs/$(basename "$deb")"
        metadata=$(dpkg-deb --field "$deb")
        package=${deb##*/}
        package=${package%%_*}
        case "$package" in
            nginx|nginx-common|nginx-core|libnginx-mod-*)
                version=$(sed -n 's/^Version: //p' <<< "$metadata")
                [ -n "$version" ] || err "Missing version: $deb"
                if [ -n "$nginx_version" ] && [ "$version" != "$nginx_version" ]; then
                    err "Nginx/module version mismatch in offline bundle"
                fi
                nginx_version=$version
                nginx_packages+=("$package=$version") ;;
        esac
        printf '%s\nFilename: debs/%s\nSize: %s\nSHA256: %s\n\n' \
            "$metadata" "$(basename "$deb")" "$(stat -c %s "$deb")" \
            "$(sha256sum "$deb" | cut -d ' ' -f 1)" >> "$repo/Packages"
    done
    printf 'deb [trusted=yes] file:%s ./\n' "$repo" > "$repo/sources.list"
    cat > "$repo/apt.conf" <<EOF
Dir::Etc::parts "$repo/empty";
Dir::Etc::main "$repo/no-system-config";
Dir::Etc::sourcelist "$repo/sources.list";
Dir::Etc::sourceparts "$repo/empty";
Dir::Etc::preferences "$repo/no-preferences";
Dir::Etc::preferencesparts "$repo/empty";
Dir::State::lists "$repo/lists";
Dir::State::status "/var/lib/dpkg/status";
Dir::Cache::archives "$repo/archives";
Dir::Cache::pkgcache "$repo/pkgcache.bin";
Dir::Cache::srcpkgcache "$repo/srcpkgcache.bin";
APT::Sandbox::User "root";
APT::Install-Recommends "false";
Acquire::Languages "none";
EOF
    [ "${#nginx_packages[@]}" -gt 0 ] || err "No Nginx packages in offline bundle"
    for requested in "$@"; do
        case "$requested" in
            nginx|nginx-common|nginx-core|libnginx-mod-*) ;;
            *) targets+=("$requested") ;;
        esac
    done
    targets+=("${nginx_packages[@]}")
    export APT_CONFIG="$repo/apt.conf"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    # First repair the existing dependency graph without requested package arguments.
    # Then validate the requested install against a projected temporary status.
    local plan projected
    export LC_ALL=C
    plan="$repo/repair-plan.log"
    if ! apt-get --simulate --fix-broken --no-install-recommends install > "$plan" 2>&1; then
        cat "$plan"
        err "Offline dependency repair cannot be resolved; no packages changed"
    fi
    cat "$plan"
    validate_removal_plan "$plan" "$repo/Packages"
    projected="$repo/projected-status"
    python3 "$BUNDLE_DIR/project-status.py" /var/lib/dpkg/status "$repo/Packages" "$plan" "$projected"
    if ! apt-get -o Dir::State::status="$projected" \
        -o Dir::Cache::pkgcache="$repo/projected-pkgcache.bin" \
        -o Dir::Cache::srcpkgcache="$repo/projected-srcpkgcache.bin" \
        --simulate --reinstall --no-remove --no-install-recommends \
        install "${targets[@]}" > "$repo/install-plan.log" 2>&1; then
        cat "$repo/install-plan.log"
        err "Requested packages cannot be installed after repair; no packages changed"
    fi
    cat "$repo/install-plan.log"
    if [ "$MODE" = check ]; then
        log "Offline repair and installation plans validated; no packages changed"
    else
        apt-get --yes --fix-broken --no-install-recommends \
            -o Dpkg::Options::=--force-confold install
        apt-get --yes --reinstall --no-remove --no-install-recommends \
            -o Dpkg::Options::=--force-confold install "${targets[@]}"
    fi

)

mapfile -t packages < "$BUNDLE_DIR/requested-packages.txt"
install_offline_debs "$BUNDLE_DIR/debs" "${packages[@]}"
if [ "$MODE" = install ]; then
    ldconfig
    /usr/sbin/nginx -t
    /usr/bin/curl --version
    systemctl restart nginx.service
    systemctl is-active --quiet nginx.service
    log "Web runtime installed; check HTTPS with the certificate installer after provisioning identities"
else
    log "Offline dependency check passed; no packages installed"
fi
