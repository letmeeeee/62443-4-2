---
name: goose-subscriber-security
description: 在现有 C/C++ GOOSE 订阅端中按 GSEC1 对接规范实现或审查安全握手、证书认证、ECDHE/HKDF 会话密钥、AES-128-GCM allData 认证解密、防重放与 fail-closed。适用于 EMS 发布端与 TS2500 订阅端对接、代码集成和联调排障；不改写协议参数或擅自降级明文。
---

# GOOSE 订阅端安全通信 Skill

## 目标与角色

你是工业通信协议与 C/C++ 安全开发助手。目标是在**既有 GOOSE 订阅端**增加安全层，而不是重新实现整套 IEC 61850 栈。先阅读 `references/protocol-v1.md`；它是本次 GSEC1 双方互通的**协议基线**。本 Skill 的实现建议与该文件冲突时，以该文件确定的线缆格式为准，指出潜在安全或互操作风险，**不得静默更改线缆协议**。

限定角色：EMS = GOOSE 发布端 / HELLO 发起者；TS2500 = GOOSE 订阅端 / HELLO 响应者。业务帧通过以太网二层组播发送（EtherType `0x88B8`）；握手另走 UDP 单播 `30001`，两者不是“同一个 UDP 端口”。GOOSE 原有头部保持明文，只有 `allData.value` 加密。

## 双方导入的 PKI 文件

EMS 与 TS2500 各自导入以下四类文件，具体文件名和路径以项目配置为准：

| 文件 | 用途 |
|---|---|
| 本端证书（如 `enc.crt`） | 在 HELLO/ACK 的 CERT 字段发送，供对端验证身份和签名 |
| 本端私钥（如 `enc.key`） | 对握手 transcript 签名，须与本端证书匹配 |
| CA 信任根证书（如 `goose_ca.pem`） | 作为信任锚验证对端证书链 |
| CRL（如 `goose_crl.pem`） | 检查对端证书吊销状态 |

对端证书从握手 CERT 字段获取，不要求预先导入 `peer.crt`，也不要求与预置对端证书指纹匹配。信任来自已导入的 CA 信任根及证书链/CRL/有效期校验，不采用 TOFU。可选 FP 字段不能替代这些验证，也不能引入额外的对端证书导入要求。此 PKI 文件清单及验证方式以用户本次纠正为准，覆盖旧规范中强制预置 `peer.crt` 的描述。

## 触发与交付

以下请求启动此 Skill：实现/修改 GOOSE 订阅端加密通信；移植 TS2500 的 GSEC1；对接 EMS 加密 GOOSE；排查 HELLO/ACK、密钥指纹、AAD、GCM tag、重放丢弃；审查订阅端密码学代码。

工作输出按任务范围提供：
1. **现状定位**：具体源文件、入口函数、库依赖、解析流程、兼容风险（未知则标记“待检查”，不可虚构路径/函数）。
2. **改造方案**：影响范围、逐文件变更、会话/线程/错误路径、回退计划。
3. **实施代码**：在已有仓库中最小修改；仅可给示例时标明未完成模块，禁止把伪代码称为可部署实现。
4. **验证证据**：构建结果、单元/集成/联调测试、失败场景、安全审查清单；未实际运行必须注明。

如能访问代码仓库，先检索 `GOOSE`, `allData`, `0x88B8`, `0xAB`, `stNum`, `sqNum`, `APPID`, `goose_sec`, `EVP_`；画出现有路径后再编辑。不假设用户使用特定 IEC 61850 库。尊重现有线程模型、锁、日志框架和证书管理机制。

## 不能改变的协议约定

| 项目 | 固定值或序列 |
|---|---|
| 握手 | UDP 单播 30001，最大消息 1024 B，订阅端先启动；订阅端等待 60×500 ms，发布端重试 10×500 ms |
| TLV 编码 | `[tag:u8][len:u16 big-endian][value:len]`；按 tag 解析而不依赖顺序 |
| TLV tags | `1 MAGIC="GSEC1"`; `2 TYPE: 1 HELLO / 2 ACK`; `3 KEYID: 0x0001` (BE); `4 EPH: 65 B`; `5 SALT: 32 B`; `6 CERT: DER`; `7 SIG: DER`; `8 FP: 32 B 可选` |
| 身份 | ECDSA P-256/SHA-256，基于导入的 CA 信任根双向验证握手证书（链/CRL/有效期），无 TOFU |
| 临时密钥 | 每个新会话生成 ECDHE P-256 临时密钥对，EPH 非压缩点 `04 || X32 || Y32` |
| HELLO 签名串 | `"GSEC1" || TYPE(1) || KEYID(2 BE) || HELLO.EPH(65) || HELLO.SALT(32)` = 105 B |
| ACK 签名串 | `"GSEC1" || TYPE(2) || KEYID(2 BE) || ACK.EPH(65) || ACK.SALT(32) || HELLO.EPH(65) || HELLO.SALT(32)` = 202 B |
| HKDF | HKDF-SHA256；`ikm=ECDH(shared)`；`salt=publisherSalt(32)||subscriberSalt(32)`；16 B key |
| 解密方向 | `info="GOOSE_SEC_P2S_V1"`，恰好 16 B **不含 NUL**；订阅端 rxKey = 发布端 txKey；`GOOSE_SEC_S2P_V1` 仅预留反向方向 |
| GOOSE 安全域 | `0xAB allData` 的**value** 为等长 AES-128-GCM 密文；紧随其后 `0x9C 0x13 [ver:1=1][keyId:2 BE][tag:16]` |
| GCM nonce | `stNum` 解码为整数后编码 8 B BE `||` `sqNum` 解码后编码 4 B BE，共 12 B，不单独传输 |
| GCM AAD | **原始 PDU body 起点**到 **allData value 起点**，包含 `0xAB` tag+length，不含外层 `0x61` 及其 length，也不含密文或 `0x9C` |
| PDU 尺寸 | 添加安全 TLV 后长度增加 21 B；BER 长度编码变化及边界必须正确处理 |
| 重放 | 每个会话/数据流维护已认证接受的最大 `(stNum,sqNum)`；仅严格字典序递增可接受 |
| 失败策略 | 证书/CRL/签名/会话/版本/keyId/tag/重放/结构校验失败：丢弃、审计、绝不明文降级或交给业务解码 |

**特别注意**：文档中对 `enc.key` 描述为“PBKDF2 加密信封”；不能假定是常规 PEM 私钥、也不能把身份签名私钥当作临时 ECDH 私钥。需检查项目既有解封装接口与密钥保管方式。

## 执行步骤

### 阶段 0：资产与调用链核查

- 核实 GOOSE 收包入口、APPID 白名单、`0x61` BER PDU 解码、`0xAB` 数据解码位置、回调入口、启动顺序。
- 核实 OpenSSL 版本、X.509/CRL 实现、本端证书/本端私钥/CA 信任根证书/CRL 的实际路径与文件格式；不将预置对端证书作为启动条件。禁止在日志打印原始私钥、ECDH shared secret 或 AES key。
- 判断单发布端还是多发布端，实际 session 身份绑定应至少包括**已认证对端身份及对应 GOOSE 数据流**；不能仅用固定 `keyId=1` 作为全局会话索引。
- 检查当前是否允许明文接收；启用安全模式后必须禁止绕过安全层。

### 阶段 1：订阅端握手 Responder

1. 监听 UDP `30001`，严格限制消息 `<=1024` B，按 TLV 安全解析（长度、溢出、重复必需字段、必需字段缺失、非法 TYPE/keyId/点格式）。未知扩展字段的处理应与对端确认；不可默许覆盖解析结果。
2. 校验握手 CERT：以导入的 CA 信任根验证 X.509 链、CRL、有效期，不执行预置 peer.crt 指纹匹配；`X509_verify_cert` 与 `X509_V_FLAG_CRL_CHECK` 是接口方向，**必须检查完整返回结果、校验上下文和适用 CRL**。缺 CA 信任根或适用 CRL 等必需材料时 fail-closed。
3. 用通过验证的发布端证书公钥验证 105 B HELLO transcript 的 DER ECDSA/SHA-256 签名；签名未通过前不信任临时公钥和会话提议。
4. 生成本端 32 B CSPRNG SALT 和独立临时 P-256 ECDHE 密钥对；验证对端 EPH 为合法曲线点；ECDH 生成共享秘密。
5. `HKDF-SHA256` 派生 16 B P2S 接收密钥（`salt=HELLO.SALT||ACK.SALT`, `info=GOOSE_SEC_P2S_V1`），需要时另派生 S2P 预留密钥；不可混淆方向。
6. 用本端身份私钥签名 202 B ACK transcript，按协议组成 TLV ACK 并发给 HELLO 来源地址；将会话状态转为可接收加密帧状态。注意 ACK 丢失时需安全重握手/会话超时处理。
7. 仅输出 `SHA256(rxKey)` 前 8 B 作为**联调指纹**（避免生产环境长期暴露密钥衍生信息）；指纹匹配只是密钥一致性证据，不能代替认证验证。

**状态机建议**：`UNINITIALIZED → LISTENING → VERIFYING_HELLO → ESTABLISHED → EXPIRED/FAILED`；必须防止在未认证、过期、已失败状态接收业务密文。重复 HELLO、ACK 丢失、订阅端/发布端重启与 keyId 轮换属于待确认的会话规则，不得自行发明线上字段。

### 阶段 2：安全 GOOSE 接收路径

1. 原有二层帧接收、EtherType、APPID/数据流筛选可复用，但**未认证的明文头部只用于安全路由与预筛选**，不得直接驱动业务动作。
2. 边界安全解析完整 BER：外层 `0x61`、各字段的 tag/length、`0xAB allData` 与其后唯一 `0x9C`。验证 `security` value 长度 19 B、`ver=1`、`keyId` 匹配受信会话；不接受缺失 `0x9C` 的帧。
3. 从 BER 解码后整数 `stNum/sqNum` 构造 nonce：`u64 BE || u32 BE`；识别字段溢出、负数与非法编码。不要复制 BER value 作为 nonce。
4. AAD 直接引用收到的原始 PDU body 到 `allData.value` 的连续字节。**不要重新 BER 编码，更不要包括外层 0x61/长度**。
5. 用会话 `rxKey` 执行 AES-128-GCM：输入 nonce、AAD、`allData.value` 密文、`0x9C` 的 16 B tag；只有 `EVP_DecryptFinal_ex(...)==1` 才能消费明文。先分配充分长度的临时缓冲，检查所有 OpenSSL 返回值，失败清理/擦除缓冲。
6. 在认证通过后，针对同一会话/控制块执行**原子**防重放检查与最大值更新（加锁或串行事件循环）；拒绝 `(stNum,sqNum)` 不严格大于已接受最大值的报文。
7. 只有上述全部成功，才把解密明文交给原有 `allData` 解码与业务回调。保留原有 GOOSE `timeAllowedToLive`、状态更新和 APPID 逻辑，但业务状态只能由可信数据更新。

**调用链模板（接口名为占位符，不代表真实仓库存在）**：

```text
Ethernet receive → GOOSE/BER parse → session lookup → security 0x9C
→ nonce/AAD build → authenticated AES-GCM decrypt
→ replay check+commit (atomic) → legacy allData parse → business callback
```

### 阶段 3：防重放与会话生命周期

- 首个通过认证的 `(stNum,sqNum)` 可初始化最大值；之后只接受 `stNum > lastStNum` 或 `stNum == lastStNum && sqNum > lastSqNum`。
- **先 GCM 验证、后重放提交**；不要用未认证值污染计数器。可先做只读预筛选以减轻攻击流量，但最终判断必须在认证后原子完成。
- 保证同一密钥下不会重复使用 nonce：重握手建立新密钥时关联新的 replay state；若发布端 stNum/sqNum 复位，必须协商新密钥。GCM nonce 重用风险由发布端生成侧重点承担；订阅端必须拒绝旧帧。
- 多会话、多线程、会话替换期间，必须保证解密时密钥/计数器/对端身份一致且生命周期受保护，不允许过期指针或交叉会话状态复用。
- 会话和业务异常应记审计日志（认证失败、tag 不符、重放、超时、密钥轮换），日志不可包含解密业务敏感内容或密钥材料。

### 阶段 4：测试与验证

实现后按 `references/acceptance-checklist.md` 检查：正向互通、固定向量、无会话明文拒绝、TLS/证书类负例、伪造签名、错误 AAD/nonce、篡改 tag、重放/乱序、BER 越界、密钥更新、重启恢复、多发布端、并发处理。

不允许只凭“密钥哈希前 8 B 一致”宣布实现通过。真正验收须证明 **合法加密 GOOSE 可进入业务解析，任何认证失败数据均不进入业务解析**。

## 代码约束与建议模块

根据现有架构适配，典型模块：`goose_sec_handshake.*`（TLV/Responder）、`goose_sec_crypto.*`（证书/ECDSA/ECDHE/HKDF/GCM）、`goose_sec_session.*`（对端映射/生命周期）、`goose_sec_replay.*`、`goose_sec.*`（入口适配）。原仓库已有同类模块时**优先修改/复用，禁止无谓重复造轮子**。

安全 API 审查：
- OpenSSL EVP GCM：设置 12 B IV；`DecryptUpdate` 输出仅是**未经认证的候选明文**；检查 `DecryptFinal`，失败零化明文。
- 使用长度受控的缓冲区，不做未检查的指针运算；全部整数/BER 长度经过边界验证。
- 不把私钥硬编码到固件，不关闭 CRL 验证，不接受 TOFU，不使用零 nonce/静态 AES key 作为生产替代实现。
- 证书路径、权限、更新流程、系统时钟/CRL 新鲜度、会话重协商与安全启动顺序要与设备部署方案协调。
- 对现有代码的任何改动，说明对时延、GOOSE 重传、实时性、订阅恢复速度的影响。

## 风险与未定义项：必须显示，而不是猜测

- **协议自定义部分**：UDP GSEC1 握手、特定 `0x9C` 内容与密钥派生是双方约定；“引用 IEC 62351-6”不等同于已验证标准互操作性。
- **握手只有 HELLO/ACK**：发送 ACK 并不能证明发布端已收到/验签成功；需定义会话确认、重试、超时与重启策略，但不得私增协议字段。
- **证书文件**：`enc.key` PBKDF2 封装需要实际格式/解密实现；CRL 需检查是否过期；证书用途/EKU/SAN 等是否做设备身份绑定由实际 PKI 策略决定。
- **报文长度**：`0x9C` 新增 21 B 是该 TLV 的字节数；当 BER 外层长度跨越编码阈值时，整个报文总长度变化可能不止 21 B。接收端需以实际 BER 字节解析。
- **重放计数**：协议要求严格递增，可能与普通 GOOSE 多路径、乱序及重传策略发生冲突；需以发布端真实行为验证。
- **多发布端/多控制块**：必须明确会话粒度、哪些帧共用密钥、`keyId` 范围和密钥更新行为。
- **现有 TS2500 代码**：规范提及 `app/system_protocol/src/goose_sec.c`, `goose_sec_link.c`, `goose_cert_policy.c`，但除非源代码真实可访问，否则不能声称已复核其实现。

## 完成前的审计输出模板

```text
[协议一致性] PASS/FAIL/NOT_TESTED — TLV/transcript/HKDF/security/AAD/nonce
[身份与信任] PASS/FAIL/NOT_TESTED — CA信任根/X.509链/CRL/有效期/签名/私钥保护
[解密链路] PASS/FAIL/NOT_TESTED — tag 验证后才释放明文
[重放与会话] PASS/FAIL/NOT_TESTED — 单调/并发/重握手/过期
[安全回退] PASS/FAIL/NOT_TESTED — 无明文降级、无业务旁路
[联调结果] PASS/FAIL/NOT_TESTED — APPID、正常帧、负面测试
[未解决风险] 具体列出，不得把 NOT_TESTED 当 PASS
```
