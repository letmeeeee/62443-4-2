# 独立 CA 服务器与 Web 管理界面

本服务在项目中独立运行，不读取或修改 EMS、Modbus、GOOSE 服务配置，也不会替换原 `ca_manager.py` 或 `goose_pki_gui.py` 的 CA 数据。

## 1. 功能与算法

| 功能 | 实现 |
|---|---|
| 服务器 CA 初始化 | 生成 CA 私钥、自签根证书和初始 CRL，禁止覆盖已有 CA |
| CA 算法 | P-256（prime256v1）或 RSA-2048/3072/4096 |
| 自动签发 | 根据设备信息生成新设备私钥 → 对应 CSR → 校验 CSR → CA 签发证书 → 保存台账 |
| 设备算法 | P-256 或 RSA-2048/3072/4096，与 CA 算法独立选择 |
| 用途 | GOOSE、TLS 服务器、TLS 客户端；GOOSE 固定 P-256 |
| 导出 | 单独下载证书、CSR；ZIP 下载设备私钥、CSR、证书、根证书和当前 CRL |
| 私钥保管 | CA、设备私钥加密 PKCS#8 入库；设备导出可另设口令，也可明确选择未加密 PEM |
| 运维 | 签发记录分页、锁定/解锁、证书吊销、递增 CRL 编号、操作记录 |

CA 使用什么算法，决定证书的签发签名算法；设备选择什么算法，决定设备证书里的公钥类型。例如 RSA CA 可以签发 P-256 GOOSE 证书，也可以签发 RSA TLS 证书。

当前版本为单管理员、单 CA、单服务进程。CA 是自签根，`pathLen=0`，直接签发终端证书。管理员登录口令和 CA 保护口令用途独立。CA 私钥不提供 Web 下载接口；备份通过服务器数据目录完成。

## 2. 安装与启动

服务器环境：Linux、Python 3.9+；客户端使用现代浏览器即可，无须 Tkinter。在项目根目录执行：

```bash
python3.9 -m venv .venv-ca-server
.venv-ca-server/bin/python -m pip install -r tools/ca_server/requirements.txt

# 交互设置管理员口令，至少 12 位；不通过命令行或环境变量传入口令。
.venv-ca-server/bin/python ca_server.py --data-dir "$HOME/.lc400-ca-server" init

# Waitress 单进程、多线程；默认只监听本机。
.venv-ca-server/bin/python ca_server.py --data-dir "$HOME/.lc400-ca-server" serve
```

访问 **http://127.0.0.1:8443**。8443 是默认端口号，本机监听使用 HTTP，不表示已启用 TLS。

初始化仅设置管理员，不创建 CA。页面登录后填写 CA 信息、选择算法、设置独立 CA 保护口令，即可生成服务器自己的 CA 私钥和证书。初始化完成后先解锁，再签发。

也可指定监听端口：

```bash
.venv-ca-server/bin/python ca_server.py --data-dir /secure/lc400-ca serve --port 8443
```

向局域网提供服务时，通过 HTTPS 反向代理转发到本机 HTTP 监听，并添加 `--secure-cookie`。HTTPS 的服务器证书须单独配置，不能把 CA 根证书当作 HTTPS 叶证书。浏览器需信任 HTTPS 证书；在安全上下文中使用管理页面。不把后端 HTTP 端口直接暴露给外网。

服务启动时持有数据目录的独占锁，防止重复启动。使用提供的 CLI 启动，不配置多进程 WSGI worker；CA 解锁状态与管理员会话保存在单进程内存中。

## 3. 页面操作

1. 使用 `init` 设置的管理员口令登录。
2. 首次创建 CA：填写 CA 名称、算法、有效天数，设置并确认 CA 保护口令。默认 P-256、3650 天；RSA 可选 2048/3072/4096 位。CA 创建后不能在页面覆盖或重置。
3. 输入 CA 保护口令解锁。解锁有效期固定 30 分钟，页面定期刷新显示剩余时间；重启、退出登录或“立即锁定 CA”会清除服务进程中的解锁状态。
4. 填写设备编号、CN、用途、算法、有效期和可选组织信息。TLS 服务器证书必须包含 DNS 或 IP SAN；GOOSE 不填写 SAN。设备有效期为 1–825 天，不能超过 CA 有效期。
5. 点击“生成私钥、CSR 并签发证书”。每次成功操作会新增一套独立密钥及签发记录，不覆盖之前的证书。
6. 在签发记录里下载证书、CSR，或选择“私钥与完整包”。GOOSE 默认选择未加密 PKCS#8；加密导出时设置独立导出口令，不能使用 CA 保护口令。
7. 需要吊销时选择原因。吊销和新 CRL 的生成在同一事务提交，新的 CRL 编号递增。下载并重新导入通信双方，应用后才能影响对端验证；仅在 CA 记录吊销不会自动修改设备。

GOOSE 文件包：

```text
device-<id>.zip
├── enc.key          # P-256 设备私钥，明确选择 plain 才是未加密 PEM
├── enc.crt          # CA 签发的设备证书
├── device.csr.pem   # 对应 CSR
├── ca-roots.crt     # 本 CA 的自签信任根
└── crls.pem         # 本 CA 当前 CRL
```

使用同一 `batch_id` 把 `enc.crt`、`enc.key`、`ca-roots.crt`、`crls.pem` 导入现有 GOOSE 四类接口，最后 apply。通信双方分别生成身份，不共用设备私钥。新 CA 与已有 SCADA CA 属于不同信任体系，设备信任根须相应配置。

## 4. 存储与运行状态

```text
数据目录（0700，归服务运行用户所有）
├── ca.sqlite3   # 0600；管理员摘要、会话签名随机值、加密密钥、证书/CSR、吊销及审计记录
└── .server.lock
```

CA 密钥及设备密钥都使用 CA 保护口令加密存储。服务解锁期间在内存保留保护口令，用于签发和重新加密导出；口令不写明文配置、接口响应或日志。解锁过期后后续请求会清除该引用；Python 不提供内存可靠擦除保证。管理员口令以 scrypt 摘要保存。登录和解锁限制每来源每分钟 5 次；当前反向代理部署下来源默认是代理地址。

登录会话固定 30 分钟，退出后该会话失效，服务重启后所有会话失效。多浏览器共享同一个 CA 解锁状态，任一管理员会话锁定或退出会锁定全局 CA。CA 锁定时可查询台账和下载公开证书/CSR/CRL，不能新签发、导出私钥、吊销或更新 CRL。

签发成功响应只返回记录信息，不直接返回私钥。请求的 `Idempotency-Key` 防止断网重试生成重复身份；同键同参数返回原记录，同键不同参数返回 409。页面在失败重试时复用请求键，刷新页面后不保留未完成请求键，可先查询记录确认。

CRL 默认有效 30 天，刷新时保留全部吊销记录并增加编号。页面显示 CRL 到期状态；本版本需要人工更新和分发，未做自动推送或定时续期。导出文件包包含当前 CRL，即使已过期；导入 GOOSE 前须先更新。系统时间需准确。

备份前停止服务，完整备份数据目录，并单独保管 CA 保护口令。还原后核对根证书 SHA-256 指纹和最新 CRL 编号，不能用旧备份覆盖新吊销状态。丢失 CA 保护口令时无法恢复 CA 或设备私钥。本版本尚不提供口令轮换、管理员口令找回、已有 CA 导入、中间 CA、HSM、OCSP 或 ACME。

## 5. API 与调用示例

所有路径属于这个独立 CA 服务，不属于 EMS 的 `/api/cert/*`。JSON 成功响应不含 EMS 的 `status=3` 外壳；错误统一为 `{"error":"...","message":"..."}`。除获取页面、静态资源、会话信息和登录外均需登录。所有 POST（包括登录）需要会话 Cookie 和 `X-CSRF-Token`。

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/session` | 获取登录状态和 CSRF token |
| POST | `/api/login` | 管理员登录，返回新的 token |
| POST | `/api/logout` | 注销当前会话，同时锁定 CA |
| GET / POST | `/api/ca` | 查看状态 / 首次生成 CA |
| POST | `/api/ca/unlock` | 使用 CA 保护口令解锁 |
| POST | `/api/ca/lock` | 锁定 CA |
| GET | `/api/ca/certificate` | 下载根证书 |
| GET | `/api/ca/crl` | 下载当前 CRL |
| POST | `/api/ca/crl/refresh` | 更新 CRL |
| GET | `/api/devices?limit=20&offset=0` | 分页查询记录；每页最多 200 条 |
| POST | `/api/devices` | 生成设备密钥、CSR 并签发，需 `Idempotency-Key` |
| GET | `/api/devices/{id}/certificate` | 下载设备证书 |
| GET | `/api/devices/{id}/csr` | 下载设备 CSR |
| POST | `/api/devices/{id}/export` | 下载 ZIP；含设备私钥 |
| POST | `/api/devices/{id}/revoke` | 吊销设备证书并更新 CRL |
| GET | `/api/events` | 最近 200 条操作记录 |

CA 初始化示例（P-256；CA 自身也可指定 RSA 和 rsa_bits）：

```http
POST /api/ca
Content-Type: application/json
X-CSRF-Token: <登录后返回的 token>
Cookie: lc400_ca_session=<cookie>

{"cn":"SCADA Root CA","algorithm":"P-256","days":3650,"password":"<CA独立保护口令>"}
```

一键生成 P-256 GOOSE 身份：

```http
POST /api/devices
Content-Type: application/json
X-CSRF-Token: <token>
Cookie: lc400_ca_session=<cookie>
Idempotency-Key: 97bb5470-fc5d-4f59-836f-dfbd217125f7

{"device_id":"LC400-001","cn":"LC400-001-goose","profile":"goose","algorithm":"P-256","days":365}
```

一键生成 RSA TLS 服务器身份：

```json
{"device_id":"LC400-001","cn":"LC400-001-server","profile":"tls_server","algorithm":"RSA","rsa_bits":3072,"days":365,"ip_addresses":["192.168.3.100"],"dns_names":["ems.example.com"]}
```

成功返回 HTTP 201，示例（摘要仅展示主要字段）：

```json
{"id":"<设备记录ID>","device_id":"LC400-001","cn":"LC400-001-goose","profile":"goose","algorithm":"P-256","rsa_bits":null,"serial":"<证书序列号>","created_at":"<UTC时间>","expires_at":"<UTC时间>","revoked_at":null,"reason":null}
```

未加密设备私钥包导出（响应为 ZIP 字节）：

```http
POST /api/devices/<设备记录ID>/export
Content-Type: application/json
X-CSRF-Token: <token>
Cookie: lc400_ca_session=<cookie>

{"key_format":"plain","confirm_plaintext":true}
```

加密设备私钥包导出请求体：

```json
{"key_format":"encrypted","export_password":"<独立导出口令，至少12位>"}
```

常见错误：401 未登录或会话过期，403 CSRF 失败，409 CA 已存在或幂等键冲突，413 请求过大，422 参数/口令/证书配置不合法，423 CA 已锁定，429 尝试过频，500 持久化或服务内部失败。签发响应失败时先用相同幂等键重试，不直接生成新键。

## 6. 验证

```bash
.venv-ca-server/bin/python -m unittest tools.ca_server.test_server -v
node --check tools/ca_server/static/app.js
```

测试在临时目录生成测试 CA；覆盖算法组合、CSR/证书/私钥一致性、OpenSSL 严格链与 CRL 验证、现有 GOOSE 后端四文件导入与模拟 apply、认证/CSRF/注销、私钥导出口令隔离、幂等、重启、存储失败和吊销。

可选浏览器测试（启动真实 Waitress 服务并操作 Web 页面）：

```bash
.venv-ca-server/bin/python -m pip install playwright
.venv-ca-server/bin/python -m playwright install chromium
.venv-ca-server/bin/python -m unittest tools.ca_server.test_web -v
```
