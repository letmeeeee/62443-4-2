# LC400 应用安全接口部署与验证

本轮增加非固件维护类的应用安全接口，沿用 MySQL 和 Bearer 会话。接口交付说明见 `LC400-前端接口对接反馈-2026-11-03.md`。本文件面向后端部署和设备维护，不作为标准符合性结论。

## 1. 数据与启动兼容

保留现有 Permission_Management 用户表及其八列结构，不重建已有业务数据库。启动增加以下 InnoDB 表：

- security_accounts：稳定 UID、普通账号启停、最后登录、口令历史；删除账号后保留不可重用的身份记录。
- security_session_activity、security_session_locks：会话活动和服务端锁屏。
- security_auth_attempts、security_rate_limits：跨工作进程共享的失败锁定和 HTTP 来源限速。
- security_settings：Banner 和限时维护模式。
- security_audit：结构化请求审计，与原 operation_log 联合查询。

原 login_sessions、login_capacity_lock 继续使用。运行账号须能建表并读写上述表；审计容量查询使用 information_schema.TABLES。部署前先保全现有数据库与 INI，并确认存在未被开发账号禁用策略禁止的个人管理员。

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

新安全接口采用默认权限矩阵：账号、证书、备份、退役、维护入口为角色 4；审计读/导出、安全汇总为角色 3/4；参数修改为角色 2/3/4。矩阵见 utils/access.py，前端通过 `/api/security/roles` 对齐。

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

对外接口路径、权限及 JSON 字段保持不变：`GET /api/history/status` 的 totalBytes、usedBytes、usagePercent 改为上述文件系统统计；capacityExceeded 仍表示已用空间达到总空间（100%），不代表95%严重告警。`GET /api/security/status` 的 alerts 在使用率达到80%且不足95%时返回 `AUDIT_CAPACITY_HIGH`，提示清理、导出日志或扩容；达到95%时改为返回 `AUDIT_CAPACITY_CRITICAL`，提示尽快处理。两级容量告警不同时返回；`AUDIT_WRITE_FAILED` 独立报告，可与容量告警同时出现。告警对象仍使用 code/source 字段，未增加字段；前端需识别新增的 CRITICAL 告警码并映射提示文案。这些状态在查询时返回，不主动推送、不自动清理或扩容。空间采集失败不得报告为0%正常，安全汇总标记审计状态不可用，已存在的写入故障仍报告。

旧审计队列满/写失败与新审计写失败会触发 writeFailed。可写本地存储时写入 health/audit-write-failed，跨工作进程和重启保留；磁盘也不可写时至少保留本进程告警。排障并确认数据库、队列和磁盘恢复后，由管理员清除该文件并重启进程，重置告警。不能因单次查询成功自动解除。

新请求审计与旧业务操作日志可同时存在。旧记录的新增字段为 null，不补造来源和变更摘要；统一读取不意味着历史数据已经具备全部新增证据。

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
