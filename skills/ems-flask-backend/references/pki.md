# PKI 与 HTTPS 身份

先核对 `route_cert.py`、`custom_pki.py`、`pki_common.py`、`crl_store.py`、`https_certificates.py` 和相应测试；不要把评审报告列出的问题当作已修复。

## 模式和批次

当前 API 枚举是 `general` / `trina`，路径 `/api/cert/custom/...` 保留 custom。Python 类名、脚本名和存储目录不因枚举改名一起替换。历史 state.json 的 custom 值有读兼容，不能靠删除历史状态完成迁移。

定制入口为 `custom/key/import`、`ca/import`、`chain/import`、`identity/import`、`apply`、`status`（前缀 `/api/cert/`）。多批次并存；第一次暂存可创建 batch_id，后续沿用该 ID；暂存成功不代表已安装或服务应用成功。先区分 staged、installed、applied 和待重试服务标志。对照 active_hashes、baseline 和恢复 journal 查冲突，不直接删状态或强改批次。

旧接口是否接受 trina 以 `_cert_validate_general_mode()` 为准，不能仅因名字断定被禁止。UI 按配置显示一套流程是历史需求，不能自动当成已实现的全局后端模式开关。

共享信任根是公共材料，master/slave/https 身份各自有私钥、叶证书和中间链。清空链使用该角色、该批次的 chain/import `clear=true` 无文件方式，应用后才生效。空链适用于根直接签发，不用于忽略缺少的真实中间 CA。链顺序、根信任、时间有效性、用途、私钥匹配和 CRL 是不同校验。

外部导入身份异常或临期时应报告状态，不自动生成 CSR/私钥；先查身份来源标记及独立维护脚本版本。不要新增自动清理、重置或删除密钥功能来解决状态问题，除非用户本次要求。

## 密钥和服务

file 后端默认普通 RSA-2048，兼容普通 RSA-2048/3072；定制私钥拒绝 RSA-PSS 类型。私钥类型与 CA 证书使用 PSS 签名不是同一概念。用户指定 file 时不扩大修改到 TEE。

`/home/zlg/app/bin/modbus_tee_identity` 是设备身份工具，检查密钥、CSR 和证书匹配及私钥签验，不是通信服务器。设备报“must ... RSA-3072”但源码兼容 2048 时先查旧二进制。对应 logger 构建与实际通信程序也需核对：

```bash
cmake -S logger -B logger/build -DMODBUS_WITH_TEE=OFF
cmake --build logger/build --target tems modbus_tee_identity -j4
```

构建选项和架构按目标工具链确认，不把本机可执行文件部署到异构设备。非相关改动不必构建这些模块。

## 常见诊断

- `ISSUER_CRL_MISSING`：查真实签发者对应 CRL、信任根和中间链，不传任意根来绕过签名校验。
- self-signed / issuer verify：上传的 issuer 链不等于已信任根，先核对指纹与当前/批次信任库。
- `certificate is not yet valid`：查设备时间和 notBefore，不归因为中间链未清空。
- 证书临期阈值和证书硬失效区分；general 可准备 CSR，trina 报外部签发需求；不能据临期推出所有服务停用。
- HTTPS SAN 校验主要发生在客户端，Nginx 监听地址另查配置；SAN 不是客户端来源 IP 白名单。
- `/api/cert/https/apply` 可能处理全局待应用服务，必须读返回与 pending 状态，不能把某个服务成功当作整体成功。

应用脚本副本位于 app/script，启动维护可能调用 `/usr/local/lib/g3-https/`。只更新 app 副本不保证重启生效；安装入口和涉及副本见 `enable_https.sh`。日志通常在 `/var/log/ems/https/`；脚本返回码、诊断输出、服务状态与实际 TLS 握手分别验证。

测试入口：`test_custom_pki.py`、`test_certificate_self_test.py`、`test_ca_provisioning.py`、`test_crl_management.py`、`test_https_config.py`、`test_pki_read_cache.py`。真实 loopback TLS 测试可能需网络许可，跳过就说明范围，不能将跳过计作通过。
