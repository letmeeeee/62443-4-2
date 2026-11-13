# LC400 应用安全接口部署与验证

本轮增加非固件维护类的应用安全接口，沿用 MySQL 和 Bearer 会话。接口交付说明见 `LC400-前端接口对接反馈-2026-11-06.md`。本文件面向后端部署和设备维护，不作为标准符合性结论。

## 1. 数据与启动兼容

保留现有 Permission_Management 用户表及其八列结构，不重建已有业务数据库。启动增加以下 InnoDB 表：

- security_accounts：稳定 UID、普通账号启停、最后登录、口令历史；删除账号后保留不可重用的身份记录。
- security_session_activity、security_session_locks：会话活动和服务端锁屏。
- security_auth_attempts、security_rate_limits：跨工作进程共享的失败锁定和 HTTP 来源限速。
- security_settings：Banner 和限时维护模式。
- security_audit：结构化安全审计，独立查询，与原 operation_log 分开。

原 login_sessions、login_capacity_lock 继续使用。运行账号须能建表并读写上述表；审计容量查询读取配置路径所在文件系统的空间。部署前先保全现有数据库与 INI，并确认存在未被开发账号禁用策略禁止的个人管理员。

新会话支持默认 900 秒空闲失效。没有活动记录的旧会话需要重新登录；正常请求和后台轮询会更新活动时间。新会话保持原来的绝对有效期配置。

旧 MD5 口令只在验证成功后迁移为 PBKDF2；原 password VARCHAR(128) 可容纳新格式。强摘要迁移后，旧版本仅支持 MD5 的登录代码不能验证已迁移口令，不能只回退 Python 文件。需要回退时按备份流程同时处理账号数据。

新增用户必须明确提供符合策略的口令；本人改密需要 old_password，成功后全部会话失效。用户名不再允许在线重命名。

## 2. 依赖与配置

新增运行依赖见 `requirements-security.txt`。本次测试使用 Python 3.8、Flask 3.0.3、SQLAlchemy 1.4.54、Flask-SocketIO 5.3.6、cryptography 42.0.8。测试虚拟环境只用于开发验证，不是设备部署路径。

继续使用现有 Session 配置文件及持久 FLASK_SECRET_KEY。可设置环境变量 `SECURITY_CONFIG_FILE` 指向本机受管理员控制的 JSON 文件，示例：

```json
{
  "AUTH_IDLE_SECONDS": 900,
  "HTTP_REQUESTS_PER_MINUTE": 3000,
  "AUDIT_RETENTION_DAYS": 180,
  "SECURITY_STATE_DIR": "/home/zlg/instance/security",
  "MODBUS_CERT_DIR": "/etc/ems/modbus",
  "SECURITY_DISK_PATH": "/mnt/nvme",
  "TRUST_LOOPBACK_PROXY": true,
  "SECURITY_ALLOW_DESTRUCTIVE": false
}
```

缺省值同上，但磁盘默认 `/`，安全目录默认按代码路径计算为 instance/security。单独指定 SESSION_CONFIG_FILE 不会改变安全目录，需另设 SECURITY_STATE_DIR。目录由后端创建为 0700，文件为 0600；如果已有目录权限过宽则拒绝使用，不会静默修改现有目录权限。路径必须为绝对路径，不允许符号链接目录。

HTTP 限速按来源 IP 的分钟窗口计数；Nginx 从 loopback 转发且覆盖 X-Real-IP 时可恢复真实来源。仅信任 loopback，不信任任意 X-Forwarded-For；非该代理部署应关闭 TRUST_LOOPBACK_PROXY 或核对代理拓扑。默认 3000 次/分钟需结合实际前端轮询和设备压测调整，不代表已完成协议通信负荷压测。

新安全接口采用默认权限矩阵：账号、证书、备份、退役、维护入口为角色 4；安全审计读/导出为角色4；业务日志读取及安全汇总为角色3/4；参数修改为角色 2/3/4。矩阵见 utils/access.py，前端通过 `/api/security/roles` 对齐。

停用旧 GET `/api?sql=...` 任意 SQL 入口。通用 CSV 导出仅保留白名单业务历史表。生产部署必须同步更新依赖旧入口的客户端。

## 3. 临时口令交付

重置接口生成随机临时口令，只把明文写到安全目录下 credentials/{delivery_id}.json（0600），HTTP 仅返回 delivery_id。凭据和领取记录有效期 24 小时，过期临时账号不能继续凭该口令登录。

设备管理员通过设备本地受控终端领取一次：

```bash
python3 /home/zlg/app/script/collect_credential.py DELIVERY_ID --directory /home/zlg/instance/security
```

脚本核验文件归属和权限，读取后删除领取文件，并在本地终端输出临时口令。请按现场既有受控渠道交付给用户；不要通过 HTTP、应用日志或源码记录口令。未领取的旧凭据文件可由设备管理员清理；重置/禁用后旧登录凭据失效。

## 4. 审计留存与告警

新审计保留 180 天，在写入时清理过期新审计记录；历史 operation_log 不自动删除。容量改为统计 SECURITY_DISK_PATH 所在文件系统的实际总空间和已用空间（包括其他文件占用），不再按日志表大小或固定 256 MiB 计算。应将该路径配置到 MySQL 数据目录所在文件系统；默认仍为 `/`，远程数据库须在数据库主机侧提供监测，不能用后端本机空间代替。旧 AUDIT_CAPACITY_BYTES 配置保留兼容读取，但不再参与容量计算。业务历史数据清理仍由原磁盘清理策略负责。

容量状态 JSON 字段保持原结构：`GET /api/history/status` 的 totalBytes、usedBytes、usagePercent 改为上述文件系统统计；capacityExceeded 仍表示已用空间达到总空间（100%），不代表95%严重告警。`GET /api/security/status` 的 alerts 在使用率达到80%且不足95%时返回 `AUDIT_CAPACITY_HIGH`，提示清理、导出日志或扩容；达到95%时改为返回 `AUDIT_CAPACITY_CRITICAL`，提示尽快处理。两级容量告警不同时返回；`AUDIT_WRITE_FAILED` 独立报告，可与容量告警同时出现。告警对象仍使用 code/source 字段，未增加字段；前端需识别新增的 CRITICAL 告警码并映射提示文案。这些状态在查询时返回，不主动推送、不自动清理或扩容。空间采集失败不得报告为0%正常，安全汇总标记审计状态不可用，已存在的写入故障仍报告。

旧审计队列满/写失败与新审计写失败会触发 writeFailed。可写本地存储时写入 health/audit-write-failed，跨工作进程和重启保留；磁盘也不可写时至少保留本进程告警。排障并确认数据库、队列和磁盘恢复后，由管理员清除该文件并重启进程，重置告警。不能因单次查询成功自动解除。

安全审计与业务操作日志独立查询。GET /api/history/getSecurityAudit 只读 security_audit，GET /api/history/getOperationlog 只读 operation_log，均保持 total/pageNum/pageSize/operationLogList 分页结构。安全审计查询、GET /api/history/export 导出、GET /api/history/status 状态均仅等级4；业务操作日志查询仍允许等级3或4。历史数据不迁移、不改写；旧安全审计记录仍可能保留原接口路径和粗粒度类型。

新安全审计记录使用实际事件类型，如 authentication.login、account.disable、account.password.reset、backup.restore；operation_target 写入后端确认的账号、设备、证书角色或备份编号，无法确认时明确标记为未确认对象。接口方法和路径、HTTP状态及错误码放入 remark，不记录原始请求体、完整查询串或明文密码/令牌。恢复、出厂恢复及身份清除执行前的授权记录使用 *.authorize 类型，避免与执行完成混淆。审计类型筛选支持事件类型字符串，审计目标按文本精确匹配；业务日志仍使用原数字类型及设备编号筛选。接口完整说明见《审计日志与业务日志接口说明_2026-11-06.md》。

## 5. 备份与恢复的保守范围

范围只包括应用账号/角色、UID/启停/口令历史、安全设置、设备 INI 和公开证书指纹引用。不会复制可重放 Token、TEE/证书私钥、业务历史数据库或平台镜像。维护模式这类瞬时状态不会恢复。

备份以 AES-GCM 加密并绑定设备及版本。密钥由现有持久 Flask 密钥按独立用途派生；丢失/轮换该密钥会导致已有备份不能解密，因此密钥应在设备受控持久化方案中保全。默认设备标识取 /etc/machine-id，也可在配置中明确设置 SECURITY_DEVICE_ID；标识改变后旧备份被拒绝。

恢复检查格式、AEAD 认证、可选/执行时必需的 SHA-256、设备、用户表结构、有效管理员和证书引用兼容性。备份最多 20 个、总量 128 MiB、单文件约 16 MiB；达到配额由管理员下载归档后在本地处理文件。

执行恢复需同时满足：

1. 本机配置 SECURITY_ALLOW_DESTRUCTIVE 为 true。
2. 管理员通过接口启用限时维护模式。
3. 当前管理员 Token、CSRF、二次口令校验有效。
4. dry_run:false、准确确认文本及已校验的备份摘要。

维护模式会阻止大部分业务写请求。实际恢复前应确认设备业务已停至可恢复状态，并等待在途操作结束；当前应用接口不负责停止平台控制进程。默认关闭执行开关，预览与校验始终优先。

恢复前先生成检查点；数据库事务和 INI 替换失败时尝试恢复原配置。数据库与文件系统无法跨资源原子提交，进程异常/断电时使用 recovery/pending.json 阻止服务再次启动，避免带不确定配置运行。

出现 pending.json 时，先停服务，保留 pending.json、目标备份及 checkpoint；由设备管理员核对数据库是否提交、INI 与可信完整性基线是否匹配，通过受控恢复流程将两者恢复到同一检查点，然后移除标记并启动。不要直接删除标记继续运行。正常恢复后也需要重启及 INI 完整性基线/设备参数/时间同步/功能检查；接口不自动把新摘要认定为可信基线。

## 6. 出厂基线与清除边界

出厂恢复复用同设备加密备份，需在本机配置 SECURITY_FACTORY_BACKUP_ID 和 SECURITY_FACTORY_BACKUP_SHA256。基线文件由设备管理员预置和保全，应用不自动从任意普通备份中选择。基线需包含有效管理员且所有账号为强摘要口令；出厂恢复后设置首次改密。

退役接口本轮只实现 application-identities 范围，清除应用身份/会话/安全设置及本地备份与临时凭据。保留业务数据库、INI、证书、平台/TEE 密钥、审计与应用日志；保留证据便于人工归档和平台退役。没有物理介质覆盖擦除，也不能宣称整个设备已完成退役。

恢复出厂、应用身份清除的执行开关都默认关闭。清除后必须通过设备本地受控流程重新配置管理员；应用不会创建一个可远程登录的固定默认口令账号。

## 7. 设备依赖与验证边界

- Modbus/HTTPS 只使用外部 CA 身份，CSR/链校验见 CERT_API.md 和 script/HTTPS.md。chainVerified 不代表已经执行 CRL/OCSP 吊销检查。
- TEE RSA 公钥可查询时生成实际 Key ID；无 CLI/TA 能力时明确 unavailable。当前没有对称密钥完整生命周期和实时握手遥测。
- 网络快照需要 ip/nft 及相应读取权限；时间同步状态依赖 timedatectl；采集失败不当作安全正常。
- 组件清单自动采集后端运行时。完整平台/固件组件需通过 COMPONENT_MANIFEST 指定 JSON 数组补充；每项按 name/version/type 等字段描述。未配置时 firmwareInventoryComplete 为 false。
- 测试使用 SQLite、临时目录和设备服务替身，不连接生产 MySQL，不执行真实设备部署或平台清除。

## 8. 本次验证结果

2026-11-03：以下八个测试文件合计 **159 项通过**：test_ca_provisioning.py、test_input_validation.py、test_security_center.py、test_auth_session.py、test_session_config.py、test_https_config.py、test_route_tee.py、test_ssh_api.py。覆盖真实路由匿名拦截、角色/对象权限、强摘要迁移、大小写别名失败锁定、空闲超时、不可绕过的锁屏、改密/禁用/强制下线、审计字段/历史兼容/导出、备份篡改拒绝、恢复提交失败回滚、默认预览和应用清除边界，以及三种独立 CSR、公钥/用途/CA 链拒绝、CA-only HTTPS 续签与 reload 重试。

另通过 file 私钥的生产 Modbus TCP 双向 TLS 回环与 IP SAN/过期/叶证书冒充 CA 拒绝测试，以及 TEE 软件替身 CSR/CA 身份测试和 OpenSSL TLS1.2/1.3 双向握手测试。TEE 测试不是实机 TA 持久化验证。

检查同时通过变更 Python 文件语法和 CRLF 感知的 git diff --check。测试不等于真实 MySQL、设备硬件或浏览器联调；本次没有在生产设备运行恢复、清除或部署操作。

## firewalld 规则只读查询

`GET /api/security/network-rules`（权限 3/4）读取 `firewall-cmd --list-all-zones`，不再返回整个 nftables ruleset，不调用 `/usr/local/bin/fw-port.sh` 或写入/重载防火墙。运行账号须有查询 firewalld 的权限，且 firewalld 服务正在运行。

网卡、路由仍由 iproute2 采集。`rules` 成功时为 `{scope:"runtime-zones",zones:[...]}`，区域包含 `name`、`active`、`target`、`interfaces`、`sources`、`ports`、`services`、`richRules` 和 `details`。例如 public 的 `ports` 为 `[{"port":"8000","protocol":"tcp"},{"port":"6000-6010","protocol":"udp"}]`；服务隐含端口不展开，复杂规则原样保留。非活动区域也返回，由 active 区分。该结果是区域运行时配置，不是永久配置、系统监听端口或完整访问判定；不包含独立 policy 对象和 direct 等其他规则入口。

查询工具缺失、权限不足、服务未启动或超时，返回 `rules:null`、`rulesAvailable:false`、`rulesUnavailableReason:"FIREWALLD_QUERY_FAILED"`；输出解析失败则原因是 `FIREWALLD_RESPONSE_INVALID`。正常采集但无显式端口时 ports 是空数组，仍为采集成功。新增 DPrint 仅打印区域数量或失败原因，保留现有业务日志和审计通道。配置摘要中的 networkRules 同步使用该结果。

## Modbus TLS 活动对端遥测

`GET /api/security/peer-status`（现有权限 3/4）读取 logger 发布的活动 TLS 对端快照。身份在真实 TLS 握手及验证成功后登记，终止性收发错误或 `Modbus_Close` 时移除。握手失败的连接不发布证书，现有 TLS 错误日志保留。此功能不是新的认证机制，不修改 CA 信任、TLS 策略、寄存器共享内存或业务/审计日志通道。

### 文件与发布周期

默认运行时目录为 `/run/lc400/modbus-peers/`：

- `status.json`：schemaVersion=1，包含当前进程、启动标识、单调时钟心跳和活动连接引用。
- `peer-<进程实例>-<连接序号>.pem`：每连接独立保存对端公开叶证书，不保存私钥、会话密钥，也不加入信任库。
- `.lock`、`.publish.tmp`：单发布者锁及原子发布临时文件。

通信线程只在内存登记/移除，独立线程执行 PEM 和 JSON 文件操作。连接变化唤醒发布线程，同时约每秒发布心跳；正常断开后的文件清理通常在下一次发布、约 1 秒内完成，并非通信线程同步删除。同一证书可对应多条连接，每条连接拥有独立文件，关闭一个连接不会删除其他活动连接所需的证书。

正常进程退出清理快照和证书；启动时清理旧 PEM 和快照。SIGKILL、掉电等不能保证立即执行删除：Flask 会通过 PID/启动标识和最多 5 秒的心跳有效期拒绝旧快照，残留文件由下次启动清理，`/run` 也属于临时运行数据。连接状态基于进程实际检测到的断开/错误；未被通信层检测到的半开连接不会仅因业务空闲被强制删除。

最多记录 256 个连接；达到上限或登记信息不完整时返回采集不完整，避免将部分数据误当成全量。采集目录或文件不可用时仅记录诊断，不中断原有 Modbus 通信。当前仅支持一个 logger 发布者占用该目录，多实例应分别配置目录。

### Flask 返回结构

```json
{
  "ok": true,
  "liveAuthenticationTelemetryAvailable": true,
  "scope": "modbus-tls-active-connections",
  "sampledAt": "2026-11-11T10:00:00Z",
  "data": [
    {
      "connectionId": "1234-1794362400-123456789-1",
      "localRole": "master",
      "peerIp": "192.0.2.10",
      "peerPort": 502,
      "transport": "tls",
      "connectionStatus": "connected",
      "authenticationStatus": "verified",
      "connectedAt": "2026-11-11T09:59:00Z",
      "peerCertificate": {
        "sha256": "证书SHA-256指纹",
        "subject": "CN=device-slave",
        "issuer": "CN=Enterprise-CA",
        "notBefore": "2026-01-01T00:00:00+00:00",
        "notAfter": "2027-01-01T00:00:00+00:00"
      }
    }
  ]
}
```

以上为结构示例。`localRole` 是本机角色：master 表示本机主动连接从机，slave 表示本机接受主机连接；服务端看到的 peerPort 可能是主机的临时源端口。`authenticationStatus:verified` 表示连接建立时已通过 TLS 验证，不代表持续 CRL/OCSP 查询。API 不返回服务器文件路径、PEM 原文或私钥。没有新增证书下载接口。

`liveAuthenticationTelemetryAvailable:true,data:[]` 表示有效快照中没有活动已认证 TLS 连接；不能扩大解释为所有 Modbus 设备离线。单设备可能有多条读写连接，不能直接将数组长度当作设备数量。明文 Modbus TCP 和 RTU 不在本清单中；本次不提供最近收发时间字段。

遥测不可用时仍返回 HTTP 200、`ok:true`、空 data、`liveAuthenticationTelemetryAvailable:false` 和 `reason`：

| reason | 含义 |
| --- | --- |
| PEER_STATE_UNAVAILABLE | 状态文件或某个证书不存在，或断开清理与读取发生竞争 |
| PEER_STATE_STALE | 心跳超时或时间无效 |
| PEER_PRODUCER_UNAVAILABLE | 生产进程不存在、已退出或 PID 启动标识不匹配 |
| TLS_DISABLED | logger 未开启 TLS，不能提供已认证 TLS 对端 |
| PEER_COLLECTION_INCOMPLETE | 连接超过上限或采集信息不完整 |
| PEER_STATE_INVALID | 格式、权限、符号链接、大小或证书读取异常 |
| PEER_CERTIFICATE_READER_UNAVAILABLE | Flask 缺少证书解析依赖 |

Flask 只读、不启动或探测 Modbus 连接，也不清理 logger 文件；状态切换/原子发布期间可能短暂返回不可用，下次轮询重试即可。

### 部署与权限

需要重新配置并构建 logger，将新增 `logger/lib/modbus_peers.c` 纳入现有 CMake 的 lib 源文件集合，部署新 logger 二进制及 Flask 修改后分别重启。只更新 Python 文件不能启用真实遥测。未部署新 logger 时 Flask 会保持遥测不可用。

logger 和 Flask 默认共用 `/run/lc400/modbus-peers`；如设置 `MODBUS_PEER_STATE_DIR` 环境变量，两个服务必须指向同一实际目录，且能访问同一进程命名空间。Flask 还可通过同名 app.config 配置覆盖，避免只修改单方路径。

目录必须由 logger 运行用户拥有，不允许组/其他用户写入；发布文件为 0640。若 Flask 使用不同用户，部署时预建 logger 所有、Flask 可读的共享组目录（例如目录 2750 并设置共享组继承），确保所有父目录可遍历、Flask 可读取文件；不要用 0777 或组可写目录解决权限问题。logger 和 Flask 使用同一用户时默认目录权限即可。`/run` 的目录重启后需要由部署的运行目录机制重新创建。本次不修改 systemd 单元或自动部署。
