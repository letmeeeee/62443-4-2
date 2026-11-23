from pathlib import Path
stage=Path('/tmp/em1000-web-stage')
root=Path('/home/wx/WorkStation/ItemCode/62443-4-2/offline_packages/em1000_debian13_arm64_web_debs')
s=(stage/'setenv-original.sh').read_text()
# Keep custom device configuration when dpkg asks about a modified conffile.
s=s.replace('apt-get --yes --no-remove --no-install-recommends install "$@"','apt-get --yes --no-remove --no-install-recommends -o Dpkg::Options::=--force-confold install "$@"',1)
helper='install_offline_debs()\n'+s.split('install_offline_debs()\n',1)[1].split('\ninstall_compat_runtime()',1)[0]
header='''#!/bin/bash
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
'''
check_helper=helper.replace('apt-get --yes --no-remove --no-install-recommends -o Dpkg::Options::=--force-confold install "$@"','''if [ "$MODE" = check ]; then
        apt-get --simulate --no-remove --no-install-recommends install "$@"
    else
        apt-get --yes --no-remove --no-install-recommends -o Dpkg::Options::=--force-confold install "$@"
    fi''')
footer='''
mapfile -t packages < "$BUNDLE_DIR/requested-packages.txt"
install_offline_debs "$BUNDLE_DIR/debs" "${packages[@]}"
if [ "$MODE" = install ]; then
    ldconfig
    nginx -t
    curl --version
    log "Web runtime installed; check HTTPS with the certificate installer after provisioning identities"
else
    log "Offline dependency check passed; no packages installed"
fi
'''
(root/'install-web-runtime.sh').write_text(header+'\n'+check_helper+footer)
(root/'install-web-runtime.sh').chmod(0o755)
web_function='''install_web_runtime()
{
    log "Install Debian 13 ARM64 Nginx, curl and image/XML runtime libraries"
    local bundle="$WORK_DIR/web/offline_pkg"
    bash "$bundle/install-web-runtime.sh"
}

'''
s=s.replace('install_compat_runtime()\n',web_function+'install_compat_runtime()\n',1)
s=s.replace('    install_python_env\n    install_compat_runtime','    install_python_env\n    install_web_runtime\n    install_compat_runtime',1)
(stage/'setenv.sh').write_text(s)
mapping='''Ubuntu 20.04 ARM64 清单 -> Debian 13 trixie 对应项
curl -> curl
libcurl4 -> libcurl4t64
libgd3 -> libgd3
libjbig0 -> libjbig0
libjpeg-turbo8 + libjpeg8 -> libjpeg62-turbo
libnginx-mod-http-image-filter -> libnginx-mod-http-image-filter
libnginx-mod-http-xslt-filter -> libnginx-mod-http-xslt-filter
libnginx-mod-mail -> libnginx-mod-mail
libnginx-mod-stream -> libnginx-mod-stream
libtiff5 -> libtiff6
libwebp6 -> libwebp7
libxpm4 -> libxpm4
libxslt1.1 -> libxslt1.1
nginx-common -> nginx-common (all)
nginx-core -> nginx-core (all，Debian 元包，附带的模块由依赖解析下载)
nginx -> nginx (arm64，Debian 主程序)

下载 Debian 13 arm64/all 原生软件包，不混用 Ubuntu 20.04 的旧二进制。
包名变化按 Debian 组件用途对应；不声称新版库提供旧 SONAME（如 libtiff.so.5/libjpeg.so.8）。
Nginx 主程序、nginx-common、nginx-core 及所有 Nginx 模块来自同一版本，ABI 由 APT 验证。
每包的准确版本、架构、来源 URL 和 SHA256 见 manifest.json。
'''
(root/'package-mapping.txt').write_text(mapping)
(root/'README.txt').write_text('''适用：EM-1000 / Debian GNU/Linux 13 (trixie) / ARM64。
来源：Debian 官方 trixie、trixie-updates、trixie-security 签名仓库。
所有 Depends / Pre-Depends 按空 dpkg 状态解析；基础库也随包带齐。
APT 根据设备实际已安装状态选择依赖，不把目录内所有 deb 强制装一遍。

将整个目录复制到设备，或解压 em1000-web-runtime-debian13-arm64.tar.gz。
在解压出的 em1000-web-runtime-debian13-arm64 目录以 root 执行：

仅校验文件和模拟离线安装（不安装包）：
bash install-web-runtime.sh --check-only

正式离线安装：
bash install-web-runtime.sh

脚本仅使用临时 file: APT 仓库，不修改设备的联网源。
保留已修改的系统配置文件；安装包维护脚本可能启动/重启 Nginx。
不操作 NVMe 分区、数据库初始化或项目证书。
安装后验证 nginx -t 和 curl --version；HTTPS 身份由 install_keys_certs.py 单独安装。
设备已有项目部署成功时，只运行此补充包，不重跑 ENABLE_NVME_FORMAT=1 的 setenv.sh。
provenance/ 保存来源、签名索引、解析及验证记录；SHA256SUMS 用于传输完整性检查。
''')
print('Prepared standalone installer and full deployment script')
