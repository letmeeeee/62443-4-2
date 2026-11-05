# 企业内部 CA 与设备首次证书部署

项目根目录提供两套管理工具，以及设备本地应急后端：

- `ca_manager.py`：管理电脑上的离线 CA，GUI/CLI；生成加密的根 CA 和签发 CA，签发设备三证书包，查询记录、吊销并导出 CRL。
- `device_deploy.py`：PC 端 SSH 部署 GUI/CLI；通过 SSH 在设备生成三份 CSR 并下载到 PC，将 PC 上签发证书包上传至设备预检/导入，远程校验、应用 HTTPS 和重启 tems。
- `device_local.py`：保留的设备本地应急维护后端；日常使用 PC 工具，无需设备桌面。

**当前推荐使用 PC SSH 方式**，完整连接设置、GUI 操作和调用例子见 [SSH_DEPLOY.md](SSH_DEPLOY.md)。原有设备本地流程下文仅作为应急维护说明。

INI 已存在且正确，本软件只读其配置。支持当前 file/TEE 两种 Modbus 私钥后端；HTTPS 私钥仍为文件。CA 不接触任何设备私钥；设备不接触 CA 私钥。

## 1. 安装、启动与分发

CA 管理电脑使用 Python 3.8+，安装依赖：

```bash
python3 -m pip install -r provisioning/requirements-ca.txt
python3 ca_manager.py
```

GUI 使用 tkinter：Windows 官方 Python 安装时选择 Tcl/Tk，Linux 安装发行版的 python3-tk。GUI 在后台线程进行密钥生成/部署，操作完成前禁止退出；CA 口令不以明文写入配置、日志或命令行参数，可保存为独立保护口令加密的 .lcvault 文件。关闭程序后可重新读取口令文件，也可手动输入 CA 口令。

PC SSH 工具源码运行需安装 `provisioning/requirements-device.txt`，GUI 使用 PC 的 tkinter。设备需启用 SSH/SFTP，并已有 Python 3.8+、OpenSSL 1.1.1+、app 配套脚本和本次构建的 `modbus_tee_identity`。设备不需要 GUI、Paramiko 或新 Python 包，远程后端仅用标准库。HTTPS 应用还依赖 Nginx、systemd 和 root 权限。

生成只含代码的单文件 Python 发行包：

```bash
python3 build_provisioning_tools.py
# 输出：provisioning/build-output/ca_manager.pyz
#       provisioning/build-output/device_deploy.pyz（PC SSH 客户端）
#       provisioning/build-output/device_agent.pyz（设备本地应急后端）
```

管理电脑运行 `ca_manager.pyz` 和 `device_deploy.pyz`；无需将 PC 客户端复制到设备，临时后端会通过 SSH 自动上传。只有需要本地应急维护时才将 `device_agent.pyz` 复制到设备，例如 `/home/zlg/device_agent.pyz`。不要复制 CA 数据目录到设备。运行方式为 `python3 程序.pyz`，CLI 参数与 .py 源码相同。Python zipapp 不打包解释器、Tk 或 cryptography，仍需安装对应运行环境。源码直接部署时，复制根启动脚本及 provisioning 包，保持相对目录结构。

## 2. CA 初始化与保管

GUI 指定一个空 CA 数据目录、企业名称，点击“初始化 CA”，输入并确认至少 12 位口令。默认根 CA RSA-4096/10 年、签发 CA RSA-4096/5 年；设备叶证书默认 365 天，可选 1–825 天，不能超过签发 CA 到期时间。

CLI 等价操作（口令交互输入）：

```bash
python3 ca_manager.py --ca-dir /secure/company-ca init --name 'Example Company'
python3 ca_manager.py --ca-dir /secure/company-ca fingerprint
```

数据目录内容：

| 文件 | 含义 |
|---|---|
| root-key.pem | PKCS#8 口令加密根私钥；只在初始化生成签发 CA 时使用 |
| issuer-key.pem | PKCS#8 口令加密签发私钥；设备证书和 CRL 由它签发 |
| roots.pem | 根证书（公开） |
| intermediates.pem | 签发 CA 中间证书（公开） |
| ledger.sqlite3 | 签发、吊销、CRL 编号和操作记录；记录当前 OS 操作账号 |

POSIX 下目录要求 0700，私钥和数据库为 0600。Windows 下用操作系统 ACL 将目录限制到 CA 管理员，单独配置磁盘加密。程序为单机离线 CA，授权依赖管理员工作站账号和 CA 口令，不包含网络服务或多人审批系统。根证书的自签名是标准信任锚；设备三张身份证书均由签发 CA 签发。

若初始化被中断，目录会保留 .initializing，工具拒绝使用不完整 CA；核查并保全目录后，在新的空目录重新初始化，不混用其中零散文件。

初始化完成后以及每批签发/吊销后，关闭程序，使用企业受控离线介质备份**整个 CA 目录**，包含数据库与加密私钥；单独保管口令并验证备份可读取。若保存了 .lcvault 文件且仍记得其保护口令，可读取恢复 CA 口令；若 CA 口令及可用的口令文件/保护口令都丢失，则无法恢复私钥。不要只备份公开根证书。应用未实现根/签发 CA 轮换向导、HSM、多管理员权限或在线 OCSP；CA 到期前需规划新 CA 和设备根信任切换。签发记录先提交再交付，若文件输出失败，数据库仍保留已分配序列号和证书用于追溯；重试到新目录会产生新一批证书。


### 2.1 CA 口令生成、加密保存和读取

GUI 新增五个按钮：

| 操作 | 行为 |
|---|---|
| 生成并加密保存 | 为新 CA 生成 43 字符随机口令（256 位随机源），选择新的 .lcvault 文件，设置并确认独立保护口令，保存后载入当前会话 |
| 保存现有 CA 口令 | 输入已有 CA 口令；已初始化 CA 会先验证私钥能解密，再保存加密口令文件 |
| 读取口令文件 | 输入文件保护口令，解密并载入口令；已有 CA 还会验证它是否匹配本机私钥 |
| 查看已载入口令 | 在独立窗口中查看，默认掩码显示，勾选“显示口令”后可见；不输出到操作日志 |
| 清除会话口令 | 清除工具保存的会话引用；后续操作需重新载入或手动输入 |

**新 CA 推荐顺序**：选择空 CA 数据目录 → 生成并加密保存 → 初始化 CA。保存成功后初始化会直接使用当前会话口令，不必抄写随机字符串。下次打开程序，选择同一 CA 目录 → 读取口令文件 → 输入文件保护口令 → 签发/吊销/导出 CRL。切换 CA 目录会清除已载入的会话口令，避免误用。

**已有 CA** 使用“保存现有 CA 口令”，不要点击生成来替换口令。生成按钮不会改变已有加密私钥；此版本仍不提供 CA 私钥口令轮换。

.lcvault 使用 scrypt（N=131072、r=8、p=1，约128 MiB内存）派生密钥和 AES-256-GCM 认证加密，每次保存使用随机盐和 nonce。文件保护口令为 12–1024 字符，必须与 CA 口令不同；不保存保护口令本身。CA 口令文件同样限制为 12–1024 字符。文件损坏、篡改或保护口令错误都会拒绝读取。

口令文件必须保存在 CA 数据目录之外，不覆盖已有文件；POSIX 创建权限为0600，Windows 按操作系统 ACL 保护保存目录。完整 CA 数据、.lcvault 文件及保护口令分别备份/保管。保护口令可保存在企业密码管理器中，不能放在口令文件旁。丢失保护口令时，仍可使用另行保存的原始 CA 口令；两者均无可用备份时无法找回。

CLI 也支持，所有口令均交互输入，不以参数、环境变量或命令输出传递：

```bash
# 新建随机 CA 口令并加密保存；程序会要求设置并确认独立文件保护口令。
python3 ca_manager.py --ca-dir /secure/company-ca password-generate \
  --out /secure/password-backups/company-ca.lcvault

# 用已保存的口令初始化 CA；交互输入文件保护口令。
python3 ca_manager.py --ca-dir /secure/company-ca \
  --vault-file /secure/password-backups/company-ca.lcvault init --name 'Example Company'

# 已有 CA：保存现有口令；先输入现有 CA 口令，再设置文件保护口令。
python3 ca_manager.py --ca-dir /secure/company-ca password-save \
  --out /secure/password-backups/company-ca-existing.lcvault

# 验证文件可读取；只输出验证状态，不输出口令明文。
python3 ca_manager.py --ca-dir /secure/company-ca \
  --vault-file /secure/password-backups/company-ca.lcvault password-check

# 使用文件中保存的 CA 口令签发。
python3 ca_manager.py --ca-dir /secure/company-ca \
  --vault-file /secure/password-backups/company-ca.lcvault \
  sign ./LC400-001-csr ./LC400-001-certificates --days 365
```

请先创建用于保存口令文件的受控目录。新 CA 的口令文件与所选 CA 路径绑定；已初始化 CA 的备份移动目录后，验证其私钥能解密即可重新读取。命令中的 ca_manager.py 可替换为发行包中的可执行程序路径。

## 3. 设备本地应急流程：导 CSR → CA 签发 → 导入与应用

日常在 PC 使用 device_deploy.py，通过 SSH 自动完成以下设备操作，见 [SSH_DEPLOY.md](SSH_DEPLOY.md)。本节命令仅供设备本机维护。

### 3.1 设备生成三份 CSR

以下命令均在设备本机执行。默认 app 为 `/home/zlg/app`，INI 为 `/home/zlg/lc_data_set.ini`；软件不改 INI。默认身份目录为 `/etc/ems/modbus`、`/etc/ssl/g3`。

```bash
sudo python3 /home/zlg/device_agent.pyz --backend file generate \
  --device-id LC400-001 --out /tmp/LC400-001-csr
```

运行用户应与现有文件私钥的属主一致；默认首次引导按 root 维护。设备正式运行服务也必须能够按项目既有私钥所有权/权限规则读取对应密钥。不能让不同账号各自生成同一路径的身份。

本地后端 GUI 对应填写设备编号、CSR 输出新目录，点击“1 生成/导出三份 CSR”；PC 工具点击“生成并下载 CSR”，输出位置在 PC。输出目录必须不存在，防止覆盖已有交接材料。

- master CSR 的 CN 为 `设备编号-master`，EKU clientAuth。
- slave CSR 的 CN 为 `设备编号-slave`，EKU serverAuth，IP SAN 使用现有 `[HTTPS] device_ips` 全部地址，确保覆盖常用访问网口。实际 Modbus 连接 IP 必须位于已有设备访问 IP 配置中；本工具不修改 INI。若两类地址不同，请先通过既有配置维护流程确认地址，再生成交接包。
- HTTPS CSR CN 为 logger，IP SAN 使用现有配置，EKU serverAuth。
- 自动核对三种公钥互不相同。存在私钥时复用；已有身份/CSR 却丢失私钥时失败。

输出目录仅含 `master.csr`、`slave.csr`、`https.csr` 和 `manifest.json`，将整个目录传给 CA 管理员。传输可使用企业现有 SFTP 或移动介质；本工具不自动连接设备 SSH，也不修改网口、INI 或服务环境。

选择 TEE 时改为 `--backend tee`。必须已部署支持 TEE 的 tems/辅助程序和匹配 TA；tems、app 后端、部署工具均配置同一后端。该参数只选择本次进程环境，不持久化服务配置，也不迁移旧后端私钥。切换已有身份到全新后端需使用现有辅助程序显式 ensure 对应角色，然后重新申请证书；工具不会悄悄替换丢失的身份。

### 3.2 管理电脑审查并签发

GUI 指定收到的 CSR 目录，点击“预览 CSR”，核对设备归属、CN、IP。设置证书输出新目录及有效期，点击“签发三证书包”，确认身份并输入 CA 口令。

```bash
python3 ca_manager.py --ca-dir /secure/company-ca inspect ./LC400-001-csr
python3 ca_manager.py --ca-dir /secure/company-ca sign \
  ./LC400-001-csr ./LC400-001-certificates --days 365
```

程序检查 CSR 自身签名、SHA-256 及以上签名、RSA 至少 3072 位、CN、SAN、CA 权限和 EKU，拒绝未知扩展、跨角色/跨设备复用公钥以及已因密钥泄露吊销的公钥。签发时明确 CA:FALSE、digitalSignature/keyEncipherment；master 仅 clientAuth，slave/HTTPS 仅 serverAuth，不签双用途叶证书。

证书包包含 `roots.pem`、`intermediates.pem`、`master-leaf.pem`、`slave-leaf.pem`、`https-leaf.pem`、`manifest.json`，没有任何私钥。将整个目录带回设备。同时通过独立可信渠道将 CA GUI 显示的完整根 SHA-256 指纹交给设备管理员。交接 manifest 用于摘要校验；其内自带指纹不作为信任依据。

### 3.3 设备预检、导入

```bash
# 将占位符替换为从可信渠道确认的完整根 SHA-256 指纹
sudo python3 /home/zlg/device_agent.pyz --backend file preview \
  --bundle /tmp/LC400-001-certificates --fingerprint ROOT_SHA256

sudo python3 /home/zlg/device_agent.pyz --backend file import \
  --bundle /tmp/LC400-001-certificates --fingerprint ROOT_SHA256

sudo python3 /home/zlg/device_agent.pyz --backend file check
```

多根时重复传 --fingerprint。GUI 的对应字段以逗号分隔，点击“2 预检证书包”“3 导入证书包”“4 本机校验”。

预检在写入前验证根指纹、文件摘要、完整有序链、有效期、EKU、CSR 的 CN/SAN/公钥、当前配置 HTTPS IP、三角色独立性，并用真实密钥做持钥验证。所有三张都通过才开始导入；Modbus 私钥证明调用生产 C 辅助程序，TEE 私钥不导出。

普通导入失败自动恢复导入前的根与三份公开身份证书及 HTTPS 待应用标记，私钥保持不变；不回滚设备业务数据。导入本身不启动/重启服务。更新期间不要并行运行其他证书维护程序。

若掉电/进程被杀导致 `/etc/ems/modbus/deployment-recovery/` 留下记录，工具拒绝再次导入/应用。先保持服务停止，核查记录，然后显式恢复到导入前公开文件：

```bash
sudo python3 /home/zlg/device_agent.pyz --backend file recover \
  --confirm RESTORE_PUBLIC_CERTIFICATES
```

恢复完成后重新导入。若恢复 manifest 尚未写完、文件缺失、配置路径已变化或磁盘仍不可写，工具停止并报错；由设备管理员核查目录和文件，不直接删除恢复记录继续应用。断电恢复只处理导入前的证书文件，不能撤回已经运行的 Nginx/tems 配置。

### 3.4 应用及首次安装 HTTPS 定时服务

先确认设备处于维护窗口，并确认 tems 和 app 服务环境都已配置正确密钥后端。以下服务名是示例，必须替换为设备实际 tems 单元名：

```bash
sudo python3 /home/zlg/device_agent.pyz --backend file apply \
  --tems-service actual-tems.service --confirm APPLY_AND_RESTART
```

GUI 填写实际服务名，点击“5 应用并重启”。工具会重新校验全部身份，检查 tems 单元 Environment 中 MODBUS_KEY_BACKEND 和 LC_INI_PATH 是否与工具一致，然后调用现有 enable_https.sh --install-service 刷新 HTTPS 脚本副本、Nginx 和每日 timer，最后重启指定 tems 并检查 active。

若服务通过 EnvironmentFile/启动脚本设置变量，应将这两个关键配置显式放到 systemd Environment 中以便核验；工具不猜测其他启动器的环境。不填写变量时仅接受项目默认 file 后端和默认 INI 路径。程序不修改服务的 file/TEE 环境。若只需应用现有 HTTPS 而不刷新定时服务，CLI 添加 --no-install-timer。现有 timer 使用默认 INI/HTTPS 目录；自定义路径时工具会拒绝安装默认 timer，须使用此选项并由管理员维护对应服务环境。

若 HTTPS 已应用但 tems 重启失败，明确返回部分应用错误，不自动撤回已启动配置。成功只代表配置应用与服务 active，仍需从管理电脑验证 HTTPS 信任/IP、Modbus 双向 TLS 握手与业务报文，不等于实机业务验收完成。

## 4. 续签、查询与吊销

续签重复生成新的 CSR 交接目录，复用设备原私钥；CA 重新签发到新输出目录，再按预检、导入、应用流程操作。根/签发 CA 均保持原目录。HTTPS 定时服务每天本地时间 03:00（最多随机延迟 5 分钟）检查，距到期不足 30 天仅生成待签 CSR，不联网签发；可用部署工具重新导出三份 CSR 一并续签。

```bash
python3 ca_manager.py --ca-dir /secure/company-ca list
python3 ca_manager.py --ca-dir /secure/company-ca revoke HEX_SERIAL --reason key_compromise
python3 ca_manager.py --ca-dir /secure/company-ca crl ./issuer-crl.pem
```

GUI 支持签发记录查询、填序列号吊销、导出签发 CA 的签名 CRL。CRL 默认 7 天有效，编号递增。**当前设备端还未接入 CRL/OCSP 校验，因此 CA 标记吊销或导出 CRL 不会自动阻断现有设备证书连接。** 设备反馈继续为 revocationStatus:unavailable；涉及密钥泄露应由管理员在维护窗口更换身份/信任，并按实际系统能力阻断旧身份。此程序不宣称具有尚未接入的在线吊销执行能力。

## 5. 验证

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider provisioning/tests
```

测试使用临时目录、真实生产 C file 后端辅助程序和 OpenSSL 验证 CSR/三证书链、完整导入、私钥不变、失败回滚/中断恢复、篡改/错误指纹/错误角色/缺链拒绝、CA 加密口令及签名 CRL。服务应用测试使用 systemctl/Nginx 替身，不执行真实服务部署。GUI 的实际桌面交互、真实 TEE 和目标设备联调仍需实机验证。

## 6. 原生可执行文件打包

根目录 `build_provisioning_executables.py` 默认生成 CA 与 PC SSH 两套桌面发行包：

| 程序 | 形式与依赖 |
|---|---|
| LC400_CA_Manager | 包含 Python、Tk、cryptography 的桌面发行包；PyInstaller 可用时生成单文件，Linux 离线模式生成带 runtime/ 和 app/ 的目录包 |
| LC400_Device_Deploy | PC SSH 桌面客户端；内含 Python、Tk、SSH 库，通过 SSH 连接设备，不依赖 PC 的设备目录或 C 辅助程序 |
| LC400_Device_Agent（可选） | 设备本地应急后端；使用设备已有 Python，需另加 --tool device-agent 构建，不是日常 PC 客户端 |

Linux PC 桌面工具构建：

```bash
python3 -m pip install -r provisioning/requirements-build.txt
# 默认构建当前 PC 架构的 CA 与 SSH 客户端；不需要 ARM64 交叉编译器。
python3 build_provisioning_executables.py
```

输出默认在 `provisioning/build-output/executables/`，各包包含使用说明、构建信息及 SHA256SUMS，另提供 tar.gz 压缩包。CA 可执行文件直接运行，不再需要管理电脑另装 Python/Tk/cryptography；GUI 仍需要桌面显示环境。目录式发行包必须整体保留 runtime/、app/ 和启动文件，不能只复制启动文件。最低 glibc 版本见 build-info.json（当前构建机为 2.31）。Linux 文件只能用于对应 Linux 架构，不能改扩展名作为 Windows EXE。

Linux 在无法下载 PyInstaller 时，可复用构建机已有 Python/Tk/cryptography，执行：

```bash
python3 build_provisioning_executables.py --tool ca --ca-builder portable
```

该模式无需 PyInstaller，打包当前 Python 标准库、Tk 资源、cryptography 及所需非 glibc 动态库，使用静态 ELF 启动器；发行包需要兼容的 Linux/glibc 和桌面显示环境。构建过程只复制代码/运行时，不复制 CA 数据、加密口令文件或设备私钥。

Windows CA EXE 在 Windows x64 Python（3.8–3.13，选择包含 Tcl/Tk 的安装）环境构建：

```powershell
py -m venv .venv-build
.venv-build\Scripts\python.exe -m pip install -r provisioning\requirements-build.txt
.venv-build\Scripts\python.exe build_provisioning_executables.py --tool ca
```

CA 输出 `LC400_CA_windows-amd64/LC400_CA_Manager.exe` 和 zip。将 --tool ca 改为 --tool device 可生成 PC SSH 的 `LC400_Device_PC_windows-amd64/LC400_Device_Deploy.exe`。保留控制台以支持口令交互和 CLI；双击无参数仍进入 GUI。当前 Linux 构建不会生成或冒充 Windows EXE。

可选本地应急后端使用 `--tool device-agent --device-arch aarch64` 构建（交叉构建需 aarch64-linux-gnu-gcc），在设备上执行：

```bash
chmod +x LC400_Device_Agent
./LC400_Device_Agent --help
sudo ./LC400_Device_Agent --backend file generate \
  --device-id LC400-001 --out /tmp/LC400-001-csr
```

它优先选择 `/home/zlg/myenv/bin/python3`，其次 `/usr/bin/python3`、`/usr/local/bin/python3`。如需指定解释器，可设置 `LC400_PYTHON=/绝对路径/python3`。无参数 GUI 需设备本机已有 tkinter/桌面；无桌面的设备继续使用 CLI。此设备发行形式不包含 ARM64 Python 运行时，不能作为“无 Python 设备可直接使用”的包。

可执行包不包含私钥或运行数据。根 CA 指纹仍须独立核对；发行文件 SHA256SUMS 只用于完整性核查，不能替代企业可信分发与代码签名流程。

证书管理脚本统一放在 `exec/app/script/`，设备路径为 `/home/zlg/app/script/modbus_certs.py`。更新时整体复制 app 目录；PC SSH 工具也需使用匹配的新版本。`app/bin/modbus_tee_identity` 仍需放入对应设备架构的新版本二进制，整体复制 app 时保留该文件及设备运行配置、密钥。
