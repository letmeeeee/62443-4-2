# GOOSE 安全接收与 PKI 对接

`middle.c` 当前启用的是 EMS GOOSE → Modbus TCP 桥接。此次只替换上层收包入口；保留
原有寄存器映射、队列、Modbus TCP、共享内存及停用的下层发布逻辑，不修改 libiec61850。
加密功能是订阅端的认证解密；EMS 发布端仍须按 GSEC1 生成加密报文。

## 运行链路

`security/goose_transport.c` 在原 `net2` 网口监听 UDP 单播 30001 和二层 GOOSE；
只有通过认证解密与防重放的报文才能通过 `GooseReceiver_handleMessage` 进入原解析器。
不启动 libiec61850 自带接收线程，避免存在明文旁路。原业务回调额外检查解析有效性，
解析失败不下发 Modbus。接收线程独占会话与计数器，无需跨线程共享密钥。

固定订阅范围沿用原代码：APPID `0x1000`、目的 MAC `01:0c:cd:01:00:00`、
`gocbRef=TEMPLATEPIGO/LLN0$GO$gocb1`。实例仅支持一个发布端、一个控制块。
不要将其扩展为多个控制块共用同一密钥；原 nonce 不含流标识，多流重复计数会复用 nonce。

密码参数遵循仓库《GOOSE加密对接规范-给EMS-20261109.md》，PKI 文件清单以用户纠正为准：

- 双向 ECDSA P-256/SHA-256，验证 CA 链、CRL、有效期、非 CA 身份及 digitalSignature 用途。
- ECDHE P-256 临时密钥；HKDF-SHA256 使用发布端盐在前、订阅端盐在后，P2S info 固定 16 B。
- AES-128-GCM 只解密 allData.value；nonce 为 stNum 的 8 B BE 加 sqNum 的 4 B BE。
- AAD 引用接收原始 body 到 allData.value 前的字节，不重新编码，不含外层 0x61/length。
- 只接受唯一且紧邻 allData 的 `9C 13 01 00 01 <16B tag>`；当前拒绝尾随扩展字段。
- 认证通过后检查 allData BER 和条目数，再提交严格递增的 `(stNum,sqNum)`。
- 重建明文 PDU 和 GOOSE Length 时处理 BER 长度边界，支持普通帧和单层 802.1Q VLAN。
- stNum/sqNum 当前限制在原 libiec61850 支持的 uint32 范围；stNum 仍按 8 B 编入 nonce。

## PKI 文件与独立管理

双方各导入本端证书、本端私钥、CA 信任根、CRL；不导入 `peer.crt`。对端证书来自握手
CERT 字段，不执行对端证书指纹固定。FP TLV 仅兼容解析，不作为信任依据。

GOOSE 使用独立文件目录，默认 `/etc/ems/goose`，不复用或改写 TLS 的根证书/CRL/角色文件：

```text
/etc/ems/goose/                    # 0700，属运行/导入用户
  batches/<batch_id>/              # 私有上传暂存
  releases/<batch_id>/             # 校验完成的完整四文件快照
    enc.crt                       # 本端证书，可附中间 CA 链，PEM
    enc.key                       # 本端 EC P-256 私钥，PEM，0600
    ca-roots.crt                  # 自签名 CA 信任根，PEM
    crls.pem                      # CRL，可附未受信任的中间 CA 证书，PEM
  current -> releases/<batch_id>   # 原子切换整套材料
```

私钥采用现有 TLS 文件私钥导入方式：**未加密的 PKCS#8/EC PEM，由文件权限保护**。
不生成私钥、不导出私钥，也不将身份私钥用于临时 ECDH。
旧规范未提供 PBKDF2 私钥信封格式，当前不支持该自定义信封或带密码私钥；不能将其直接
改后缀上传。必须提供与本端证书匹配的 TLS 文件后端格式私钥。

CRL 必须由受信任链签发，含 AKI/CRLNumber，不能过期；支持按 TLS CRL 管理规则防止
CRL 号回退、同号内容冲突或移除既有吊销条目。中间 CA 仅参与链构建，不提升为信任根。
需要提供身份完整链对应的 CRL；其他对端中间 CA 可随 CRL 包附带。
握手 CERT 仍是单张 DER 叶证书，叶证书必须满足 1024 B 握手预算。

首次申请一个批次，后续上传携带同一个 `batch_id`。材料上传顺序任意；apply 前必须
四项齐全且匹配。更新已有配置时，新批次快照现有四文件，可只上传变化的材料。
过时批次不能覆盖后来已应用的配置。切换后重启失败保留 installed/pending，重试同一
批次；不会因为服务重启失败而自动回滚信任根或恢复旧吊销状态。

## 后端接口

新增接口位于 `exec/app/routes/route_cert.py`，复用 TLS 的 Session、管理员授权、CSRF、
审计及错误响应机制。旧 TLS 接口/参数及其 PKI 模式保持原行为。GOOSE 接口无需指定
TLS 的 pki_mode，不使用 CSR，也不调用 nginx/tems 的重启。

| 方法与路径 | 参数与作用 |
|---|---|
| POST `/api/cert/goose/identity/import` | multipart `file`、可选 `batch_id`，暂存本端证书（可含链） |
| POST `/api/cert/goose/key/import` | 同上，暂存 EC P-256 私钥 |
| POST `/api/cert/goose/ca/import` | 同上，暂存 CA 信任根 |
| POST `/api/cert/goose/crl/import` | 同上，暂存 CRL（PEM/DER，可带 PEM 颁发者证书） |
| GET `/api/cert/goose/status` | 当前代次、公开证书指纹和 CRL 状态，不返回私钥 |
| GET `/api/cert/goose/status?batch_id=...` | 查询批次状态 staged/installed/applied |
| POST `/api/cert/goose/apply` | JSON `{"batch_id":"..."}`，验证、原子切换并重启 GOOSE 服务 |

写请求带现有登录令牌与 `X-CSRF-Token`，例如：

```bash
curl "$BASE/api/cert/goose/identity/import" \
  -H "Authorization: Bearer $SESSION_TOKEN" -H "X-CSRF-Token: $CSRF_TOKEN" \
  -F file=@enc.crt
# 从返回 data.batch_id 取出批次标识，随后三项均携带同一个 batch_id。
curl "$BASE/api/cert/goose/key/import" \
  -H "Authorization: Bearer $SESSION_TOKEN" -H "X-CSRF-Token: $CSRF_TOKEN" \
  -F "batch_id=$BATCH_ID" -F file=@enc.key
# CA/CRL 上传方式同上，接口路径分别为 ca/import 和 crl/import。
curl "$BASE/api/cert/goose/apply" \
  -H "Authorization: Bearer $SESSION_TOKEN" -H "X-CSRF-Token: $CSRF_TOKEN" \
  -H 'Content-Type: application/json' --data "{\"batch_id\":\"$BATCH_ID\"}"
```

Flask 配置 `GOOSE_PKI_DIR` 与进程环境同名变量须指向同一目录。
`GOOSE_SERVICE` 默认 `goose_middle.service`，可在 Flask 配置中指定实际 unit 名。
apply 会执行 `systemctl restart` 和 `is-active`；503 表示文件已安装但应用失败，需要重试。
没有修改现有前端构建产物；调用方需对接上述新增接口。

## 会话恢复策略与互通边界

- 相同 HELLO（同来源 IP、相同签名参数）返回缓存 ACK，不重新派生密钥或重置防重放状态。
- 当前实例最近 30 秒内接受过业务帧，或刚建立会话时，不以另一 HELLO 替换密钥。
  连续空闲达到 30 秒后可用新临时参数重新协商，第一帧会重置旧解码器的计数器。
- 初始等待 30 秒无握手时打印告警并继续监听，便于 EMS 延后启动。
- 上述是本实现明确采用的本地恢复策略，未增加或改变任何线上字段，需要与 EMS 联调确认。
  EMS 若在旧会话仍活跃时重启，其 5 秒重试窗口可能不足；应在空闲窗口后重新发起握手，
  或在维护期间重启订阅端。仅两报文协议未提供额外的 Finished/会话确认消息。
- 证书及 CRL 的有效性按墙钟秒边界重检；异常帧不更新计数器/活动时间。
  证书、CRL 更新通过 apply 重启生效，运行实例持有启动时同一代次快照。
- 严格单调策略拒绝乱序帧；不能据此宣称支持多发布端、组密钥分发或标准安全 GOOSE 互通。

## 编译与部署

依赖 OpenSSL >=1.1.1 的 libcrypto、pthread、rt，以及与目标架构相同的现有 libiec61850。
CMake 默认 ARM64 交叉编译；修正了原工程的固定开发机路径，支持指定库构建目录。

```bash
# ARM64：OPENSSL_INCLUDE_DIR/OPENSSL_CRYPTO_LIBRARY 应来自目标设备 SDK。
cmake -S . -B build-secure-arm -DUSE_CROSS=ON \
  -DLIBIEC_BUILD=/path/to/arm64/libiec61850/build \
  -DOPENSSL_INCLUDE_DIR=/path/to/arm64/openssl/include \
  -DOPENSSL_CRYPTO_LIBRARY=/path/to/arm64/libcrypto.so
cmake --build build-secure-arm --target goose_middle -j4

# 本机验证：先本机构建 libiec61850，再选择相同架构的构建目录。
cmake -S ../libiec61850 -B /tmp/goose-lib-native -DBUILD_EXAMPLES=OFF
cmake --build /tmp/goose-lib-native -j4
cmake -S . -B /tmp/goose-middle-native -DUSE_CROSS=OFF -DLIBIEC_BUILD=/tmp/goose-lib-native
cmake --build /tmp/goose-middle-native --target goose_middle -j4
```

部署内容：新 `goose_middle`、后端 `script/goose_pki.py` 和更新后的 `routes/route_cert.py`。
`deploy/goose_middle.service` 是服务模板。仓库根 `deploy/deploy.py` 已将安全程序和模板
纳入升级包；设备没有 GOOSE 服务时安装模板但不自动启动/enable，已有服务保留原配置
并按原启停状态恢复。部署不改动 GOOSE PKI 或日志；详见仓库 `deploy/README.md`。
本地仅生成升级包不会修改运行设备。
进程需要 raw socket / SO_BINDTODEVICE 权限；运行用户须与 PKI 导入文件属主一致。
示例以 root 运行，二进制路径为 `/home/zlg/goose/goose_middle`，部署时按实际服务调整。
后端新增路由需要重启后端进程生效。不要同时启动旧的明文 GOOSE 桥接程序。

日志默认 `/mnt/nvme/goose_log/YYYY-MM-DD.log`，格式与 DPrint 一致：

```text
[2026-11-17 15:00:00.123456] [goose_security.c:123] [gsec_hello] [INFO] GOOSE session established...
```

同时输出 stderr；`GOOSE_LOG_DIR` 可更改目录。记录 PKI 加载、握手、拒绝原因、首帧和
每 1000 帧统计、Modbus 转发及退出事件；异常帧日志做计数抽样。日志目录父路径须存在，
不可写时 stderr 告警。当前按天分文件，保留/清理由设备日志策略管理，不自动删除。
调试环境可设置 `GOOSE_DEBUG_KEY_FINGERPRINT=1` 打印 P2S 密钥 SHA256 前 8 B；默认关闭，
不输出原始密钥、共享秘密或解密业务数据。

回退代码时需先停止 GOOSE 入口，保留 PKI 代次以供人工检查；不得在线自动回退为明文。

## 验证

```bash
GOOSE_TEST_LIBIEC=/tmp/goose-lib-native/src/libiec61850.so PYTHONPATH=/path/to/repo/exec/app \
  python3 -m pytest tests/test_goose_security.py /path/to/repo/exec/app/tests/test_goose_pki_api.py -q
```

测试使用独立 Python EMS 与真实 C 订阅端密码实现，包含双向签名、ECDH/HKDF、GCM、
真实 libiec61850 回调、篡改、明文拒绝、重放、重复 HELLO、重启、证书链/吊销/过期、
BER 长度边界、VLAN、PKI 批次与失败重试、文件权限、API 认证/管理员/CSRF和 TLS 隔离。
原 TLS 定制 PKI、CRL 管理及 TLS 1.2/1.3 回环测试单独回归。

当前未完成实机 EMS/TS2500 二层网络及 Modbus 设备联调；实际时延、乱序行为、30 秒
恢复策略、设备 OpenSSL SDK/运行库和服务启动顺序仍需在目标环境验证。

本次本地执行证据（2026-11-17）：

- 新增密码协议、PKI、真实 libiec61850 回调和 HTTP 测试：34 项通过。
- 现有 `test_custom_pki.py`、`test_crl_management.py`：72 项在沙箱内通过；另外 8 项
  TLS 1.2/1.3 回环测试在允许本地 socket 的环境重跑通过（沙箱内禁止创建 socket）。
- 本机与 ARM64 `goose_middle` 均构建通过；原代码停用函数的 unused-function 告警仍保留。
  ARM64 链接仓库 `logger/mysqlib/lib/libcrypto.so.1.1`，使用本机 OpenSSL 1.1.1 同系列
  公开 API 头文件作交叉构建检查；未验证设备 SDK 的头文件和实际运行环境。
  ELF 未嵌入开发机 SDK 路径，仍需设备提供对应的 libcrypto.so.1.1。
- Clang 静态分析覆盖密码、传输、日志三个新增 C 模块；缺 PKI 的二进制启动检查确认
  非零退出、不启动业务桥接。
- 30 秒空闲后的在线重握手、实际网卡/设备重启、实时延迟及现场互通标记为 NOT_TESTED，
  不以本地测试代替现场验收。
