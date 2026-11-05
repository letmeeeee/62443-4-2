# PC 通过 SSH 部署 LC400 证书

更新：2026-11-05。`device_deploy.py` 已改为 **PC 端程序**，通过 SSH/SFTP 操作设备。GUI 和 CLI 均在 PC 上运行，设备无需桌面或 tkinter。

流程：PC 建立可信 SSH 连接 → 设备生成三份独立 CSR → 下载到 PC → CA 工具签发 → PC 上传公开证书包 → 设备整包校验、导入 → 应用 HTTPS 并重启指定 tems。

## 1. 前提和发行包

- PC 源码运行需要 Python 3.8+、tkinter，安装 `python3 -m pip install -r provisioning/requirements-device.txt`。Windows 使用带 Tcl/Tk 的官方 Python。
- Linux PC 可直接使用 `LC400_Device_PC_linux-x86_64.tar.gz`，解压后运行 `LC400_Device_Deploy`；内含 Python、Tk 和 SSH 库，须保留同目录 app/、runtime/。
- 设备需已启用 SSH/SFTP，已有 Python 3.8+、OpenSSL、当前版本 app 配套脚本及 modbus_tee_identity。设备原 INI 已配置好；本工具不改 INI，也不负责安装 tems/app 主程序。
- 生成/导入以 SSH 登录用户（或选定 sudo 后的用户）执行，应与设备身份文件属主一致。最终应用 HTTPS 及服务重启需要 root；可用 root SSH，或具备免交互 sudo 的维护账号勾选“sudo -n”。工具不修改 sudoers，不把 SSH 口令转交 sudo。
- file/TEE 选择、设备目录、INI、tems 服务名沿用既有规则。切换工具 backend 不会持久修改 tems/app 服务环境，服务仍须配置一致。

PC 端不再依赖本机的设备路径、fcntl 或设备 C 辅助程序；这些代码只在远程 Linux 设备上执行。

## 2. SSH 身份认证与主机信任

支持三种认证来源：

1. 在 GUI 掩码字段输入 SSH 口令；只保留在当前窗口内存，不写磁盘或操作日志，可点击“清除当前窗口 SSH 口令”。
2. 选择 PC 上的 SSH 私钥，可填私钥解密口令。
3. 两者均未填写时使用已有 SSH Agent/默认用户密钥。

主机信任使用 PC 的 `~/.ssh/known_hosts`（可另选文件），或管理员核对过的完整 SSH 指纹。**不会自动信任未知主机，不会忽略已有主机密钥变化。**

GUI 的“探测 SSH 指纹”仅读取服务器公开主机密钥，尚未登录或信任，结果带 trusted:false。探测与正式连接共用相同的密钥选择规则，存在 known_hosts 时都会优先协商已记录的密钥类型。请先与设备管理员通过可信渠道核对，再填入 SSH 指纹字段。设备管理员可在设备本地查看：

```bash
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256
```

设备可能同时有 RSA、Ed25519、ECDSA 多种主机密钥，每一种都有独立指纹。探测返回 key_type（如 ssh-rsa、ssh-ed25519），请核对对应公钥；不要将 Ed25519 公钥指纹填给实际协商 RSA 的连接。可在设备本地列出 OpenSSH 主机公钥的全部指纹：

```bash
for key in /etc/ssh/ssh_host_*_key.pub; do
    [ -f "$key" ] && ssh-keygen -lf "$key" -E sha256
done
```

若报不匹配，新版错误会列出目标主机/端口、协商密钥类型、填写值和设备返回值。先确认 IP/端口正确，再在设备本地核对对应类型。只有核对相同后才更新输入；工具不会自动接受错误中显示的指纹，也不会自动删除 known_hosts。

指纹格式区别：

| 字段 | 格式与用途 |
|---|---|
| SSH 主机指纹 | `SHA256:...` Base64 格式，验证 SSH 服务器 |
| CA 根指纹 | 64 位十六进制（可含冒号），验证设备证书信任锚 |
| SSH 登录口令 | 登录设备用，与 CA 口令无关 |
| CA 口令 / 文件保护口令 | 仅用于 CA 管理软件，部署软件不会索取或上传 |

## 3. GUI 操作

PC 启动：

```bash
python3 device_deploy.py
# 或发行包：
./LC400_Device_Deploy
```

“SSH 连接”页填写设备 IP、端口、用户名，选择口令/私钥/Agent，并填已核对的主机指纹或选择已有 known_hosts。设备 Python 默认为 `/usr/bin/python3`，可改为设备实际绝对路径；无须在设备安装 Paramiko。

“设备路径与证书材料”页填写原有设备路径、backend、设备编号、PC CSR 输出新目录、PC 证书包目录、CA 根指纹及实际 tems 服务名。

依次操作：

1. **测试连接**：核对远程 hostname、uid、Python、设备配套文件、INI 是否存在。ready:false 表示还缺设备配套，不表示可部署；can_apply:false 表示当前用户不能执行需要 root 的最终应用。
2. **生成并下载 CSR**：三份 CSR 在设备本机生成；下载 master.csr、slave.csr、https.csr、manifest.json 到 PC 新目录。私钥留在设备文件/TEE 中。
3. 将 PC 上的 CSR 目录交给同 PC 或另一台管理电脑上的 CA 工具，得到公开证书包。
4. **预检证书包**：选择 PC 证书包，填可信根指纹；只上传固定公开文件，由设备检查 CA 链、用途、CSR 和本机私钥匹配及 IP。
5. **导入证书包**：明确确认后导入；保留原来的失败回滚与中断恢复机制，不自动重启。
6. **校验身份**：重新核验设备当前三类身份。
7. **应用并重启**：维护窗口确认后应用 Nginx；默认安装/刷新 HTTPS 定时服务，重启填写的实际 tems 服务。仍需真实业务/TLS 握手验收。

每个操作会新建 SSH 连接，执行完成即关闭；口令字段不自动保存配置。CA 签发较久时无须一直保持 SSH 连接。

## 4. CLI 完整调用例子

以下全部在 **PC** 执行，示例使用密钥认证。设备 IP、SSH 指纹、私钥路径、服务名和 CA 指纹需替换为真实值。不要原样使用占位符。

```bash
# 仅探测，结果须再独立核对；不会自动建立信任。
python3 device_deploy.py --host 192.168.2.136 probe

# 测试连接
python3 device_deploy.py --host 192.168.2.136 --user root \
  --identity ~/.ssh/lc400-maintenance \
  --host-fingerprint 'SHA256:设备SSH主机指纹' connect

# 在设备生成并下载到 PC 新目录
python3 device_deploy.py --host 192.168.2.136 --user root \
  --identity ~/.ssh/lc400-maintenance \
  --host-fingerprint 'SHA256:设备SSH主机指纹' \
  generate --device-id LC400-001 --out ./LC400-001-csr

# 仍在 PC，由 CA 软件审查/签发，口令交互输入。
python3 ca_manager.py --ca-dir /secure/company-ca \
  sign ./LC400-001-csr ./LC400-001-certificates --days 365

# 预检（设备执行校验，PC 上传公开包）
python3 device_deploy.py --host 192.168.2.136 --user root \
  --identity ~/.ssh/lc400-maintenance \
  --host-fingerprint 'SHA256:设备SSH主机指纹' \
  preview --bundle ./LC400-001-certificates --fingerprint 根CA完整十六进制SHA256

# 导入
python3 device_deploy.py --host 192.168.2.136 --user root \
  --identity ~/.ssh/lc400-maintenance \
  --host-fingerprint 'SHA256:设备SSH主机指纹' \
  import --bundle ./LC400-001-certificates --fingerprint 根CA完整十六进制SHA256

# 校验
python3 device_deploy.py --host 192.168.2.136 --user root \
  --identity ~/.ssh/lc400-maintenance \
  --host-fingerprint 'SHA256:设备SSH主机指纹' check

# 应用：actual-tems.service 必须替换为设备真实服务名
python3 device_deploy.py --host 192.168.2.136 --user root \
  --identity ~/.ssh/lc400-maintenance \
  --host-fingerprint 'SHA256:设备SSH主机指纹' \
  apply --tems-service actual-tems.service --confirm APPLY_AND_RESTART
```

口令认证改用全局 `--password`（不带口令值），程序使用 getpass 交互读取。加密 SSH 私钥需要交互解锁时加 `--key-passphrase`。已有 known_hosts 时可省略 --host-fingerprint；非22端口使用 --port。维护用户需要 sudo 时加 --sudo，失败时检查已配置的 sudo -n 权限。

多根 CA 使用重复 --fingerprint。只应用已有 HTTPS、不安装定时器时给 apply 添加 --no-install-timer。自定义 INI/HTTPS 路径时沿用原限制：默认定时服务不支持这些自定义路径，须由管理员维护对应服务环境。

## 5. 文件传输、失败及恢复

PC 每次仅上传临时执行代码到设备 `/tmp/lc400-pc-随机值/agent.pyz`，证书操作再上传固定公开包文件。目录0700，文件0600；完成后清理。设备运行标准库后端，无需永久安装 GUI 或新 Python 依赖。输入/返回均为有大小限制的 JSON，命令路径按参数引用，不拼接用户 shell 片段。

CSR 下载通过 SSH 通道只返回固定公开文件，不读取 master.key、slave.key、g3.key，也不导出 TEE 私钥。证书上传只接受 manifest、roots、intermediates 和三份叶证书；即便 PC 目录中另有私钥，也不会被上传。

网络中断/超时可能发生在设备已经修改文件或应用配置之后。工具不会自动重试导入/应用，也不会把连接断开当作“未执行”。重新连接后先 check；如果设备保留 deployment-recovery，则在服务停止的维护窗口确认后使用：

```bash
python3 device_deploy.py --host 192.168.2.136 --user root \
  --identity ~/.ssh/lc400-maintenance \
  --host-fingerprint 'SHA256:设备SSH主机指纹' \
  recover --confirm RESTORE_PUBLIC_CERTIFICATES
```

完整导入回滚及恢复边界见 README。临时目录因断线未能清理时显示 cleanup_warning；目录只含公开材料和代码，重连后可由设备管理员核查清理。该目录与设备持久化恢复记录不同，不应混淆。

## 6. 构建

```bash
python3 -m pip install -r provisioning/requirements-build.txt
python3 -m pip install -r provisioning/requirements-device.txt
python3 build_provisioning_executables.py --tool device
```

Linux 可添加 --ca-builder portable，直接打包当前 Python/Tk/SSH 运行时，无需下载 PyInstaller。输出 `LC400_Device_PC_linux-x86_64/LC400_Device_Deploy` 及 tar.gz。在 Windows x64 Python 环境执行同样的 --tool device，使用 PyInstaller 生成 Windows EXE/zip；不需要 ARM64 Python 或交叉编译器。

`python3 build_provisioning_tools.py` 同时提供 PC 的 device_deploy.pyz 和设备本地应急用 device_agent.pyz；本地维护源码入口保留为 device_local.py。可选旧式设备后端原生包使用 `--tool device-agent --device-arch aarch64` 构建。日常部署使用 PC 发行包，不再将 PC 程序复制到设备执行。

证书管理脚本统一放在 `exec/app/script/`，设备路径为 `/home/zlg/app/script/modbus_certs.py`。更新时整体复制 app 目录；PC SSH 工具也需使用匹配的新版本。`app/bin/modbus_tee_identity` 仍需放入对应设备架构的新版本二进制，整体复制 app 时保留该文件及设备运行配置、密钥。

CA 签发时会在完整证书包中自动生成 `deployment.json`，记录设备编号、根 CA SHA-256 和清单摘要，不包含私钥或口令。PC 工具点击“加载 CA 部署记录”，选择该文件，确认来源后自动填写证书包目录及根指纹，再执行预检、导入、校验。整个证书包可移动目录，记录无需修改。旧签发包可直接选择 `manifest.json`。加载时检查所有清单文件摘要及实际根证书指纹；该一致性检查不代替首次 CA 身份核对，需从可信 CA 端取得交付包。
