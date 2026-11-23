#!/bin/sh
set -eu
case "${1:---simulate}" in
  --simulate) simulate=yes ;;
  --install) simulate=no ;;
  *) echo '用法: sh install.sh [--simulate|--install]' >&2; exit 2 ;;
esac
bundle_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "$(dpkg --print-architecture)" != arm64 ]; then
  echo '此包仅适用于 Debian 13 ARM64。' >&2
  exit 1
fi
. /etc/os-release
if [ "${ID:-}" != debian ] || [ "${VERSION_ID:-}" != 13 ]; then
  echo '此包仅适用于 Debian 13 ARM64。' >&2
  exit 1
fi
if [ "$simulate" = no ] && [ "$(id -u)" != 0 ]; then
  echo '实际安装请使用 sudo sh install.sh --install。' >&2
  exit 1
fi
(cd "$bundle_dir" && sha256sum -c SHA256SUMS)
apt_state=$(mktemp -d /tmp/em1000-offline-apt.XXXXXX)
trap 'rm -rf -- "$apt_state"' EXIT HUP INT TERM
mkdir -p "$apt_state/lists/partial" "$apt_state/archives/partial" "$apt_state/empty"
bundle_uri=$(printf '%s' "$bundle_dir" | sed 's/ /%20/g')
printf 'deb [trusted=yes] file:%s ./\n' "$bundle_uri" > "$apt_state/sources.list"
cat > "$apt_state/apt.conf" <<EOF
Dir::Etc::parts "$apt_state/empty";
Dir::Etc::main "$apt_state/no-system-config";
Dir::Etc::sourcelist "$apt_state/sources.list";
Dir::Etc::sourceparts "$apt_state/empty";
Dir::Etc::preferences "$apt_state/no-preferences";
Dir::Etc::preferencesparts "$apt_state/empty";
Dir::State::lists "$apt_state/lists";
Dir::State::status "/var/lib/dpkg/status";
Dir::Cache::archives "$apt_state/archives";
Dir::Cache::pkgcache "$apt_state/pkgcache.bin";
Dir::Cache::srcpkgcache "$apt_state/srcpkgcache.bin";
APT::Sandbox::User "$(id -un)";
APT::Install-Recommends "false";
APT::Install-Suggests "false";
Acquire::Languages "none";
EOF
export APT_CONFIG="$apt_state/apt.conf"
apt-get update
set --
while IFS= read -r package; do
  [ -z "$package" ] || set -- "$@" "$package"
done < "$bundle_dir/requested-packages.txt"
if [ "$simulate" = yes ]; then
  apt-get --simulate --no-install-recommends --no-remove install "$@"
else
  apt-get --no-install-recommends --no-remove install "$@"
  python3.13 --version
  python3.13 -m pip --version
  sshpass -V
fi
