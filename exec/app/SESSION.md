# Session 登录与接口校验

## 实现与范围

主应用 `main.py` 使用显式 Bearer 凭据识别会话，服务端继续使用现有 MySQL `login_sessions` 表。每个标签页把凭据保存在自己的 `sessionStorage`，请求时显式发送；后端不再读取 `lc_session` Cookie，也不接受 URL 参数中的凭据。不是 JWT，不新增 Redis 或用户表字段。

- `POST /permission/login` 验证成功后返回 `session_token`、`csrf_token`、`expires_at`（Unix 秒），并保留原有用户名、权限、密码到期等响应字段。不会设置登录 Cookie。
- 登录时携带旧 `Authorization`，只轮换该凭据对应的会话；不携带则创建独立会话。密码错误或达到上限拒绝登录，不撤销原会话。
- `GET /permission/session` 必须携带 Bearer，返回用户名、最新权限和该会话的 `csrf_token`，供刷新页面恢复身份。
- `POST /permission/logout` 必须携带 Bearer，只撤销该会话；复制的同一 Token 也立即失效。其他标签页使用不同 Token 时不受影响。
- 主应用除登录、前端页面、静态资源外的已注册接口均校验会话；新注册接口默认受保护。OPTIONS 只返回预检响应，不执行业务。
- 未登录、过期、撤销返回 HTTP 401 / `SESSION_INVALID`；认证存储故障返回 503，不放行业务。
- 默认固定有效期 1800 秒，不随访问自动续期；最多 20 个有效登录会话，达到上限返回 429 / `LOGIN_LIMIT_REACHED`，不顶替其他会话。携带旧凭据重新登录可替换自己的名额。
- 每次请求检查账号是否存在、密码凭据是否变化，并读取最新权限。删除、改名、改密后旧会话失效。
- 操作人仍来自 `g.current_user["username"]`；前端的 `operatorName` 不作为操作人依据，业务中的目标 `username` 含义不变。
- 主应用 Socket.IO 使用连接握手的 `auth.session_token` 认证，不使用 Cookie。重新登录、退出时断开当前进程中绑定旧 Token 的连接，其他会话连接保留。

这是身份认证层，各接口的角色授权仍由业务代码负责。独立 `upgrade/upgrade.py`（9000）继续使用相同数据库和认证逻辑，HTTP 查询携带 Bearer，Socket.IO 携带 `auth.session_token`。已有 Socket.IO 仅在连接时验证身份；9000 的连接和其他工作进程中的连接不会被主应用本进程的断开回调立即清理。当前没有 Socket.IO 业务操作事件；将来增加时需逐事件验证，不能仅依赖握手。

## 启动配置

后端 `main.py` 和 `upgrade/upgrade.py` 均在 `init_auth(app)` 前自动调用 `script/session_config.py` 中的 `configure_session(app)`，无需手动 export 即可启动。脚本通过 Python 函数将配置写入 Flask，不依赖子进程修改父进程环境变量。

首次启动自动生成 `exec/instance/session_config.json`：

- `FLASK_SECRET_KEY`：自动生成 64 字符随机密钥，保存后每次重启复用。
- `SESSION_COOKIE_SECURE`：保留兼容配置，默认 `true`；当前用于确定来源校验的预期 HTTPS 协议，不再传输登录 Cookie。
- `AUTH_SESSION_SECONDS`：默认 `1800`，即 30 分钟。

要调整配置，直接编辑生成的 JSON 文件并重启后端。例如将 `AUTH_SESSION_SECONDS` 改为 `3600`；HTTP 本地调试将 `SESSION_COOKIE_SECURE` 改为 `false`。保留原有密钥值；现有配置格式继续兼容。修改脚本中的默认值只影响尚未生成配置文件的首次启动。

也可提前运行初始化脚本（不会输出密钥）：

```bash
python3 exec/app/script/session_config.py
```

配置文件以 0600 权限保存，默认目录首次创建权限为 0700。多个启动进程通过文件锁和原子写入共享同一密钥。服务运行用户需要配置目录的读写权限。文件损坏或配置非法时停止启动，不会自动重新生成密钥。

若应用升级会替换代码目录，使用环境变量 `SESSION_CONFIG_FILE` 指定升级不会覆盖的持久化文件路径。多个实例必须共享相同密钥、MySQL 数据库并保持时钟同步。原有 `FLASK_SECRET_KEY`、`SESSION_COOKIE_SECURE`（0/1）、`AUTH_SESSION_SECONDS` 环境变量仍可覆盖文件配置；首次创建时覆盖值写入文件，已有文件不被环境覆盖值改写。systemd 环境应在服务配置中设置，终端 export 不会影响已运行的服务。

应用启动时通过 `CREATE TABLE IF NOT EXISTS` 初始化 `login_sessions`（InnoDB、utf8mb4）。数据库连接复用现有 INI 配置，不再读取 `AUTH_SESSION_DB`，也不创建本地 SQLite 文件。数据库账号需要会话表的 SELECT、INSERT、DELETE 权限，以及 `login_capacity_lock` 表的 SELECT、INSERT、UPDATE 权限和启动建表所需 CREATE 权限。容量锁使用 InnoDB 单行锁串行检查登录上限。表结构如下。数据库不可用或建表失败时拒绝启动；运行中会话校验失败返回 503。

```sql
CREATE TABLE IF NOT EXISTS login_sessions (
    sid VARCHAR(64) NOT NULL PRIMARY KEY,
    username VARCHAR(64) NOT NULL,
    credential VARCHAR(64) NOT NULL,
    expires_at DOUBLE NOT NULL,
    csrf_token VARCHAR(64) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

`sid` 保存随机会话 ID 的 SHA-256 摘要，`credential` 保存用于检测密码变化的凭据摘要，`expires_at` 为 Unix 时间戳（秒）。会话写入和删除使用数据库事务。MySQL 数据保留时，服务重启后未过期的 Bearer 会话仍有效；过期记录在新登录时清理。

现有会话表结构无需迁移。此次从 Cookie 认证切换到 Bearer 后，旧 Cookie 不再被接受，用户需通过新版前端重新登录。主服务与 9000 服务应同时更新并重启；旧前端仅携带 Cookie 的请求将返回 401，必须与前端协同发布。不要单独部署后端后期待旧页面继续工作。

凭据应通过 HTTPS 传输。现有 `FLASK_SECRET_KEY`、Cookie 配置项继续由配置模块加载，避免破坏部署配置；Bearer 认证不依赖签名 Cookie。HTTP 本地调试仍可将 `SESSION_COOKIE_SECURE` 设为 `false`，使登录来源检查匹配 HTTP。不要信任任意 X-Forwarded-* 请求头。

## 前端对接

所有认证状态（Token、CSRF、用户名、权限）均应使用当前标签页的 `sessionStorage` 或内存，不使用共享 Cookie、`localStorage` 或跨标签页广播来覆盖其他页的身份。刷新时从本页取 Token，调用 `/permission/session`，以返回身份更新界面。新标签页没有凭据时进入登录页。

浏览器“复制标签页”或带 `opener` 打开页面可能复制初始 `sessionStorage`；若要求新页面始终独立登录，应使用 `noopener` 打开新页面，并处理复制标签页的初始化，不能把 `sessionStorage` 当成强制的一页一凭据机制。后端区分显式凭据，不能区分两个页面故意或被复制后使用同一个 Token 的情况。

HTTP 请求格式：

```http
Authorization: Bearer <session_token>
X-CSRF-Token: <csrf_token>
```

GET/HEAD 只需 Authorization。修改类请求保留已有 CSRF 规则：同源 Origin/Referer 或 `Sec-Fetch-Site: same-origin` 可以通过；无同源信息时需匹配当前会话的 `X-CSRF-Token`。建议统一为写请求发送 CSRF。CSRF Token 不能替代 Bearer 身份凭据；缺少 Bearer，即使有合法 Cookie、同源来源和 CSRF 也返回 401。跨域前端未开放。

以下示例用于对接，不是本仓库已完成的页面修改：

```javascript
const key = 'ems.tabSession';
const readSession = () => JSON.parse(sessionStorage.getItem(key) || 'null');
function authHeaders(session = readSession()) {
  return session ? {
    Authorization: `Bearer ${session.session_token}`,
    'X-CSRF-Token': session.csrf_token
  } : {};
}

// 同页切换账号时携带本页旧凭据；全新标签页没有凭据，不撤销其他页。
async function login(username, password) {
  const response = await fetch('/permission/login', {
    method: 'POST',
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password })
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error);
  sessionStorage.setItem(key, JSON.stringify(result));
  return result;
}

const currentResponse = await fetch('/permission/session', { headers: authHeaders() });
if (!currentResponse.ok) throw new Error('需要重新登录');
const current = await currentResponse.json(); // 用后端返回值更新界面身份与权限

async function logout() {
  const active = readSession();
  const response = await fetch('/permission/logout', {
    method: 'POST', headers: authHeaders(active)
  });
  if (response.ok || response.status === 401) {
    // 避免旧请求返回时清除刚刚建立的新会话。
    if (readSession()?.session_token === active?.session_token) {
      sessionStorage.removeItem(key);
    }
  } else {
    throw new Error('退出失败，请重试');
  }
}
```

通用请求封装也应处理 401：只清理发出该请求时的本页凭据，并返回登录页；不要清除其他标签页状态。切换账号时取消旧请求或忽略旧响应，更新界面身份、权限并重新连接 Socket.IO。不要将凭据拼进 URL、日志或下载链接；下载接口使用带 Authorization 的 fetch 获取 Blob。文件上传同样加 Authorization，由浏览器生成 multipart boundary。

Socket.IO 使用动态握手参数，重连时读取本页最新 Token：

```javascript
const socket = io({
  autoConnect: false,
  auth: callback => callback({ session_token: readSession()?.session_token || '' })
});
// 登录成功后，以及切换账号后：
socket.disconnect();
socket.connect();
// 本页退出时主动断开 socket。
```

不把 Token 放到 Socket.IO 的 query 参数，也不依赖浏览器 WebSocket 自动发送 Authorization 头。命令行或自动化脚本同样从登录 JSON 获取 Token，后续显式设置 Authorization；无需保存 Cookie。升级脚本当前直接写本地 JSON 的状态上报行为不变。

## 管理员强制下线指定会话

两个接口均要求管理员本人的 Bearer 凭据，并按 `config.PERMISSION_TABLE["usermanage"]` 授权，当前配置仅允许权限等级 4。

### GET /permission/sessions

返回数据库中现存的会话记录（包含尚未清理的过期记录），例如：

```json
{
  "ok": true,
  "sessions": [
    {
      "session_id": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "username": "alice",
      "expires_at": 1790000000,
      "expired": false,
      "current": false
    }
  ]
}
```

`session_id` 是 `login_sessions.sid` 中保存的 SHA-256 摘要，是管理用标识，不是登录返回的 `session_token`，不能用于 Bearer 登录。列表不返回原始 Token、CSRF 或密码凭据。`current` 标记管理员本次请求使用的会话；列表中的未过期记录也不等于在线标签页数量。

### POST /permission/sessions/revoke

请求头：

```http
Authorization: Bearer <管理员自己的 session_token>
Content-Type: application/json
X-CSRF-Token: <管理员自己的 csrf_token>
```

请求体使用列表取得的标识，或数据库中 `sid` 列的原值：

```json
{"session_id": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"}
```

成功返回 HTTP 200：

```json
{"ok": true, "session_id": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef", "username": "alice"}
```

数据库事务提交并删除该行后才返回成功；只删除指定会话，不批量删除同账号的其他会话，也不删除用户。后续使用该 Token 请求主服务或 9000 查询服务均返回 401，释放对应登录名额；已通过认证正在执行的请求不会被追溯取消。管理员也可以撤销自己的当前会话，之后需重新登录。

同时尝试断开主应用当前进程中绑定该会话的 Socket.IO 连接；跨进程或独立 9000 服务已有连接的限制见前文。Socket.IO 断开失败不恢复已撤销的数据库会话，并记录异常。强制下线记录用户管理操作日志，操作人取自认证后的管理员身份，不采信请求体的 `operatorName`。

错误状态：未认证 401、非管理员 403、参数缺失/格式错误 400、目标记录不存在（包括重复撤销）404、会话存储异常 503。POST 同样受已有 CSRF 检查保护。成功后可重新查询 `GET /permission/session` 获取最新 `loginSessions`，或重新获取会话列表。

## 验证

在已安装 Flask、SQLAlchemy（1.4 或更新版本）、Flask-SocketIO 和 pytest 的环境执行：

```bash
PYTHONPATH=exec/app python3 -m pytest -q exec/app/tests/test_auth_session.py exec/app/tests/test_session_config.py
```

测试通过 SQLAlchemy 使用临时 SQLite 模拟用户表和会话表，以验证事务及认证流程，不连接设备或生产 MySQL；另检查 MySQL 方言的建表语句。上线前仍需在目标 MySQL 验证连接和建表权限。覆盖共用 Cookie 容器时不同账号的查询/操作/审计隔离、单页重新登录和退出隔离、容量限制、实际登录接口、主应用全路由未登录拦截、Token 篡改、会话过期、退出撤销、重新登录轮换、账号变更、权限刷新、审计身份、CSRF、跨进程配置复用和 Socket.IO 连接认证。

## 独立升级状态服务的 HTTPS 入口

`enable_https.sh` 将 `/api/upgrade/process` 精确转发至 `127.0.0.1:9000`，其余请求仍走 8000。前端应使用同源 `/api/upgrade/process?...`，不再直接请求 `http://设备IP:9000`；该查询请求必须显式携带本标签页登录获得的 Bearer Token。查询服务自身校验会话，不调用 8000，所以主应用停机不影响认证，但 MySQL 必须可用。会话过期或退出后返回 401，认证存储故障返回 503。

两个服务应共享 `SESSION_CONFIG_FILE`、来源检查配置和账号/会话数据库；若通过 systemd 环境覆盖配置，两个服务应同步设置。升级脚本会替换 app 目录，因此部署时应将现有会话配置迁移到升级目录之外，并为两个服务指定同一持久化路径，以免新旧进程使用不同配置。HTTPS 模式下 9000 仅监听回环地址。9000 不再开放任意来源的 CORS，Socket.IO 连接也必须携带有效登录会话。

## 启动时禁用开发账号

`configure_session(app)` 读取配置后，`init_auth(app)` 自动调用 `init_developer_accounts(app)`。默认禁用已确认的开发账号 `trinastorage`，不按权限等级禁用其他个人账号。

在 `session_config.json` 中配置以下两个字段（保留原有密钥等配置）：

```json
{
  "DISABLE_DEVELOPER_ACCOUNTS": true,
  "DEVELOPER_ACCOUNTS": ["trinastorage"]
}
```

已有配置文件缺少这两个字段时，同样默认启用禁用 `trinastorage` 的规则；新生成的配置文件会包含它们。修改后重启生效。需要重新允许该账号时，将开关改为 `false`，重启后重新登录。

初始化函数撤销名单内账号在 MySQL 中已有的会话。登录接口拒绝这些账号，并记录失败登录日志；每次会话验证也检查配置派生的 `disabled` 状态。登录查询使用数据库返回的实际用户名判断，避免数据库不区分大小写时通过变更登录名大小写绕过。账号记录和密码不删除、不修改，不新增管理接口。重新启用不会恢复已撤销的会话。

多实例部署必须使用相同规则并全部重启，避免未更新的实例继续接受登录。已建立的 Socket.IO 连接仍遵循前文所述限制；正常后端重启会断开旧连接。
