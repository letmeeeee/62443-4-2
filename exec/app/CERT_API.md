# Modbus TLS 证书管理接口调用说明

本文按当前 `routes/route_cert.py`、`utils/auth.py`、`config.py` 和 `logger/scripts/modbus_certs.py` 整理，适用于前端接入、Postman 和设备端调试。示例响应中的证书内容、指纹和输出为示意值。

## 1. 入口与接口总览

设备 HTTPS 入口示例：`https://192.168.2.136`。接口注册在主应用 `g3_bp` 上，无额外蓝图 URL 前缀，由主服务处理，不走独立 9000 升级查询服务。

这些接口管理的是 **Modbus TLS 身份证书和从机对主机的信任文件**，不是浏览器访问网页时 Nginx 使用的 HTTPS 证书。

| 方法 | 路径 | 用途 | 参数位置 | 成功返回 |
| --- | --- | --- | --- | --- |
| GET | `/api/cert/identity` | 查询本机身份信息 | Query：`role` | JSON，`data.certificate` 为信息文本 |
| POST | `/api/cert/generate` | 首次生成本机证书 | JSON | JSON，包含 `restart_required` |
| POST | `/api/cert/renew` | 备份并更新已有本机证书 | JSON | JSON，包含 `restart_required` |
| GET | `/api/cert/check` | 校验证书及其对应的 TA 密钥 | Query：`role` | JSON，`data.valid: true` |
| GET | `/api/cert/trust-list` | 查询从机信任的主机证书 | 无 | JSON，`data.output` 为文本 |
| POST | `/api/cert/trust-add` | 上传并导入一个可信主机证书 | multipart/form-data | JSON，包含 `restart_required` |
| POST | `/api/cert/trust-remove` | 按 SHA-256 指纹删除可信主机证书 | JSON | JSON，包含 `restart_required` |
| GET | `/api/cert/export` | 下载本机公开证书 | Query：`role` | `.crt` 文件，非 JSON |

## 2. 认证、权限和通用响应

### 2.1 请求头

先调用 `POST /permission/login` 登录，从响应中取得 `session_token` 和 `csrf_token`。所有证书接口均携带真实会话凭据：

```http
Authorization: Bearer <session_token>
```

所有接口，包括查询和导出，都要求权限属于 `config.PERMISSION_TABLE["usermanage"]`；当前配置为 `[4]`。Body 中的 `role` 是证书角色，不是登录用户权限。接口不接受客户端提交的管理员身份，也不需要 `operatorName`。

POST 请求建议统一携带：

```http
X-CSRF-Token: <csrf_token>
```

当前后端允许通过同源来源检查的写请求；缺少同源信息的 Postman、curl 等客户端应发送匹配的 CSRF Token。仅有 CSRF 或 Cookie 不能替代 Bearer；`Bearer ok` 不是有效会话。

JSON 请求设置 `Content-Type: application/json`；文件上传由浏览器或 Postman 自动设置带 boundary 的 multipart Content-Type。不要把 Token 拼进 URL。

### 2.2 JSON 响应

当前配置中 `STATE_DONE = 3`，`STATE_ERROR = -1`。证书接口使用 `status/message/data`，不是业务接口中的 `ok`：

```json
{
  "status": 3,
  "message": "certificate information retrieved",
  "data": {"role": "master", "certificate": "subject=...\nissuer=...\nSHA256: ..."}
}
```

通常的证书接口错误：

```json
{"status": -1, "message": "role must be master or slave"}
```

全局认证/CSRF 钩子可能在进入证书函数前返回另一种结构，例如：

```json
{"ok": false, "code": "SESSION_INVALID", "error": "Authentication required"}
```

前端应同时判断 HTTP 状态，错误提示兼容 `message` 和 `error`。所有证书业务响应均禁止缓存。

## 3. 本机身份证书

### 3.1 GET /api/cert/identity：查询本机证书

```http
GET /api/cert/identity?role=master
```

| Query 参数 | 必填 | 说明 |
| --- | --- | --- |
| `role` | 是 | `master` 或 `slave`，服务端去除首尾空白并转小写，无默认值 |

- `master`：本机作为 Modbus 主机，证书用途为 TLS clientAuth。
- `slave`：本机作为 Modbus 从机，证书用途为 TLS serverAuth。

HTTP 200：

```json
{
  "status": 3,
  "message": "certificate information retrieved",
  "data": {
    "role": "master",
    "certificate": "subject=CN=master-001\nissuer=CN=master-001\nnotBefore=...\nnotAfter=...\nSHA256: ..."
  }
}
```

`certificate` 是脚本输出的信息文本，不是 PEM 证书，也没有独立的 subject、issuer、指纹 JSON 字段。显示时应按普通文本处理，例如 `<pre>`，不要当作 HTML 渲染。

角色错误返回 400；脚本失败或证书缺失等返回 500。此接口主要显示信息，不能代替 `/check` 的完整校验。

### 3.2 POST /api/cert/generate：首次生成

```json
{
  "role": "slave",
  "name": "slave-001",
  "days": 365,
  "ip": ["192.168.2.136", "192.168.3.136"],
  "dns": ["device.example.local"]
}
```

`generate` 和 `renew` 共用以下参数：

| JSON 字段 | 必填 | 默认值 | 规则 |
| --- | --- | --- | --- |
| `role` | 是 | 无 | `master` / `slave`，忽略首尾空白和大小写 |
| `name` | 是 | 无 | 设备 CN；1–64 个字符，以英文字母或数字开头，其余仅字母、数字、`_`、`.`、`-`；去除首尾空白 |
| `days` | 否 | `365` | 1–3650；前端按 JSON 整数发送，布尔值被拒绝 |
| `ip` | 否 | `[]` | 单个 IP 字符串或字符串数组；每项为合法 IPv4/IPv6 地址；`null` 按空列表处理 |
| `dns` | 否 | `[]` | 单个 DNS 字符串或字符串数组；每项最多 253 字符，标签按字母/数字/连字符规则校验；不支持通配符、尾随点或直接传中文域名；`null` 按空列表处理 |

实现中 `days` 使用 `int()` 转换，会接受可转换的字符串，部分非整数数值也可能被截断；前端不要依赖这种宽松转换。

HTTP 200：

```json
{
  "status": 3,
  "message": "certificate generated successfully",
  "data": {
    "role": "slave",
    "name": "slave-001",
    "days": 365,
    "output": "已生成: /etc/ems/modbus/slave.crt\nSHA256: ...\n...",
    "restart_required": true
  }
}
```

首次生成不会覆盖该角色已有 `.crt`。已有证书时脚本失败，接口返回 500 / `certificate generation failed`；应按维护流程改用 `renew`，不能把生成当作覆盖接口。参数错误返回 400。

### 3.3 POST /api/cert/renew：更新已有证书

参数与 `generate` 相同，例如：

```json
{"role":"master","name":"master-001","days":365,"ip":[],"dns":[]}
```

成功响应结构与生成相同，`message` 为 `certificate renewed successfully`，`data.restart_required` 为 `true`。

- 要求该角色已有 `.crt`；不存在时返回 500 / `certificate renewal failed`，首次创建应使用 `generate`。
- 脚本备份旧公开证书，复用对应角色的 TA 私钥；首次迁移可能创建 TA 密钥。不应理解为每次续期都轮换私钥。
- **IP/DNS SAN 需要重新提交**，不能省略后期待自动继承旧 SAN。
- 应在维护流程已停止相关 `tems` 进程后调用。接口本身不会帮忙停止或重启服务。
- 更新主机证书后，需要将新的 `master.crt` 导入相关从机的信任文件。

### 3.4 GET /api/cert/check：有效性检查

```http
GET /api/cert/check?role=slave
```

`role` 规则与查询接口相同。当前脚本校验直接自签身份、有效期、`CA:FALSE`、角色用途，并通过 `modbus_tee_identity check` 检查与 TA 中对应角色密钥的匹配。

HTTP 200：

```json
{
  "status": 3,
  "message": "certificate check passed",
  "data": {"role":"slave","valid":true,"output":"校验通过：自签名、有效期、用途和私钥匹配\n..."}
}
```

检查未通过返回 **HTTP 422**：

```json
{"status":-1,"message":"certificate check failed","data":{"role":"slave","valid":false}}
```

注意：此函数把所有 `CertificateScriptError` 都映射为 422，包含证书不符合要求、文件/脚本缺失、执行失败或超时，不能只凭 `valid:false` 认定证书已过期。具体原因查后端日志。角色参数错误为 400。

### 3.5 GET /api/cert/export：导出公开证书

```http
GET /api/cert/export?role=master
```

成功返回文件：

```http
Content-Type: application/x-pem-file
Content-Disposition: attachment; filename=master.crt
Cache-Control: no-store
```

`slave` 对应 `slave.crt`。只支持白名单中的两个公开证书，不支持任意路径或私钥下载。下载前会先执行 `/check` 对应的脚本校验。

成功体是 PEM 文件内容，不应调用 `response.json()`。角色错误为 400，证书文件不存在为 404；校验、脚本或读取失败通常为 500，错误体为 JSON。

## 4. 从机信任的主机证书

信任文件为 `/etc/ems/modbus/master-ca.crt`。虽然文件名包含 `ca`，当前脚本管理的是直接自签的主机公开证书集合，不是通用 CA 链导入接口。

### 4.1 GET /api/cert/trust-list：查询信任列表

不需要 Query 或 Body。HTTP 200：

```json
{
  "status": 3,
  "message": "trusted certificates retrieved",
  "data": {"output":"可信主机证书数量: 1\nsubject=CN=master-001\nissuer=CN=master-001\nnotBefore=...\nnotAfter=...\nSHA256: ..."}
}
```

没有 `certificates` 数组、独立的 `count` 或指纹字段；目前返回多行文本。若前端需要逐条操作，必须从文本提取指纹，或后续扩展结构化响应。信任文件缺失/为空时，当前脚本可返回数量为 0 的成功结果；读取或解析失败返回 500。

### 4.2 POST /api/cert/trust-add：上传并导入

Body 必须使用 **multipart/form-data**，不能用 raw JSON 或 binary 替代：

| 表单字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `file` | File | 是 | 一个主机公开证书，文件名必须以 `.crt` 结尾，大小写不敏感；内容必须是 PEM |
| `fingerprint` | Text | 否 | 完整 SHA-256 证书指纹，用于与导入证书核对 |

- 文件不能空，最大 **1,048,576 字节（1 MiB）**，超出时接口返回 413。
- `.pem` 扩展名即使内容是 PEM 也不被当前 HTTP 接口接受。
- 只导入单个直接自签、`CA:FALSE`、用途包含 TLS clientAuth 且通过有效期和自签名检查的主机证书；不接受私钥、CSR、证书链或 CA 签发的设备证书。
- 指纹允许 64 位连续十六进制或 32 组冒号分隔的十六进制字节，不区分大小写，首尾空白会去除；不能使用缩写或省略号。
- 指纹不匹配、证书内容校验失败等脚本错误返回 500，不是 400；格式参数错误返回 400。
- 重复导入同一指纹不会重复添加；接口仍返回成功和 `restart_required:true`，是否实际写入需看 `output`。

HTTP 200：

```json
{
  "status": 3,
  "message": "trusted certificate imported successfully",
  "data": {"output":"可信主机证书数量: 1 SHA256: ...\n重启 tems 后生效；脚本不会自动重启。","restart_required":true}
}
```

### 4.3 POST /api/cert/trust-remove：按指纹删除

```json
{"fingerprint":"0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF"}
```

`fingerprint` 必填，格式规则与导入一致。只能按完整证书指纹删除，不接受用户名、设备名称、证书文件名或会话 `session_id`。

HTTP 200：

```json
{
  "status": 3,
  "message": "trusted certificate removed successfully",
  "data": {
    "fingerprint":"0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF",
    "output":"旧信任文件备份: ...\n可信主机证书数量: 0 SHA256: ...\n...",
    "restart_required":true
  }
}
```

返回指纹已规范化为不带冒号的大写字符串。参数错误为 400；目标指纹不存在时，当前脚本报错，接口返回 **500** / `failed to remove trusted certificate`，并非 404。

删除最后一张信任证书后，当前 TLS 实现重启时不会启动从机监听。替换信任时应先导入新的主机证书，再删除旧证书。

## 5. 前端 fetch 示例

以下以同源页面为例。登录成功时需保存真实凭据，`csrfToken` 是下面示例约定的存储键：

```javascript
sessionStorage.setItem('authToken', loginData.session_token);
sessionStorage.setItem('csrfToken', loginData.csrf_token);
```

JSON 查询/写入与文件上传可共用：

```javascript
function certHeaders(write = false) {
  const token = sessionStorage.getItem('authToken');
  if (!token || token === 'ok') throw new Error('请先登录获取真实会话凭据');
  const headers = { Authorization: `Bearer ${token}` };
  const csrf = sessionStorage.getItem('csrfToken');
  if (write && csrf) headers['X-CSRF-Token'] = csrf;
  return headers;
}

async function certRequest(path, { method = 'GET', json, form } = {}) {
  const headers = certHeaders(method !== 'GET' && method !== 'HEAD');
  if (json !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, {
    method,
    headers,
    body: form !== undefined ? form : (json === undefined ? undefined : JSON.stringify(json))
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.status !== 3) {
    throw Object.assign(new Error(data.message || data.error || `HTTP ${response.status}`), {
      httpStatus: response.status, responseData: data
    });
  }
  return data;
}

async function loadCertificates() {
  const identity = await certRequest('/api/cert/identity?role=master');
  const checked = await certRequest('/api/cert/check?role=master');
  const trusted = await certRequest('/api/cert/trust-list');
  return { identity, checked, trusted };
}

// 写操作示例，应由对应按钮触发，不要在页面初始化时自动执行。
async function generateSlave() {
  return certRequest('/api/cert/generate', {
    method: 'POST',
    json: { role: 'slave', name: 'slave-001', days: 365, ip: ['192.168.2.136'], dns: [] }
  });
}

async function renewMaster() {
  return certRequest('/api/cert/renew', {
    method: 'POST',
    json: { role: 'master', name: 'master-001', days: 365, ip: [], dns: [] }
  });
}

async function importMaster(file, fingerprint = '') {
  const form = new FormData();
  form.append('file', file); // 字段名是 file，不是 firmwareFile
  if (fingerprint) form.append('fingerprint', fingerprint);
  return certRequest('/api/cert/trust-add', { method: 'POST', form });
}

async function removeMaster(fingerprint) {
  return certRequest('/api/cert/trust-remove', { method: 'POST', json: { fingerprint } });
}
```

导出需要带 Authorization 的 fetch 获取 Blob；普通 `<a href>` 不会自动附加 sessionStorage 中的 Bearer：

```javascript
async function exportCertificate(role) {
  if (!['master', 'slave'].includes(role)) throw new Error('证书角色错误');
  const response = await fetch(`/api/cert/export?role=${role}`, { headers: certHeaders() });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.message || error.error || `HTTP ${response.status}`);
  }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = `${role}.crt`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
```

前端超时时间应大于后端脚本的 60 秒执行超时，并考虑代理/网络耗时。遇到 `restart_required:true` 时提示需按维护流程重启 `tems`；这不表示后端已经重启。收到 401 时按项目登录流程处理当前标签页会话。

## 6. Postman 配置

1. 请求 `POST {{baseUrl}}/permission/login`，Body 选择 **raw → JSON**，提交有效账号密码。
2. 保存响应的 `session_token` 和 `csrf_token` 到 Postman 环境变量。
3. 证书请求 Authorization 选择 **Bearer Token**，值为 `{{session_token}}`；这里不再额外填写 `Bearer ` 前缀。
4. POST 请求 Headers 添加 `X-CSRF-Token: {{csrf_token}}`。
5. `generate`、`renew`、`trust-remove` 使用 **raw → JSON**；`trust-add` 使用 **form-data**，`file` 行类型选择 **File**，指纹行为 Text，删除手动填写的 Content-Type。
6. GET 请求在 Params 中填写 `role`（仅 identity/check/export），不要把账号密码当作证书接口 Body。
7. `export` 成功后使用文件保存功能，错误时查看 JSON。证书请求的 HTTPS 信任使用网页服务证书，与上传的 Modbus 主机证书是两个用途。

## 7. curl 调试示例

以下命令仅供按需手动选择执行，写操作会修改设备证书，不应整段批量运行。先取得已登录管理员的真实 Token。使用签发/信任设备网页 HTTPS 证书的 CA 文件；`HTTPS_CA` 不是 Modbus 的 `master-ca.crt`。如果系统已经信任该 HTTPS 证书，可省略 `--cacert`。

```bash
BASE_URL='https://192.168.2.136'
HTTPS_CA='/path/to/https-ca.crt'
read -r -s -p 'session_token: ' SESSION_TOKEN
printf '\n'
read -r -s -p 'csrf_token: ' CSRF_TOKEN
printf '\n'

# 查询本机公开身份信息
curl --cacert "$HTTPS_CA" -sS \
  -H "Authorization: Bearer $SESSION_TOKEN" \
  "$BASE_URL/api/cert/identity?role=master"

# 校验本机证书
curl --cacert "$HTTPS_CA" -sS \
  -H "Authorization: Bearer $SESSION_TOKEN" \
  "$BASE_URL/api/cert/check?role=master"

# 查看从机信任的主机证书
curl --cacert "$HTTPS_CA" -sS \
  -H "Authorization: Bearer $SESSION_TOKEN" \
  "$BASE_URL/api/cert/trust-list"

# 首次生成从机证书
curl --cacert "$HTTPS_CA" -sS -X POST \
  -H "Authorization: Bearer $SESSION_TOKEN" -H "X-CSRF-Token: $CSRF_TOKEN" \
  -H 'Content-Type: application/json' \
  --data '{"role":"slave","name":"slave-001","days":365,"ip":["192.168.2.136"],"dns":[]}' \
  "$BASE_URL/api/cert/generate"

# 更新已有主机证书；按实际配置重新填写 IP/DNS
curl --cacert "$HTTPS_CA" -sS -X POST \
  -H "Authorization: Bearer $SESSION_TOKEN" -H "X-CSRF-Token: $CSRF_TOKEN" \
  -H 'Content-Type: application/json' \
  --data '{"role":"master","name":"master-001","days":365,"ip":[],"dns":[]}' \
  "$BASE_URL/api/cert/renew"

# 导入单个主机公开证书；不核对指纹时省略 fingerprint 这一行
FINGERPRINT='替换为真实的完整SHA256证书指纹'
curl --cacert "$HTTPS_CA" -sS -X POST \
  -H "Authorization: Bearer $SESSION_TOKEN" -H "X-CSRF-Token: $CSRF_TOKEN" \
  -F 'file=@./master.crt' \
  -F "fingerprint=$FINGERPRINT" \
  "$BASE_URL/api/cert/trust-add"

# 删除该指纹对应的可信主机证书
curl --cacert "$HTTPS_CA" -sS -X POST \
  -H "Authorization: Bearer $SESSION_TOKEN" -H "X-CSRF-Token: $CSRF_TOKEN" \
  -H 'Content-Type: application/json' \
  --data "{\"fingerprint\":\"$FINGERPRINT\"}" \
  "$BASE_URL/api/cert/trust-remove"

# 导出：HTTP 失败时不把错误 JSON 当证书保存；下载完成后可用 openssl 查看
curl --cacert "$HTTPS_CA" -sS --fail \
  -H "Authorization: Bearer $SESSION_TOKEN" \
  -o ./exported-master.crt "$BASE_URL/api/cert/export?role=master"
```

## 8. 后端调用链与故障定位

### 8.1 路由到脚本的映射

脚本实际由运行 Flask 的 Python 解释器 `sys.executable` 启动：

```text
<服务使用的 Python> /home/zlg/app/scripts/modbus_certs.py --dir /etc/ems/modbus <子命令与参数>
```

| HTTP 操作 | 脚本子命令 | 主要文件/行为 |
| --- | --- | --- |
| identity | `show --role master/slave` | 读取 `<role>.crt`，输出 subject、issuer、日期和指纹 |
| generate | `generate --role ... --name ... --days ... [--ip ...] [--dns ...]` | 调用 TA 身份工具生成公开证书，写 `<role>.crt` |
| renew | `renew` 加同样身份参数 | 备份旧公开证书并生成新证书，复用角色密钥 |
| check | `check --role master/slave` | OpenSSL 校验及 TA 密钥匹配检查 |
| trust-list | `trust-list` | 读取 `master-ca.crt` 并输出每张证书信息 |
| trust-add | `trust-add --cert <临时文件> [--fingerprint ...]` | 校验后追加信任，已有信任文件先备份 |
| trust-remove | `trust-remove --fingerprint ...` | 备份并重写信任文件 |
| export | 先 `check --role ...`，再 Flask `send_file` | HTTP 实现不调用脚本 `export` 子命令 |

脚本单次执行超时 60 秒。公开证书位于 `/etc/ems/modbus/master.crt`、`slave.crt`；备份目录为 `/etc/ems/modbus/backups/`。私钥由 TA 保存，不通过这些接口导出。上传临时目录前缀为 `modbus-cert-`，处理后清理。

HTTP 层会先检查脚本和证书目录是否存在，目录缺失时不会调用脚本自行初始化。设备还需具备 OpenSSL、可执行的 `/home/zlg/app/bin/modbus_tee_identity`（或脚本环境变量 `MODBUS_TEE_IDENTITY` 指定路径）、可用 OP-TEE/TA 和相应运行权限。API 文件仅做接口转发，不能替代这些设备依赖。

### 8.2 HTTP 状态速查

| 状态 | 排查方向 |
| --- | --- |
| 200 | JSON 操作检查 `status:3`；export 应为证书文件 |
| 400 | 非 JSON 对象、缺少参数、角色/名称/IP/DNS/指纹格式错误、缺少上传文件、扩展名或 PEM 前缀不符 |
| 401 | Bearer 缺失、过期、撤销，或账号凭据变化；不是证书参数问题 |
| 403 | 用户管理权限不足，或写请求未通过来源/CSRF 检查；检查响应的 `message`/`error` |
| 404 | export 对应 `.crt` 不存在；其他脚本内“未找到”通常不是 404 |
| 413 | 上传证书大于 1 MiB；反向代理也可能提前返回自身的上传大小错误 |
| 422 | 仅 `/check` 的脚本执行/校验失败映射；进一步查 `[CERT]` 日志 |
| 500 | 脚本/目录缺失、脚本非零退出、超时、已有证书重复生成、导入/删除失败、文件操作失败等 |
| 503 | 全局会话认证存储不可用，尚未进入证书业务逻辑 |

后端 `[CERT]` 日志包含操作类型、返回码和脚本 stderr，HTTP 错误只给通用提示。通过实际监听主服务的进程日志定位，不应只查看另一个未处理请求的 service。独立运行 `route_cert.py` 的 8001 测试入口没有注入管理员身份和正式登录流程，不能用它替代主应用做正常认证调用。

### 8.3 只读设备调试命令

```bash
# 查看设备公开证书，不读取私钥
openssl x509 -in /etc/ems/modbus/master.crt \
  -noout -subject -issuer -dates -fingerprint -sha256

# 以实际服务使用的 Python 调用；这里按现有设备虚拟环境举例
/home/zlg/myenv/bin/python /home/zlg/app/scripts/modbus_certs.py \
  --dir /etc/ems/modbus show --role master

/home/zlg/myenv/bin/python /home/zlg/app/scripts/modbus_certs.py \
  --dir /etc/ems/modbus check --role master

/home/zlg/myenv/bin/python /home/zlg/app/scripts/modbus_certs.py \
  --dir /etc/ems/modbus trust-list
```

这些查询不修改证书内容；脚本仍会使用锁文件，校验过程可能创建并清理临时文件。本文仅整理当前行为，未执行证书生成、更新、信任变更或服务重启，也不表示已完成设备端联调。
