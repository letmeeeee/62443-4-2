# 前端连接与磁盘使用量

## GET /api/system/cpu-usage

需登录，返回例如 `{"usedPercent":25.5,"sampleSeconds":0.2}`。
读取 Linux `/proc/stat` 两次，间隔约 200ms，计算此期间所有 CPU 核心合计的平均忙碌比例，
范围 0–100%，不是单个 Python 进程的使用率。idle 和 iowait 视为空闲，guest 不重复计数。
每次请求约需 200ms，建议前端每 2–5 秒查询一次；采样失败或系统不支持时返回 HTTP 503。

浏览器控制台调用：

```javascript
fetch('/api/system/cpu-usage', { credentials: 'same-origin' })
  .then(async r => {
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    console.log(`CPU 使用率：${data.usedPercent}%`);
  })
  .catch(console.error);
```

## 登录会话名额（当前登录数量统计口径）

所有使用同一会话数据库的服务最多允许 20 个未过期登录会话，与是否使用 Socket.IO 无关。
`POST /permission/login`、`POST /permission/logout` 和 `GET /permission/session`
成功响应包含 `loginSessions: {"limit":20,"active":2,"remaining":18}`。
登录/登出日志中的 `logins` 和 `remaining` 使用该统计；`webConnections` 仍单独表示长连接。
第 21 个独立登录返回 HTTP 429，`code=LOGIN_LIMIT_REACHED`，同时返回 `loginSessions`。
数据库事务串行化登录名额分配，避免并发超限；启动时自动创建 `login_capacity_lock` 表。

独立浏览器/设备的 Cookie 会话各占一名额；同一浏览器标签页共享 Cookie，重新登录替换
当前会话而不多占名额。不同会话即使用同一用户名也分别计数。退出立即释放登录名额；
过期会话不计数。关闭页面或断网无法可靠通知 HTTP 后端，名额会保留至退出或会话过期。
账号/密码变化导致的失效会话在认证检查撤销或到期前仍可能占名额。

主服务（8000 端口）的默认 Socket.IO namespace 最多同时接入 20 个已认证连接。
每个浏览器标签页的连接单独计数；第 21 个连接被拒绝，客户端收到 `connect_error`。
断开连接（包括心跳超时被服务端识别后）释放名额。连接、断连和超限拒绝通过
现有 `DPrint` 记录日志，包含 sid、IP、当前连接数，断连还包含原因。
该计数适用于当前单进程部署；多进程部署需要共享计数存储。
独立升级服务（9000 端口）不在此计数范围内。

退出登录必须调用 `POST /permission/logout`（携带登录 Cookie，跨来源校验按现有
`X-CSRF-Token` 规则执行）。接口打印用户退出日志，并断开当前登录会话关联的主服务
Socket.IO 连接，释放名额。仅清理前端状态、跳转登录页或加载登录页资源不会通知后端，
也不会触发退出日志。没有创建 Socket.IO 连接的 HTTP 客户端不计入上述连接数。

主服务的登录、登出成功响应，以及 `GET /permission/session` 的成功响应，新增：

```json
{"webConnections":{"limit":20,"active":3,"remaining":17}}
```

`webConnections.remaining` 为当前剩余可用的 Socket.IO 连接名额，连接变化日志也包含
`remaining`。前端可通过已有会话查询接口刷新数量。计数为返回时的快照，HTTP 登录
本身不占用连接名额，因此不是剩余可登录账号数，也不代表为调用者预留了名额。

主动退出需要成功调用退出接口；会话到期（默认登录后 1800 秒，可配置）、会话记录
被撤销、账号被删除/禁用或密码凭据变化，会在下次认证检查时导致会话失效。
页面刷新和正常请求不会延长固定会话期限。关闭页面或断网不是主动退出；
Socket.IO 断开/心跳超时只释放连接名额。现有连接不会仅因登录会话到期自动断开。

## GET /api/system/disk-usage

此接口现在一次返回磁盘与 CPU 使用率，保留原磁盘字段，新增 `cpu` 对象。
新增 `display` 对象供前端直接显示，无需换算容量或拼接百分号：

```json
{"display":{"diskTotal":"100.00 GiB","diskUsed":"40.00 GiB","diskFree":"60.00 GiB","diskUsage":"40.00%","cpuUsage":"25.00%"}}
```

容量按 1024³ 字节换算为 GiB，所有显示值保留两位小数。原始数值字段继续保留。
例如：`{"path":"/","total":1000,"used":400,"free":600,"usedPercent":40.0,"cpu":{"usedPercent":25.0,"sampleSeconds":0.2}}`。
顶层 `usedPercent` 为磁盘使用率，`cpu.usedPercent` 为 CPU 使用率。
CPU 采样失败时整个请求返回 503。原 `/api/system/cpu-usage` 保留兼容旧调用。

需要已有登录 Cookie。可选查询参数 `path` 为绝对路径，默认 `/`。
例如 `/api/system/disk-usage?path=/mnt/nvme` 查询 NVMe 挂载路径所在文件系统。
返回的是路径所在文件系统的容量，不是目录中文件的累计大小，也不是所有磁盘之和。

```json
{"path":"/","total":1000000000,"used":400000000,"free":600000000,"usedPercent":40.0,"cpu":{"usedPercent":25.0,"sampleSeconds":0.2}}
```

`total`、`used`、`free` 单位为字节；`usedPercent` 为已用 / 总容量 × 100，保留两位小数。
Linux 的保留块可能导致 `total` 不等于 `used + free`。
路径无效返回 400，不存在返回 404，无权限返回 403，读取失败返回 500。
