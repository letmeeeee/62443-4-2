# 系统监控、TEE 与证书管理接口调用协议

整理日期：2026-10-23。本文依据用户指定的 **`/home/wx/WorkStation/ItemCode/62443-4-2/exec/app/routes`** 下实际源码整理，包含 `route_system.py`、`route_tee.py`、`route_cert.py`，共 **17个路径、17个显式HTTP方法绑定**。

参考仓库HEAD为 `74e5d5e`，认证等文件存在未提交修改，本文以读取时的工作区实现为准。此前临时副本及当前G3-src项目不能代替这份源码；本文只在当前G3-src项目的docs目录输出文档，没有复制接口或修改指定项目。示例值用于说明结构，未调用真实TEE、生成证书、轮换密钥或重启设备。

## 1. 服务入口、认证与响应

### 1.1 入口

这些接口全部由**主服务8000**承载，不走独立9000升级查询服务。线上使用设备实际HTTPS入口，例如 `https://<设备IP>`；开发直连按现场配置使用 `http://<设备IP>:8000`。启用HTTPS部署时主进程可能只监听127.0.0.1，由Nginx转发，不能假设8000可直接从外部访问。

请求URL = 服务根地址 + 本文完整路径；Base URL不额外拼接 `/api`。例如 `https://<设备IP>/api/cert/identity?role=master`。

`route_system.py` 注册在system_bp；TEE与证书模块导入时把路由注册到g3_bp，main.py在注册蓝图前导入了它们，没有额外URL前缀。

### 1.2 当前源码使用Bearer会话凭据

先JSON提交 `POST /permission/login`，取得 `session_token`、`csrf_token` 和 `expires_at`。示例：

```json
{"username":"<用户名>","password":"<密码>"}
```

成功响应中的关键字段：

```json
{"ok":true,"username":"<用户名>","permission":4,"session_token":"<服务器返回的会话凭据>","csrf_token":"<服务器返回的CSRF值>","expires_at":1792744200}
```

上例仅列对接所需字段，expires_at为Unix秒，具体值由服务器返回。后续所有17个接口均携带：

```http
Authorization: Bearer <session_token>
```

**当前utils/auth.py只从Authorization请求头取得HTTP会话凭据，不回退到Cookie，也不从URL读取Token。** 不能以 `credentials:'same-origin'`、本地登录标记或请求体里的operatorName代替认证；该session_token是服务器会话凭据，不据此假定为JWT。

登录后如需恢复CSRF值，可携带Bearer调用 `GET /permission/session`。默认固定会话期1800秒，可配置；普通请求不会自动延长有效期。登录、会话查询仅作为本文接口的前置步骤，不计入17个路径。

POST请求建议统一携带：

```http
X-CSRF-Token: <csrf_token>
```

后端对非GET/HEAD请求先检查同源来源；无法通过同源判断时必须匹配CSRF Token。curl、Postman等通常没有同源信息，应同时发送Bearer与CSRF。Token匹配不等于服务已开放跨域，前端优先同源或使用开发代理。登录有单独的跨源限制。

| 模块 | 身份要求 | 角色要求 |
| --- | --- | --- |
| route_system.py | 有效Bearer会话 | 无额外角色限制 |
| route_tee.py | 有效Bearer会话 | config.PERMISSION_TABLE.usermanage，当前为[4] |
| route_cert.py | 有效Bearer会话 | 同上，当前为[4] |

证书请求中的 `role=master/slave` 是Modbus证书用途，不是用户权限。三个模块均不需要前端提交operatorName。

### 1.3 成功与失败格式

系统监控成功返回原始统计对象，不包含统一status或ok。TEE和证书JSON成功使用：

```json
{"status":3,"message":"<操作说明>","data":{}}
```

错误一般为：

```json
{"status":-1,"message":"<错误原因>"}
```

全局认证/CSRF钩子可能在业务函数执行前返回不同结构：

```json
{"ok":false,"code":"SESSION_INVALID","error":"Authentication required"}
```

前端同时判断HTTP状态和业务结果，提示信息兼容message/error。常见公共错误：401会话缺失或失效；403管理员权限不足或CSRF失败；503认证存储不可用。业务响应禁止缓存。证书导出成功是文件流，需要单独处理。

**密码学verify接口中，HTTP200和status=3只代表校验操作正常完成；校验是否通过以data.valid为准。** valid=false仍然HTTP200。

## 2. 路径与调用方式速查

| 源文件 | 方法 | 完整路径 | 用途 | 请求方式 | 章节 |
| --- | --- | --- | --- | --- | --- |
| route_system.py | GET | `/api/system/cpu-usage` | CPU使用率 | 无 | 3.1 |
| route_system.py | GET | `/api/system/disk-usage` | 磁盘及CPU使用率 | Query：path可选 | 3.2 |
| route_tee.py | POST | `/api/cert/tee/keys` | 确保TEE密钥存在 | JSON：type可选 | 4.1 |
| route_tee.py | POST | `/api/cert/tee/rotate-rsa` | 轮换TEE RSA密钥 | JSON：confirm | 4.2 |
| route_tee.py | GET | `/api/cert/tee/public-key` | 读取TEE RSA公钥 | 无 | 4.3 |
| route_tee.py | POST | `/api/cert/tee/cmac` | 计算CMAC | JSON：message | 4.4 |
| route_tee.py | POST | `/api/cert/tee/sign` | RSA-PSS签名 | JSON：message | 4.5 |
| route_tee.py | POST | `/api/cert/tee/verify-cmac` | 验证CMAC | JSON：message/mac | 4.6 |
| route_tee.py | POST | `/api/cert/tee/verify-signature` | 验证RSA签名 | JSON：message/signature | 4.7 |
| route_cert.py | GET | `/api/cert/identity` | 查询本机证书信息 | Query：role | 5.2 |
| route_cert.py | POST | `/api/cert/generate` | 首次生成本机证书 | JSON | 5.3 |
| route_cert.py | POST | `/api/cert/renew` | 更新本机证书 | JSON | 5.4 |
| route_cert.py | GET | `/api/cert/check` | 检查证书与对应密钥 | Query：role | 5.5 |
| route_cert.py | GET | `/api/cert/trust-list` | 查询可信主机证书 | 无 | 5.6 |
| route_cert.py | POST | `/api/cert/trust-add` | 导入可信主机证书 | multipart：file/fingerprint | 5.7 |
| route_cert.py | POST | `/api/cert/trust-remove` | 按指纹删除信任证书 | JSON：fingerprint | 5.8 |
| route_cert.py | GET | `/api/cert/export` | 导出本机公开证书 | Query：role；返回文件 | 5.9 |

## 3. route_system.py：系统监控

### 3.1 GET `/api/system/cpu-usage`

无Query或请求体。需登录，无额外管理员限制。

```http
GET /api/system/cpu-usage
Authorization: Bearer <session_token>
```

200示例：

```json
{"usedPercent":25.5,"sampleSeconds":0.201}
```

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| usedPercent | number | 全部CPU核心总体忙碌比例，0–100，保留两位小数 |
| sampleSeconds | number | 实际采样间隔秒数，约0.2，保留三位小数 |

后端读取两次Linux `/proc/stat`，间隔约200ms；不是Flask进程自己的CPU使用率。idle和iowait视为空闲，guest不重复计数。每次请求有采样等待，前端建议2–5秒轮询一次（建议值，不是后端限流）。

采样读取失败或计数异常返回503：`{"ok":false,"error":"CPU usage unavailable"}`。

### 3.2 GET `/api/system/disk-usage`

可选Query：`path:string`，默认 `/`，必须为非空绝对路径，不得包含NUL字符。需要查询NVMe时传 `/mnt/nvme` 等现场真实路径。

```http
GET /api/system/disk-usage?path=/mnt/nvme
Authorization: Bearer <session_token>
```

200示例：

```json
{
  "path":"/mnt/nvme",
  "total":107374182400,
  "used":42949672960,
  "free":64424509440,
  "usedPercent":40.0,
  "cpu":{"usedPercent":25.5,"sampleSeconds":0.201},
  "display":{
    "diskTotal":"100.00 GiB",
    "diskUsed":"40.00 GiB",
    "diskFree":"60.00 GiB",
    "diskUsage":"40.00%",
    "cpuUsage":"25.50%"
  }
}
```

| 字段 | 含义 |
| --- | --- |
| path | 回显查询路径 |
| total/used/free | 该路径所在文件系统总量、已用、可用量；整数，单位字节 |
| usedPercent | 磁盘使用率，used/total×100，两位小数 |
| cpu | 与CPU专用接口相同的统计对象 |
| display | 可直接显示的字符串；容量按1024³换算为GiB，均两位小数 |

返回文件系统容量，不是目录文件大小合计，也不是所有磁盘总量。Linux保留块可能使total不等于used+free。界面若同时展示磁盘和CPU，可只轮询此接口，避免再独立请求CPU。

| HTTP | 情况 | error |
| --- | --- | --- |
| 400 | 空路径、非绝对路径或包含NUL | path must be an absolute path |
| 404 | 路径不存在或中间不是目录 | Path does not exist |
| 403 | 路径权限不足 | Permission denied |
| 500 | 磁盘读取失败 | Disk usage unavailable |
| 503 | CPU采样失败 | CPU usage unavailable |

错误统一包含ok=false。CPU失败会使整个接口返回503，不会返回仅含磁盘的部分成功对象。

## 4. route_tee.py：TEE密钥与密码学操作

全部接口要求管理员权限4。底层调用设备上的 `crypto_ta_client`，默认路径 `/home/zlg/app/bin/crypto_ta_client`，可通过 `CRYPTO_TA_CLIENT` 环境变量指定；**每次客户端调用超时15秒**。密钥生成type=all会依次调用两个操作，不是整个HTTP请求总计15秒。

请求message、mac、signature及响应密码学字节均使用**标准Base64**，不是十六进制，也不是Base64URL。message为原始消息字节的Base64，不要先将消息SHA-256摘要传入sign。每个message解码后最多1,048,576字节；空消息字符串可解码为0字节，接口允许。前端必须先将中文文本编码为UTF-8字节再转Base64。

参数错误返回400；客户端未安装、调用失败/超时、输出不符合预期等返回503。底层错误不会把完整stderr返回前端。

### 4.1 POST `/api/cert/tee/keys`

JSON对象必传，可传空对象 `{}`；type可选，默认all，去空白后转小写，支持aes/rsa/all。

```http
POST /api/cert/tee/keys
Authorization: Bearer <session_token>
X-CSRF-Token: <csrf_token>
Content-Type: application/json

{"type":"all"}
```

200：

```json
{"status":3,"message":"TEE key is ready","data":{"type":"all","created_or_reused":true,"rotated":false}}
```

确保持久密钥存在；已有密钥复用，不会自动轮换，不返回私钥。created_or_reused不能用于区分“此次新建”还是“复用已有密钥”。不传JSON或type非法返回400。all为顺序调用，后一步失败不保证前一步已产生的密钥被撤销。

### 4.2 POST `/api/cert/tee/rotate-rsa`

必填JSON：`confirm:string`，必须严格等于 `ROTATE_RSA_KEY`，大小写不可改。

```json
{"confirm":"ROTATE_RSA_KEY"}
```

200：

```json
{"status":3,"message":"TEE RSA key rotated","data":{"type":"rsa","rotated":true,"certificate_renewal_required":true,"restart_required":true}}
```

这是明确的密钥轮换操作，应由界面的用户确认动作触发，不作为普通页面初始化或ensure-key步骤。成功标志表示需要后续证书维护和服务重启，不代表接口已经自动完成换证、重配信任和重启。具体证书role及设备维护顺序由实际部署确定，不能只凭此响应推定。

confirm缺失或不匹配400；TEE执行失败503。

### 4.3 GET `/api/cert/tee/public-key`

无参数，200：

```json
{"status":3,"message":"TEE RSA public key retrieved","data":{"algorithm":"RSA-3072","format":"unsigned-big-endian","modulus":"<Base64编码的384字节n>","exponent":"AQAB"}}
```

modulus/exponent分别为RSA公钥n/e，**无符号大端字节的Base64**；modulus解码后384字节，exponent保持实际长度且必须非空。AQAB只是常见指数65537的示例，不应硬编码。返回值不是PEM公钥、JWK或X.509证书，前端如需其他格式需自行转换。无密钥或客户端输出异常可能503。

### 4.4 POST `/api/cert/tee/cmac`

JSON必填：`message:string`，Base64。示例中aGVsbG8=表示UTF-8文本hello。

```json
{"message":"aGVsbG8="}
```

200：

```json
{"status":3,"message":"TEE operation completed","data":{"algorithm":"AES-128-CMAC","mac":"<Base64编码的16字节CMAC>"}}
```

mac解码后固定16字节。400参数错误；503TEE不可用或结果长度异常。

### 4.5 POST `/api/cert/tee/sign`

JSON必填message，示例：`{"message":"aGVsbG8="}`。发送原始消息，不预先计算摘要。

200：

```json
{"status":3,"message":"TEE operation completed","data":{"algorithm":"RSA-3072-PSS-SHA256","signature":"<Base64编码的384字节签名>"}}
```

signature解码后固定384字节。400参数错误；503TEE或输出异常。

### 4.6 POST `/api/cert/tee/verify-cmac`

JSON必填message和mac；message与生成mac时的原始字节必须完全一致，mac为Base64编码且解码后恰为16字节。

```json
{"message":"aGVsbG8=","mac":"<cmac接口返回的mac>"}
```

200示例：

```json
{"status":3,"message":"TEE verification completed","data":{"algorithm":"AES-128-CMAC","valid":true}}
```

不匹配时同样200/status=3，但data.valid=false；参数格式或长度错400，TEE调用失败503。

### 4.7 POST `/api/cert/tee/verify-signature`

JSON必填message和signature；signature取sign返回的Base64字符串，解码后恰为384字节。

```json
{"message":"aGVsbG8=","signature":"<sign接口返回的signature>"}
```

200：

```json
{"status":3,"message":"TEE verification completed","data":{"algorithm":"RSA-3072-PSS-SHA256","valid":false}}
```

valid=true/false表示签名通过/不通过，false不是HTTP错误。不接收另一个待验证的公钥参数，使用设备TEE所管理的对应密钥。参数错误400，TEE执行/结果异常503。

## 5. route_cert.py：Modbus TLS证书管理

这些接口管理Modbus TLS身份证书、从机的可信主机证书，**不是Nginx用于网页HTTPS的证书**。所有接口含GET查询及导出均要求管理员权限4。

运行时调用 `/home/zlg/app/scripts/modbus_certs.py`，证书目录 `/etc/ems/modbus`，单次脚本超时60秒。指定仓库中的脚本源码位于 `logger/scripts/modbus_certs.py`；部署需保证API硬编码的运行路径和证书目录实际存在。这里只整理接口，没有执行部署。

### 5.1 公共证书参数

| 参数 | 规则 |
| --- | --- |
| role | 必填master/slave，去首尾空白并转小写；没有默认值 |
| name | 生成/更新必填；1–64字符，首字符字母或数字，其余字母数字及 `_ . -` |
| days | 生成/更新可选，默认365，范围1–3650；前端发送JSON整数，布尔值被拒绝 |
| ip | 可选，单个字符串或字符串数组，每项合法IPv4/IPv6；省略/null视为空列表 |
| dns | 可选，单个字符串或字符串数组；合法DNS标签，总长度最多253；省略/null为空列表 |
| fingerprint | SHA-256完整证书指纹，64位十六进制或32组冒号分隔字节；大小写均可，后端转无冒号大写 |

master表示本机作为Modbus主机，证书用于TLS clientAuth；slave表示本机作为Modbus从机，证书用于TLS serverAuth。name是CN，不是管理员用户名。

ip/dns字符串不会按逗号拆分，多项请传数组；空字符串不是空列表。DNS不支持通配符、尾随点或直接中文域名。days底层会int转换部分输入，前端不要依赖字符串或小数截断。

下列JSON中的output/certificate是脚本文本，界面应使用普通文本或pre显示，不能假设为结构化字段，更不能作为HTML渲染。除export成功外，均用status/message/data封装。

### 5.2 GET `/api/cert/identity`

必填Query：role。

```http
GET /api/cert/identity?role=master
Authorization: Bearer <session_token>
```

200：

```json
{"status":3,"message":"certificate information retrieved","data":{"role":"master","certificate":"subject=CN=master-001\nissuer=CN=master-001\nnotBefore=...\nnotAfter=...\nSHA256: ..."}}
```

certificate是证书信息文本，**不是PEM证书文件**。角色错误400；脚本、目录或证书读取失败500，message=`failed to retrieve certificate information`。查询信息不等于已执行check。

### 5.3 POST `/api/cert/generate`

JSON请求：

```json
{"role":"slave","name":"slave-001","days":365,"ip":["192.168.2.136"],"dns":["device.example.local"]}
```

200：

```json
{"status":3,"message":"certificate generated successfully","data":{"role":"slave","name":"slave-001","days":365,"output":"<脚本输出>","restart_required":true}}
```

generate用于首次生成，不覆盖已有角色证书；已有证书应使用renew。私钥由设备TA管理，不经HTTP返回。参数错400；已有文件、脚本或生成失败等返回500，message=`certificate generation failed`，不是409。

restart_required=true表示需另行在维护流程重启相关服务；本接口不自动重启tems，也不代表整个设备必须重启。

### 5.4 POST `/api/cert/renew`

JSON字段与generate相同，示例：

```json
{"role":"master","name":"master-001","days":365,"ip":["192.168.2.136"],"dns":[]}
```

200：

```json
{"status":3,"message":"certificate renewed successfully","data":{"role":"master","name":"master-001","days":365,"output":"<包含备份信息的脚本输出>","restart_required":true}}
```

要求已有角色证书，更新前备份旧公开证书，复用对应角色的TA密钥；不是TEE RSA轮换接口。IP/DNS SAN需要重新传入，不会自动继承旧值。按当前路由说明，应在维护流程已停止相关tems进程后调用；接口本身不停止或重启服务。

参数错400；无旧证书、脚本或更新失败500，message=`certificate renewal failed`。更换master证书后，需要将新的公开证书导入相应从机的信任列表。

### 5.5 GET `/api/cert/check`

必填Query role，例：`GET /api/cert/check?role=slave`。

200：

```json
{"status":3,"message":"certificate check passed","data":{"role":"slave","valid":true,"output":"<校验输出>"}}
```

底层脚本执行证书格式、自签名、有效期、用途及对应TA密钥匹配等检查。role错误400；脚本返回失败时HTTP422：

```json
{"status":-1,"message":"certificate check failed","data":{"role":"slave","valid":false}}
```

这里的脚本失败也可能是脚本不存在/执行超时等运行问题，不能仅凭422就推断证书一定过期。与TEE verify不同，此处valid=false配HTTP422及status=-1。

### 5.6 GET `/api/cert/trust-list`

无参数。读取从机信任的主机公开证书集合，底层文件为 `/etc/ems/modbus/master-ca.crt`。

200：

```json
{"status":3,"message":"trusted certificates retrieved","data":{"output":"可信主机证书数量: 1\nsubject=CN=master-001\nissuer=CN=master-001\nnotBefore=...\nnotAfter=...\nSHA256: ..."}}
```

**当前返回文本output，不是证书对象数组**，也不包含可直接用于前端列表的单独fingerprint字段。若做结构化列表，需按脚本实际文本解析，或后续另行扩展接口；不要默认data是数组。失败500，message=`failed to retrieve trusted certificates`。

### 5.7 POST `/api/cert/trust-add`

使用multipart/form-data：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| file | 是 | PEM编码的公开证书，文件名后缀必须.crt，大小不超过1,048,576字节 |
| fingerprint | 否 | 预期的完整SHA-256证书指纹，导入时进行一致性校验 |

```http
POST /api/cert/trust-add
Authorization: Bearer <session_token>
X-CSRF-Token: <csrf_token>
Content-Type: multipart/form-data; boundary=<浏览器自动生成>

file = <master.crt文件>
fingerprint = <可选的完整证书指纹>
```

file不是firmwareFile。即使内容是PEM，.pem文件名也不能通过当前扩展名检查；可导出的.crt采用PEM编码。仅允许公开证书，非空内容去前导空白后需以 `-----BEGIN CERTIFICATE-----` 开头；脚本进一步校验证书真实性、有效期、角色等，每次导入一个主机证书。

200：

```json
{"status":3,"message":"trusted certificate imported successfully","data":{"output":"<导入或已存在提示>","restart_required":true}}
```

重复指纹不会重复添加，可能成功返回“已存在”。参数、扩展名、空文件或PEM头错误400；超1MiB返回413；指纹不匹配、证书不合法、脚本或文件操作失败通常500。指纹不匹配时脚本不修改信任文件。

### 5.8 POST `/api/cert/trust-remove`

JSON必填fingerprint，只按完整证书指纹删除，不接受设备名或文件名。

```json
{"fingerprint":"00112233445566778899AABBCCDDEEFF00112233445566778899AABBCCDDEEFF"}
```

200：

```json
{"status":3,"message":"trusted certificate removed successfully","data":{"fingerprint":"00112233445566778899AABBCCDDEEFF00112233445566778899AABBCCDDEEFF","output":"<删除输出>","restart_required":true}}
```

格式错误400；未找到指纹、脚本失败500，不是404。删除最后一个信任证书会使当前TLS实现重启后无法启动从机监听，应先安排替代证书的导入。

### 5.9 GET `/api/cert/export`

必填Query role，例：

```http
GET /api/cert/export?role=master
Authorization: Bearer <session_token>
```

成功200为文件流：

```http
Content-Type: application/x-pem-file
Content-Disposition: attachment; filename=master.crt
Cache-Control: no-store
```

role=slave下载slave.crt。只导出本机公开证书，不提供私钥或任意路径下载。下载前会执行check，因此证书存在但不通过检查也无法下载。不要使用response.json()解析成功响应。

role非法400；公开证书文件不存在404；校验失败、脚本错误或文件读取失败500。失败返回JSON，前端先看HTTP状态再决定json/blob。

## 6. 推荐页面交互顺序

| 页面或操作 | 调用顺序 |
| --- | --- |
| 系统监控 | 登录 → disk-usage → 2–5秒刷新；已含cpu则不必同时请求cpu-usage |
| 密钥确保存在 | 管理员登录 → tee/keys；不要误调用rotate-rsa |
| 签名验证联调 | tee/sign(message) → tee/verify-signature(同message,返回signature) → 检查valid |
| CMAC联调 | tee/cmac(message) → tee/verify-cmac(同message,返回mac) → 检查valid |
| 本机证书页 | identity(role) → check(role)；下载使用export(role) |
| 首次生成证书 | generate → check → export；按维护流程安排服务重启 |
| 换证 | 停止相关tems的维护步骤 → renew → check → export → 更新对端信任 → 按维护流程恢复服务 |
| 从机信任维护 | trust-list → trust-add/trust-remove → 刷新trust-list；安排重启生效 |
| RSA轮换 | 用户明确确认 → rotate-rsa → 按返回标志完成相应换证与服务重启；不自动重试该操作 |

本文三个文件没有提供通用tems停止/重启接口。不要把restart_required误解为已经重启，也不要直接用整机reboot替代维护步骤。

## 7. 前端请求封装示例

示例采用同源相对URL。登录和三个模块调用都经过同一个请求封装；所有写操作只定义函数，不自动执行。session_token可按页面会话放在sessionStorage，避免仅依赖浏览器共享Cookie。

```javascript
let sessionToken = sessionStorage.getItem('session_token') || '';
let csrfToken = sessionStorage.getItem('csrf_token') || '';

async function request(path, {query, json, form, download = false, ...options} = {}) {
  const url = new URL(path, window.location.origin);
  for (const [key, value] of Object.entries(query || {})) {
    if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
  }
  const headers = new Headers(options.headers);
  if (sessionToken) headers.set('Authorization', `Bearer ${sessionToken}`);
  const method = options.method || 'GET';
  if (method !== 'GET' && method !== 'HEAD' && csrfToken) {
    headers.set('X-CSRF-Token', csrfToken);
  }
  let body;
  if (json !== undefined) {
    headers.set('Content-Type', 'application/json');
    body = JSON.stringify(json);
  } else if (form) {
    body = form; // 不手工设置multipart Content-Type
  }
  const response = await fetch(url, {...options, method, headers, body});
  if (response.ok && download) return response.blob();
  let data;
  try { data = await response.json(); }
  catch { throw new Error(`接口未返回JSON (${response.status})`); }
  if (!response.ok || data.status === -1 || data.ok === false) {
    const error = new Error(data.message || data.error || `HTTP ${response.status}`);
    error.httpStatus = response.status;
    error.body = data; // 保留证书check的422/valid=false等信息
    throw error;
  }
  return data;
}

const get = (path, query) => request(path, {query});
const post = (path, json) => request(path, {method: 'POST', json});

export const api = {
  login: async (username, password) => {
    const result = await post('/permission/login', {username, password});
    sessionToken = result.session_token;
    csrfToken = result.csrf_token;
    sessionStorage.setItem('session_token', sessionToken);
    sessionStorage.setItem('csrf_token', csrfToken);
    return result;
  },
  cpu: () => get('/api/system/cpu-usage'),
  disk: path => get('/api/system/disk-usage', {path}),
  ensureKeys: (type = 'all') => post('/api/cert/tee/keys', {type}),
  rotateRsa: confirm => post('/api/cert/tee/rotate-rsa', {confirm}),
  publicKey: () => get('/api/cert/tee/public-key'),
  cmac: message => post('/api/cert/tee/cmac', {message}),
  sign: message => post('/api/cert/tee/sign', {message}),
  verifyCmac: (message, mac) => post('/api/cert/tee/verify-cmac', {message, mac}),
  verifySignature: (message, signature) => post('/api/cert/tee/verify-signature', {message, signature}),
  identity: role => get('/api/cert/identity', {role}),
  generate: data => post('/api/cert/generate', data),
  renew: data => post('/api/cert/renew', data),
  check: role => get('/api/cert/check', {role}),
  trustList: () => get('/api/cert/trust-list'),
  trustAdd: (file, fingerprint) => {
    const form = new FormData();
    form.append('file', file);
    if (fingerprint) form.append('fingerprint', fingerprint);
    return request('/api/cert/trust-add', {method: 'POST', form});
  },
  trustRemove: fingerprint => post('/api/cert/trust-remove', {fingerprint}),
  exportCertificate: role => request('/api/cert/export', {query: {role}, download: true})
};

// 任意UTF-8文本转标准Base64；不要直接对中文字符串调用btoa。
function textToBase64(text) {
  const bytes = new TextEncoder().encode(text);
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

async function verifyText(text) {
  const message = textToBase64(text);
  const signed = await api.sign(message);
  const checked = await api.verifySignature(message, signed.data.signature);
  return checked.data.valid; // false为密码学不匹配，不是网络请求失败
}

async function downloadCertificate(role) {
  const blob = await api.exportCertificate(role);
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `${role}.crt`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
```

curl/Postman同样发送Authorization；JSON POST同时发送Content-Type和X-CSRF-Token，上传使用form-data，导出保存为文件。例如（凭据用实际响应替换，不是字面值）：

```bash
curl 'https://<设备IP>/api/system/disk-usage?path=/mnt/nvme'   -H 'Authorization: Bearer <session_token>'

curl 'https://<设备IP>/api/cert/tee/sign'   -H 'Authorization: Bearer <session_token>'   -H 'X-CSRF-Token: <csrf_token>'   -H 'Content-Type: application/json'   --data '{"message":"aGVsbG8="}'

curl 'https://<设备IP>/api/cert/trust-add'   -H 'Authorization: Bearer <session_token>'   -H 'X-CSRF-Token: <csrf_token>'   -F 'file=@master.crt'
```

## 8. 源码与核对范围

- [route_system.py](</home/wx/WorkStation/ItemCode/62443-4-2/exec/app/routes/route_system.py>): 本文接口来源。
- [route_tee.py](</home/wx/WorkStation/ItemCode/62443-4-2/exec/app/routes/route_tee.py>): 本文接口来源。
- [route_cert.py](</home/wx/WorkStation/ItemCode/62443-4-2/exec/app/routes/route_cert.py>): 本文接口来源。
- [服务注册](</home/wx/WorkStation/ItemCode/62443-4-2/exec/app/main.py>).
- [当前Bearer/CSRF认证](</home/wx/WorkStation/ItemCode/62443-4-2/exec/app/utils/auth.py>).
- [登录及会话响应](</home/wx/WorkStation/ItemCode/62443-4-2/exec/app/routes/route_permission.py>).
- [CPU采样](</home/wx/WorkStation/ItemCode/62443-4-2/exec/app/utils/system_usage.py>).
- [角色与状态常量](</home/wx/WorkStation/ItemCode/62443-4-2/exec/app/config.py>).
- [证书脚本源码](</home/wx/WorkStation/ItemCode/62443-4-2/logger/scripts/modbus_certs.py>): 证书和信任文件的实际处理逻辑。

已静态核对17个路由及参数/响应、认证钩子和脚本输出；示例为协议展示，未运行设备侧密码学或证书操作。此文档不覆盖该仓库其他业务接口，也不将历史技能说明或旧文档中的Cookie示例作为当前认证依据。
