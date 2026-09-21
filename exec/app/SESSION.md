# Session 登录与接口校验

## 实现与范围

主应用 `main.py` 使用 Flask 签名 Cookie（`lc_session`）携带随机会话 ID，服务端使用现有 MySQL 数据库中的 `login_sessions` 表保存会话与用户的对应关系。会话、用户账号和登录日志复用 `config.engine` 的连接池，无需迁移用户表或配置额外数据库。

- `/permission/login` 验证成功后建立会话，保留原有响应字段，并返回 `csrf_token`。
- `GET /permission/session` 返回当前用户名、最新权限和 `csrf_token`。
- `POST /permission/logout` 删除服务端会话并清理 Cookie，复制的旧 Cookie 也不能再次访问。
- 主应用中除登录、前端页面、静态资源外的所有已注册接口均校验 Session，包括 `/api/*`、`/permission/*`、`/network/*`、`/ini/*`、`/system/*` 等；新注册接口默认受保护。OPTIONS 只返回预检响应，不执行业务。
- 未登录、过期、会话被撤销返回 HTTP 401，`code` 为 `SESSION_INVALID`；认证存储故障返回 503，不放行业务。
- 默认从登录时起 30 分钟到期，不随访问自动续期。重新登录轮换当前会话，其他浏览器的会话独立保留。
- 每次请求检查账号是否仍存在、密码凭据是否变化，并读取最新权限。删除、改名、改密后旧会话失效。
- 业务接口的操作人取自 `g.current_user["username"]`，忽略前端传入的 `operatorName`；目标用户字段 `username` 含义不变。
- 主应用的 Socket.IO 在连接时校验 Session，前端应在登录成功后连接或重新连接。

这是身份认证层。各操作的角色授权仍由业务接口负责，账号禁用由启动配置控制，不新增数据库禁用字段。独立 `upgrade/upgrade.py`（9000 端口）复用同一 Session 配置、MySQL 会话表及认证逻辑，HTTP 查询和 Socket.IO 连接均校验登录态；已建立的 Socket.IO 连接也不因 HTTP 退出自动断开，后续增加业务事件时需逐事件校验身份。

## 启动配置

后端 `main.py` 和 `upgrade/upgrade.py` 均在 `init_auth(app)` 前自动调用 `script/session_config.py` 中的 `configure_session(app)`，无需手动 export 即可启动。脚本通过 Python 函数将配置写入 Flask，不依赖子进程修改父进程环境变量。

首次启动自动生成 `exec/app/instance/session_config.json`：

- `FLASK_SECRET_KEY`：自动生成 64 字符随机密钥，保存后每次重启复用。
- `SESSION_COOKIE_SECURE`：默认 `true`，仅通过 HTTPS 发送 Cookie。
- `AUTH_SESSION_SECONDS`：默认 `1800`，即 30 分钟。

要调整配置，直接编辑生成的 JSON 文件并重启后端。例如将 `AUTH_SESSION_SECONDS` 改为 `3600`；HTTP 本地调试将 `SESSION_COOKIE_SECURE` 改为 `false`。保留原有密钥值，避免旧会话失效。修改脚本中的默认值只影响尚未生成配置文件的首次启动。

也可提前运行初始化脚本（不会输出密钥）：

```bash
python3 exec/app/script/session_config.py
```

配置文件以 0600 权限保存，默认目录首次创建权限为 0700，已通过 `.gitignore` 排除。多个启动进程通过文件锁和原子写入共享同一密钥。服务运行用户需要配置目录的读写权限。文件损坏或配置非法时停止启动，不会自动重新生成密钥。

若应用升级会替换代码目录，使用环境变量 `SESSION_CONFIG_FILE` 指定升级不会覆盖的持久化文件路径。多个实例必须共享相同密钥、MySQL 数据库并保持时钟同步。原有 `FLASK_SECRET_KEY`、`SESSION_COOKIE_SECURE`（0/1）、`AUTH_SESSION_SECONDS` 环境变量仍可覆盖文件配置；首次创建时覆盖值写入文件，已有文件不被环境覆盖值改写。systemd 环境应在服务配置中设置，终端 export 不会影响已运行的服务。

应用启动时通过 `CREATE TABLE IF NOT EXISTS` 初始化 `login_sessions`（InnoDB、utf8mb4）。数据库连接复用现有 INI 配置，不再读取 `AUTH_SESSION_DB`，也不创建本地 SQLite 文件。数据库账号需要会话表的 SELECT、INSERT、DELETE 权限，以及执行启动建表语句所需的 CREATE 权限（即使表已存在，启动时也会执行该语句）。表结构如下。数据库不可用或建表失败时拒绝启动；运行中会话校验失败返回 503。

```sql
CREATE TABLE IF NOT EXISTS login_sessions (
    sid VARCHAR(64) NOT NULL PRIMARY KEY,
    username VARCHAR(64) NOT NULL,
    credential VARCHAR(64) NOT NULL,
    expires_at DOUBLE NOT NULL,
    csrf_token VARCHAR(64) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

`sid` 保存随机会话 ID 的 SHA-256 摘要，`credential` 保存用于检测密码变化的凭据摘要，`expires_at` 为 Unix 时间戳（秒）。会话写入和删除使用数据库事务。密钥和 MySQL 数据同时保留时，重启后未过期会话仍有效；过期记录在新登录时清理。

从此前 SQLite 版本切换时，不迁移旧会话，用户需重新登录。旧 SQLite 文件不再使用，可按部署流程清理。

默认 Cookie 仅通过 HTTPS 发送，适用于 `enable_https.sh` 的同源反向代理部署。本地 HTTP 调试时可将配置文件中的 `SESSION_COOKIE_SECURE` 改为 `false` 后重启，或在启动环境中设置 `SESSION_COOKIE_SECURE=0`。

Cookie 的 HttpOnly 和 SameSite=Lax 始终启用。不要通过任意 X-Forwarded-* 请求头改变认证逻辑。

## 前端对接

同源浏览器自动接收和携带 Cookie。页面刷新时可调用 `/permission/session` 恢复用户信息；收到 401 时清理前端登录状态并跳转登录页。退出时必须请求后端 `/permission/logout`，仅删除 localStorage 不会撤销会话。

修改类请求校验同源 Origin/Referer 或浏览器的 `Sec-Fetch-Site: same-origin`，因此现有同源浏览器请求不必额外处理 Token。对于缺少这些请求头的客户端，需要携带登录返回的 `X-CSRF-Token`。CSRF Token 不能替代 Cookie 身份凭证。跨域前端未开放，需要另行设计明确的允许源策略。

```javascript
const login = await fetch('/permission/login', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ username, password })
});
const result = await login.json();
if (!login.ok) throw new Error(result.error);

const current = await fetch('/permission/session');

await fetch('/permission/logout', {
  method: 'POST',
  headers: { 'X-CSRF-Token': result.csrf_token }
});
```

命令行、自动化脚本同样需要先登录，保存响应 Cookie，再携带 Cookie 请求接口；POST 等请求还需 `X-CSRF-Token`。不按回环 IP 或内网 IP 绕过认证。现有升级与回滚脚本的实际状态上报实现直接写本地 JSON，保留这一行为；若恢复其注释中的 HTTP 上报代码，也必须增加认证。

## 验证

在已安装 Flask、SQLAlchemy（1.4 或更新版本）、Flask-SocketIO 和 pytest 的环境执行：

```bash
PYTHONPATH=exec/app python3 -m pytest -q exec/app/tests/test_auth_session.py exec/app/tests/test_session_config.py
```

测试通过 SQLAlchemy 使用临时 SQLite 模拟用户表和会话表，以验证事务及认证流程，不连接设备或生产 MySQL；另检查 MySQL 方言的建表语句。上线前仍需在目标 MySQL 验证连接和建表权限。覆盖实际登录接口、主应用全路由未登录拦截、Cookie 篡改、会话过期、退出撤销、重新登录轮换、账号变更、权限刷新、审计身份、CSRF、跨进程配置复用和 Socket.IO 连接认证。

## 独立升级状态服务的 HTTPS 入口

`enable_https.sh` 将 `/api/upgrade/process` 精确转发至 `127.0.0.1:9000`，其余请求仍走 8000。前端应使用同源 `/api/upgrade/process?...`，不再直接请求 `http://设备IP:9000`；浏览器会自动携带主应用登录获得的 `lc_session`。查询服务自身校验会话，不调用 8000，所以主应用停机不影响认证，但 MySQL 必须可用。会话过期或退出后返回 401，认证存储故障返回 503。

两个服务必须使用相同的 `SESSION_CONFIG_FILE`、密钥、Cookie 配置和账号数据库；若通过 systemd 环境覆盖配置，两个服务应同步设置。升级脚本会替换 app 目录，因此部署时应将现有会话配置迁移到升级目录之外，并为两个服务指定同一持久化路径，以免新旧进程使用不同密钥。HTTPS 模式下 9000 仅监听回环地址。9000 不再开放任意来源的 CORS，Socket.IO 连接也必须携带有效登录会话。

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
