# CA 签发身份证书 API：HTTPS、Modbus 主机与从机

当前仅支持 CA 签发身份证书。三种身份各自保留私钥、生成 CSR，经外部 CA 签发后导入本机。HTTPS 和两个 Modbus 角色默认使用同一个 `[TLS] ca_file` 根信任包；不保存 CA 私钥，不提供设备自签、叶证书钉扎或私钥导出。

## 公共约定

接口均要求已登录管理员（角色 4）的 Bearer Token。写请求带 X-CSRF-Token；上传使用 FormData，下载通过带 Authorization 的请求获取 Blob。业务成功通常为 HTTP 200、`status:3`，数据在 data；统一错误结构见前端反馈文档。

CA 导入、生成 CSR 和导入签发身份需要服务进程拥有对应目录的维护权限。HTTPS 应用还需要运行固定部署脚本及管理 Nginx 的权限；后端不自动 sudo 或提升权限。权限不足返回失败，不能仅凭前端显示成功。

设备配置：

```ini
[TLS]
ca_file = /etc/ems/pki/ca-roots.crt
[HTTPS]
device_ips = 192.168.2.136
```

无需模式开关；如保留旧 certificate_mode，只接受 external_ca。Modbus 私钥后端继续由 MODBUS_KEY_BACKEND=file|tee 选择，这只选择密钥存储位置，不改变 CA 签发要求。

## 接口清单

| 方法 | 接口 | 用途 / 字段 |
|---|---|---|
| GET | `/api/cert/mode` | 返回 mode:external_ca、ca_configured |
| GET | `/api/cert/ca` | 当前共享根包的 SHA-256 指纹 |
| POST | `/api/cert/ca/import` | 导入共享根信任包；FormData：file、fingerprint（每张根一个，可重复） |
| POST | `/api/cert/csr` | 生成 Modbus 角色 CSR；JSON：role、name，可选 ip、dns |
| GET | `/api/cert/csr/export?role=master` | 下载主机 CSR；slave 下载从机 CSR |
| POST | `/api/cert/identity/import` | FormData：role、file（签发叶证书）、chain（可选中间链） |
| GET | `/api/cert/identity?role=master` | 查看本机公开证书摘要文本 |
| GET | `/api/cert/check?role=master` | 校验证书链、用途、有效期、设备私钥匹配 |
| GET | `/api/cert/export?role=master` | 下载公开叶证书及中间链，不含私钥 |
| POST | `/api/cert/https/csr` | 按设备 INI 生成 HTTPS CSR，无需前端传 CN/IP |
| GET | `/api/cert/https/csr/export` | 下载 HTTPS CSR |
| POST | `/api/cert/https/identity/import` | FormData：file、chain，导入 HTTPS 叶证书及中间链 |
| GET | `/api/cert/https/status` | 校验当前 HTTPS 身份，返回有效性、待 reload/续签状态 |
| POST | `/api/cert/https/apply` | 无请求体，按待应用变更操作 Nginx／tems；见文末 CRL 应用说明 |

旧 generate、renew、trust-add、trust-remove、trust-list 接口已停止原行为，返回 HTTP 410 / CA_CSR_REQUIRED；前端删除本地生成证书、直接信任主机叶证书的交互。不能将旧 renew 改名后继续当作本地续签功能。

## Modbus CSR 与导入

```json
{"role":"master","name":"LC400-master-001","ip":[],"dns":[]}
```

```json
{"role":"slave","name":"LC400-slave-001","ip":["192.168.2.136"],"dns":[]}
```

role 为 master/slave；name 为 1–64 字符，以字母/数字开头，其余允许字母、数字、下划线、点、连字符。ip/dns 接受字符串或数组，每类最多 32 项。CSR 的有效期由外部 CA 决定，不传 days。

主机 CSR 请求 clientAuth，从机请求 serverAuth；HTTPS 也请求 serverAuth，但使用另一个私钥。CA 配置应按角色只签发对应 EKU，不签双用途客户端/服务端证书。所有叶证书明确 CA:FALSE 和 digitalSignature。从机 SAN 应包含实际连接 IP；生产 Modbus 客户端按 TCP 对端 IP 校验证书 IP SAN，不以 CN 替代 IP。

CSR 生成不会修改已部署证书。续签重复生成 CSR 时复用原私钥；如果已有身份/CSR 的私钥丢失则失败，不补建身份。CSR 导出校验仍匹配当前角色密钥。

导入前校验：可信根、完整有序中间链、当前时间、算法强度、BC/KU/EKU、公钥与本机角色私钥匹配、与当前 CSR 的公钥/CN/SAN 匹配。接受 file 中“叶证书 + 中间链”，也可通过 chain 单独提供中间链；不把上传链中的根自动加入信任。验签失败返回错误且保留原证书。

成功返回 restart_required:true；Modbus 不自动重启 tems，维护窗口重启后生效。根 CA 变更同样需要相关进程重启，不在线混用新旧信任缓存。

## HTTPS 流程

1. POST https/csr，GET https/csr/export，将 CSR 发给外部 CA。
2. 在可信渠道核验根指纹，使用 ca/import 导入根信任。
3. 外部 CA 按 CN logger、serverAuth、设备 INI 的全部 IP SAN 签发。
4. 上传 HTTPS 叶证书和中间链；成功只表示文件导入，返回 reload_required:true。
5. 调用 https/apply，成功后才显示已应用。失败保留待应用状态，不显示已生效。

证书不存在或已过期时，不能依赖该 HTTPS 入口首次开通，应通过设备本地受控终端完成引导，具体命令见 script/HTTPS.md。临近到期 timer 只生成续签 CSR 和告警，不会擅自更换密钥或本地签证书。

## 查询页显示

`GET /api/security/certificates` 提供结构化公开清单。身份包括 master、slave、https，另列 ca-root；一份 fullchain 只计一个身份，中间证书不冒充设备身份。chainVerified 为公开链校验结果。每次 GET `/api/security/certificates`、`/api/security/status` 或 `/api/security/config-summary` 均重新执行 master、slave、https 的持钥自检，privateKeyVerified 为 true（通过）、false（检查失败）或 null（未能完成/不适用），privateKeyCheckReason 提供原因；ca-root 不持有设备私钥，返回 null / NOT_APPLICABLE。检查只使用已有密钥，不生成、轮换或导出 TEE 私钥。Modbus 复用既有 file/tee 后端的 check 命令（单角色超时 15 秒），HTTPS 使用文件私钥签名随机挑战并用证书公钥验签；工具缺失、超时不会使整份列表失败。此结果独立于有效期和证书链结果，不改变原 errorCount 的证书状态统计。请求耗时会增加，前端应避免重叠轮询。

有效期见 validityStatus；链失败时 status 为 invalid。revocationStatus 现已接入 CRL，具体状态和应用步骤见文末“CRL 导入与按需应用”；unavailable 不能展示为“未吊销”。`/api/security/certificates/import` 保留为 Modbus identity/import 的别名；不再支持 POST 创建或 DELETE 钉扎叶证书。

私钥默认位置：HTTPS 为 `/etc/ssl/g3/g3.key`；Modbus file 后端为 `/etc/ems/modbus/master.key` 和 slave.key，TEE 后端分别在两个既有角色槽。文件私钥为 0600；不得跨角色复制同一个私钥。CSR、证书、中间链和根证书均为公共材料，但根信任变更必须经过管理员授权和可信指纹核对。

## 企业内部 CA 与首次部署工具

项目根目录新增 `ca_manager.py`（CA 管理 GUI/CLI）和 `device_deploy.py`（设备本地首次部署 GUI/CLI）。支持三份 CSR 交接、企业 CA 统一签发、证书包整包预检/导入、校验、HTTPS 应用及 tems 重启，INI 沿用设备现有配置。使用说明见 [provisioning/README.md](../../provisioning/README.md)。根目录运行 `python3 build_provisioning_tools.py` 可生成两个仅含代码的 .pyz 单文件发行包。

## CRL 导入与按需应用（2026-11-13，以本节为准）

设备不访问 CA 签发服务，由上层获取并推送 CRL。接口沿用管理员 Bearer、CSRF 和审计；CA 工具已有 revoke/crl 命令，CA 私钥保留在管理电脑。

| 方法 | 接口 | 参数／结果 |
|---|---|---|
| POST | `/api/cert/crls/import` | FormData：file（完整 PEM CRL 包或单份 DER CRL），chain（可选 PEM 发行方证书链）；返回 crls、restart_required、pending |
| GET | `/api/cert/crls` | 返回 crls 和 pending；每份含 issuer、issuerKeyId、crlNumber、thisUpdate、nextUpdate、status、reason、revokedCount |
| POST | `/api/cert/https/apply` | 保持无请求体；改为应用所有待生效的证书／CRL 变更 |

新增可选 `[TLS] crl_file`，默认取 ca_file 完整路径加 `.crls.pem`，例如 `/etc/ems/pki/ca-roots.crt.crls.pem`；必须为独立绝对路径。首次导入签发 CA 的 CRL 时，chain 应包含签发 CA 及所需中间证书；直接由可信根签发可省略。后续可复用已存发行方链。上传链不成为根信任。

校验 CRL 签名、发行方/AKI、CA/cRLSign、SHA-256 及以上签名、可信链、thisUpdate/nextUpdate 和 CRLNumber。拒绝编号回退、同编号不同内容、移除既有永久吊销记录、delta/间接/分区 CRL 和临时挂起。允许相同名单重试，允许已过期但真实有效的 CRL，拒绝未来发布或无 nextUpdate 的名单。单字段和合并存储各限 1 MiB。错误材料返回 422，保留原文件。有效名单即使列出本机身份也允许导入。

各发行方最新 CRL 及公开发行方链存为一个原子替换的 PEM 包，编号与名单一起提交。此文件是防编号回退的持久依据，禁止通过手工删除／恢复旧文件清除吊销。

**握手策略：** 无 CRL 时兼容已有设备，保留原有证书链校验，状态为 unavailable。已有 CRL 存储后，缺少叶证书发行方名单返回 unknown，Modbus TLS 拒绝。有效名单拒绝已列出的证书；名单过期仍拒绝原有吊销记录，其余证书允许连接，状态为 stale。证书自身有效期、链、EKU、IP SAN 校验继续执行。中间 CA 若提供对应上级 CRL，也执行吊销检查；本版不要求必须具备上级 CRL，不宣称已实现完整中间 CA 吊销发布。根撤信通过受控根包更新。

**按需应用：** HTTPS 更新操作 Nginx（按需 reload，未运行则 start）；Modbus master/slave 更新重启固定 tems.service；共享 CA 更新操作两者；CRL 更新重启 tems。合并多项更新，每个服务操作一次；没有更新不操作服务。兼容历史 HTTPS `.reload-required` 标记。服务名不接受客户端传入。

响应仍为 status/message/data；data 新增 changed、applied、services、pending。services 每项含 action/status；Nginx 的 action 为 reload-or-start，tems 为 restart。按命令成功及 tems active 判定，无运行时批次回执。一项失败返回 HTTP 503 / CERTIFICATE_APPLY_FAILED，保留失败项标记；成功项不重复操作。导入与应用通过操作锁串行化。接口可能耗时数分钟，上层应设置请求超时，超时后查询 pending。仍需设备授予固定服务管理权限，后端不自动 sudo。

CRL 导入只更新磁盘；应用重启 tems 才影响正在运行的 TLS，并终止旧连接。被吊销身份不能重连；本机身份已吊销时，重启后该角色初始化失败，需更换身份恢复。名单到期只影响新握手检查，不触发定时重启。日志记录上传、验证失败、保存、服务操作及失败原因，不记录私钥。

`GET /api/security/certificates` 的 revocationStatus 改为真实结果：good（当前有效名单未列出）、revoked（证书或中间 CA 已吊销，即使名单过期仍保持）、stale（对应名单过期且未确认吊销）、unknown（缺发行方名单）、unavailable（无名单或检查失败）、not_applicable（根信任锚）。同时返回 revocationReason、revocationCheckedAt；匹配名单时带 crlNumber（十进制字符串，避免 JS 精度损失）及 crlNextUpdate。确认吊销时整体 status 为 invalid，chainVerified、validityStatus 和 privateKeyVerified 仍独立。applyPending 表示相应服务尚待应用，磁盘检查不等于旧连接已阻断。

HTTPS 导入及应用检查已存 CRL，但浏览器端对 HTTPS 服务端证书的吊销检查由客户端策略负责；本版未开启 Web mTLS。升级需部署匹配的 app/script 并重新构建部署 tems。启用 CRL 的设备维护 Python 需 cryptography（后端既有 requirements-security.txt 要求 >=42.0.8）；未导入 CRL 的旧脚本路径不额外加载该依赖。

补充：生产统一错误响应会移除 HTTP >=400 时的路由 data，应用 503 后前端应重新 GET `/api/cert/crls` 获取 pending；校验失败的吊销详情从证书清单读取。前端适配详见 [2026-11-13 修改反馈](LC400-前端联调修改反馈-2026-11-13.md)。
