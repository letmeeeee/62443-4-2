适用：EM-1000 / Debian GNU/Linux 13 (trixie) / ARM64。
来源：原有 99 个原生包来自 Debian 官方 trixie、trixie-updates、trixie-security 签名仓库。
新增兼容库 libpcre3_8.39-15_arm64.deb 来自 Debian 12 bookworm，按官方 HTTPS 元数据 SHA256 校验。
该兼容库仅依赖 libc6 >= 2.34，目标 Debian 13 的 glibc 2.41 满足；不会启用 bookworm 软件源。
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
安装时按包内版本重新安装 Nginx 主程序、nginx-common、nginx-core 及全部配套模块，
同时重新安装请求清单中的库，修复 dpkg 记录相同版本但实际文件被旧程序覆盖的情况。
不强制重装全部 99 个依赖；其余依赖仍按设备实际状态解析。
安装后验证 /usr/sbin/nginx -t 和 /usr/bin/curl --version，并重启、检查 nginx.service。
HTTPS 身份由 install_keys_certs.py 单独安装。
设备已有项目部署成功时，只运行此补充包，不重跑 ENABLE_NVME_FORMAT=1 的 setenv.sh。
provenance/ 保存来源、签名索引、解析及验证记录；SHA256SUMS 用于传输完整性检查。

修复当前旧 Nginx 缺 libpcre.so.3（保留现有 Nginx）：
bash install-pcre3-compat.sh --check-only
bash install-pcre3-compat.sh

该脚本仅安装 libpcre3，验证并重启现有 Nginx，不更换 Nginx 主程序或模块。
默认 install-web-runtime.sh 仍执行完整的 Debian 13 Web 组件部署，并一并安装 libpcre3 兼容库。
libpcre2-8-0 和 libpcre3 均保留：分别为 PCRE2 与 PCRE1 消费者提供真实运行库，不建立伪兼容符号链接。

混装/中断安装恢复：
install-web-runtime.sh 在同一个离线仓库中使用 --fix-broken 解析并先模拟验证。
允许将 libcurl4 等已列明的旧包替换为包内对应 t64 库，并要求计划确实安装替代包。
若 APT 计划移除业务程序或任何白名单以外的软件包，脚本在实际安装前退出并打印计划。
无需执行使用联网源的 apt --fix-broken install，也不使用 dpkg --force-depends。
--check-only 会展示相同的修复计划，但不执行安装或移除。
修复采用两阶段：先模拟无包名的 apt-get --fix-broken install，再用临时投影的包状态验证目标安装。
正式安装前两阶段都须通过；投影文件仅用于模拟，绝不覆盖 /var/lib/dpkg/status。
