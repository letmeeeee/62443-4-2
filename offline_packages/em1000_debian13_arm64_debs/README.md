# EM-1000 Debian 13 ARM64 系统离线包

适用设备：EM-1000，Debian GNU/Linux 13（trixie），dpkg 架构 arm64。
按设备发行版提供 Python 3.13，以及 venv、pip 和 sshpass。

对应原来提供的 Ubuntu 包名：

| 原包 | 本包对应 Debian 包 |
| --- | --- |
| libpython3.8 | libpython3.13 |
| libpython3.8-minimal | libpython3.13-minimal |
| libpython3.8-stdlib | libpython3.13-stdlib |
| python3.8 | python3.13 |
| python3.8-minimal | python3.13-minimal |
| python3.8-venv | python3.13-venv |
| python-pip-whl | python3-pip-whl |
| sshpass | sshpass |

额外包含 python3、python3-venv、python3-pip，使系统入口和 pip 命令可用。
完整精确版本、文件 SHA-256、架构和上游下载地址见 manifest.json。

## 下载范围与验证

从 Debian 官方 trixie、trixie-updates、trixie-security 仓库下载当前可用版本。
仓库维护版本可能高于设备显示的 Debian 13.6；包仍属于 Debian 13，实际需要
更新的关联组件请查看设备模拟安装结果。
APT 使用 Debian 13 官方归档公钥验证仓库签名，并校验下载内容。
下载阶段使用独立的 arm64 APT 状态和空 dpkg 状态，以收集 Depends/Pre-Depends
依赖；不使用下载电脑已安装的软件包抵消依赖，不包含可选 Recommends/Suggests。
因此 debs/ 里也包含 libc6、OpenSSL 等系统依赖。安装脚本会根据目标机已安装的版本
解析实际需求，避免要求安装目录中所有包。设备的具体安装状态尚未读取；如有本地
定制包、hold 或不同版本的关联包，仍需以设备上的模拟结果为准。

provenance/ 保存下载日志、签名 InRelease、官方公钥和下载配置。
validation.json 保存架构、上游哈希、deb 文件结构和离线依赖解析验证结果。
下载与验证均未在本机安装任何软件包，尚未在 EM-1000 上执行安装。

## 设备离线安装

将 em1000_debian13_arm64_debs.tar.gz 传到设备后执行：

```sh
tar -xzf em1000_debian13_arm64_debs.tar.gz
cd em1000_debian13_arm64_debs
sha256sum -c SHA256SUMS
sudo sh install.sh --simulate
sudo sh install.sh --install
```

安装脚本只读取包内的 file: APT 仓库，使用设备实际 dpkg 状态解析依赖。
APT 配置和索引位于临时目录，不修改设备的软件源配置；实际安装仍通过正常 dpkg
安装流程更新设备的软件包数据库，并运行软件包维护脚本。
脚本禁止自动删除已有软件包；安装步骤保留 APT 的交互确认，可核对升级列表。
包来自 Debian 官方签名仓库；本地 Packages 索引使用 trusted=yes，信任建立在
包内 SHA256SUMS 与下载时的上游签名及 SHA-256 验证之上。

## 使用 Python wheel 离线包

在需要的新虚拟环境中安装此前准备的 Python 依赖，示例：

```sh
python3.13 -m venv /home/zlg/myenv-new
sh /实际路径/em1000_py313_aarch64/install.sh /home/zlg/myenv-new/bin/python3
```

请使用实际服务解释器路径或新建目录；已有虚拟环境无需再次创建。
此 deb 包不包含之前的应用 wheel 包，不修改服务解释器配置、不重启服务。
