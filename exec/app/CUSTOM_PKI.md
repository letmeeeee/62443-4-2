# 定制 PKI：外部设备私钥与已签发证书

定制流程支持 Modbus 主机、从机和 HTTPS 的文件身份。设备不需要先生成 CSR。
上传的私钥必须是对应设备的私钥，不是 CA 签发私钥。
只支持单份未加密 PEM 普通 RSA-2048/3072 私钥（PKCS#1 或 PKCS#8）；
拒绝 RSA-PSS 类型私钥，暂不支持 PFX、加密 PEM 或 TEE 导入。
这里限制的是设备私钥类型，不限制 CA 使用 RSA-PSS 算法签发证书。
三种身份必须使用不同私钥。

## pki_mode 参数

定制枚举已从 `custom` 更名为 `trina`，新请求必须传 `trina`。只改枚举，
接口路径 `/api/cert/custom/`、脚本名和 `.custom-pki` 目录保持不变。
历史批次和续期状态中的旧值读取时兼容为 `trina`，旧身份来源标记继续有效。
无需删除历史 state.json；单独删除会丢失批次/服务重试状态，并留下暂存材料。

| 接口 | pki_mode | 未传时 |
| --- | --- | --- |
| 原有 `/api/cert/` 通用证书接口及安全中心导入/验证别名 | `general`（通用） | 默认 general，兼容既有调用方 |
| 新增 `/api/cert/custom/` 接口 | `trina`（定制） | 返回 400 |

这只是请求参数，不是整机模式，不写入 INI。旧接口仍按原 CSR 校验规则工作。
显式传入不适合该接口的枚举值会返回 400；不存在绕过 CSR 的旧接口开关。
POST JSON 接口放在 JSON 中，上传接口放在 form-data 中，GET 接口放在 query 中。
TEE 管理接口、底层命令行参数和其他业务模块不变。

所有新接口要求管理员 Session/Bearer 身份，沿用全局 CSRF 检查。
来自 Apifox 等非同源客户端的 POST 需携带同次登录返回的 `X-CSRF-Token`。

## 上传接口

四个接口均为 POST multipart/form-data：

| 路径 | 参数 |
| --- | --- |
| `/api/cert/custom/key/import` | pki_mode、role、file、可选 batch_id |
| `/api/cert/custom/ca/import` | pki_mode、file、fingerprint（多个根时重复字段）、可选 batch_id |
| `/api/cert/custom/chain/import` | pki_mode、role、file 或 clear=true、可选 batch_id |
| `/api/cert/custom/identity/import` | pki_mode、role、file、可选 batch_id |

`role` 可选值为 `master`、`slave`、`https`。CA 根由三种身份共享，不传 role。
根指纹必须来自可信渠道，并与上传根集合完全匹配；完整 SHA-256 指纹允许带冒号。
中间链按从叶证书签发者到上级 CA 的顺序上传，不得把根放入中间链。
叶证书接口只接收一份叶证书，不能把私钥或中间链拼进同一个文件。

第一次上传不传 batch_id，响应会创建批次：

```json
{
  "status": 3,
  "message": "Custom PKI material staged; use custom apply to activate",
  "data": {
    "batch_id": "32位小写十六进制编号",
    "pki_mode": "trina",
    "status": "staged",
    "roles": {"master": ["key"]},
    "ca": false,
    "created_by": "当前管理员",
    "updated_by": "当前管理员"
  }
}
```

后续上传必须复用响应中的 batch_id；省略会创建新的独立批次。多个历史批次可以并存，
不会自动清理，也不会自动合并。apply/status 必须显式提供 batch_id。
一个批次可同时包含多个角色与共享根，暂存材料不会影响生效身份。

已配置的根、私钥或证书没有变化时，可不重复上传，应用时会使用当前生效材料。
如果替换了私钥，必须同时提供匹配的新证书。没有中间 CA 时调用链接口传
`clear=true`，不上传 file；不能上传空文件代替 clear。

## 独立应用接口

`POST /api/cert/custom/apply`，JSON：

```json
{"pki_mode":"trina","batch_id":"先前响应中的批次编号"}
```

该操作依次完成：

1. 检查完整证书链、角色 EKU、CA:FALSE、密钥用途、有效期及现有 CRL 策略。
2. 检查叶证书与私钥匹配；不读取、不生成 CSR。HTTPS CN 必须以 `LC400-` 开头（区分大小写），SAN
   覆盖当前 INI 中的设备 IP；Modbus CN 使用原身份命名规则，从机证书必须含 IP SAN。
3. 更新共享根时，同时验证其他已有身份，拒绝导致其他身份失去信任的替换。
4. 备份旧材料并记录恢复日志，再安装新私钥、完整证书链及身份来源标记。
   旧 CSR 会备份后撤下，私钥权限为 0600，公开证书为 0644。
5. Modbus 身份调用 tems.service restart/is-active；HTTPS 调用原 HTTPS 应用脚本。
   根变更会应用所有受影响的已配置身份服务。

返回的 `status` 状态：

| data.status | 含义 |
| --- | --- |
| staged | 材料暂存，尚未安装 |
| installed | 材料已安装，服务应用尚未全部成功 |
| applied | 安装和服务应用均成功 |

服务应用失败返回 HTTP 503、code=CUSTOM_PKI_APPLY_FAILED；新材料保留为一致的
已安装集合，不自动换回旧密钥。修复服务问题后用同一个 batch_id 重试，仅应用未成功
的服务。不要重新上传到已安装批次；要修改材料请创建新批次。
全局错误格式化可能只返回错误码和 trace_id，可用状态接口查询详细 pending/services。
若其他入口随后改变了生效材料，旧批次重试返回 HTTP 409、code=PKI_BATCH_CONFLICT。

`GET /api/cert/custom/status?pki_mode=trina&batch_id=...` 返回批次状态、已上传材料类型、
服务结果和 pending 列表，不返回任何私钥或私钥摘要。上传响应不代表证书已生效。

## 外部身份维护行为

成功安装后，身份目录中的 `.master-pki-source.json`、`.slave-pki-source.json` 或
`.g3-pki-source.json` 记录来源为 trina。HTTPS 自动 reconcile 对这种身份：

- 证书临近过期时记录 renewal_required 和 external_issuance_required，不生成 CSR。
- 证书无效、缺失或私钥缺失时写入异常状态并返回失败，不生成 CSR、密钥或替代证书。
- 有效身份继续正常部署，现有握手和业务报文处理不变。

管理员仍可显式调用旧 CSR 接口；当旧 identity-import 成功导入 CSR 对应证书时，
才清除该身份的 trina 来源标记，恢复原自动维护流程。手动生成 CSR 不会自行清除标记。
当前 Modbus 没有自动生成 CSR 的定时维护逻辑，来源标记为后续维护及审计保留。

## 存储、恢复与部署

批次、备份和恢复记录位于根证书目录下的 `.custom-pki/`，目录 0700、文件 0600。
其中含设备私钥及旧私钥，仅供管理员维护，不能作为公开证书包导出。
请求日志仅包含角色、材料类型、大小、批次及操作结果。维护完成后按设备策略清理
不再需要的旧批次和备份；本次未增加自动清理策略。

写入异常时会尝试恢复全部原文件。服务应用失败与文件安装失败分别处理：前者重试
应用，后者恢复原文件。多个文件的安装不具有掉电原子性，异常掉电或恢复失败时保留
`.custom-pki/recovery.json`，阻止继续上传或应用定制批次。

在停止受影响服务后，可使用本机恢复命令：

```sh
python3 /home/zlg/app/script/custom_pki.py recover \
  --config /home/zlg/lc_data_set.ini \
  --modbus-dir /etc/ems/modbus --https-dir /etc/ssl/g3
```

恢复不会自动启动服务。私钥泄露场景不能重新启用已泄露的旧密钥，应检查恢复结果后
完成新的替换。根替换继续执行现有 CRL 策略，不会自动删除或放宽吊销校验。

部署需同步更新 route_cert.py、route_security.py、security_audit.py，及 script 下的
custom_pki.py、pki_common.py、modbus_certs.py、https_certificates.py、enable_https.sh。
HTTPS 独立服务安装副本中的 https_certificates.py 和 pki_common.py 也要同步更新。
若使用离线部署工具，需同步 provisioning/device.py，以在导入失败时恢复身份来源标记；
历史 5 文件和 7 文件恢复记录仍可读取。
不需要新增数据库字段或修改 Modbus C/TEE 代码。

## 2026-11-17 兼容修复（沿用现有路径和参数）

已撤销 `/api/cert/reset`，不提供 PKI 出厂重置接口，也不再写入/使用 factory-reset
维护拦截标记。此前已经执行的服务停止和文件删除不会被升级代码自动恢复，需要
重新配置身份后显式应用；HTTPS 应用成功时会启动已安装的续期 timer。

- 保留多批次和显式 batch_id；首次上传不传编号创建独立批次，不合并、不自动删除。
- 新创建批次绑定生效根及三角色密钥/证书/链/来源版本。首次 apply 若版本变化，
  返回 409；已部署旧格式批次没有创建时快照，无法追溯比较，建议重新创建。
  CRL 更新不使 staged 批次失效，apply 始终重新验证最新吊销状态。
- 继续使用 `POST /api/cert/crls/import` 的原 form-data（pki_mode=general、file、
  可选 chain）。若不能用生效根验证，但能由已固定指纹的 staged 根验证，则自动
  暂存到所有匹配的 staged 批次，不立即改变生效根和 CRL。必须先上传定制根；
  新增的可选响应字段 staged=true、batch_ids 供诊断，原 crls/pending 字段保留。
  随后调用原 custom/apply，即统一验证并安装根、CRL和身份。并非信任任意上传的
  chain，也不会从 chain 自动提升信任根；CRL 序号和永久吊销记录回退保护继续执行。
- 通用 CA 根导入同样验证已有三角色公开证书是否能在新根集合下通过。迁移期间可
  在根文件内同时保留新旧根，指纹字段仍按原格式重复提交。
- 新叶证书在未显式上传链且能由批次根直接验证时，自动去掉继承的旧中间链。
  其他情况保留原复用规则；显式 clear=true 仍支持。失败日志包含 role 和 chain_source。
- 旧全局 apply 成功后，custom/status 会在材料版本一致时同步 installed 批次的
  pending/services/status，避免保留已完成服务的待应用状态。
- CRL 策略明确为：未配置时兼容原流程；已配置时新身份导入/定制应用要求签发者
  CRL 存在且未过期，已吊销始终拒绝。现有运行身份的过期 CRL 保留历史吊销检查，
  同时报告 stale，不修改现有 C TLS 运行策略。
- `GET /api/cert/https/status` 保持原成功包装及字段，身份健康异常以 data.valid=false、
  reason/detail 返回 HTTP 200，不生成密钥/CSR；操作类检查失败仍返回 422。
  这是健康查询行为修复，前端既有请求路径及参数不变。

部署时还需同步 crl_store.py；独立 HTTPS 服务安装目录也必须包含它。
