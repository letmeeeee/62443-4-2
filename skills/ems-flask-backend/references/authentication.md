# 认证与启动配置

## 请求链路

`main.create_app()`：创建 Flask → `configure_session(app)` → `init_auth(app)` → 注册业务蓝图。

`init_auth()` 创建 MySQL `login_sessions` 表，调用 `init_developer_accounts(app)`，并注册：

- `before_request/check_session()`：公开页面、静态资源和登录入口按代码豁免；OPTIONS 返回预检响应，不执行业务。其他已注册接口必须通过 Session 检查。新增接口默认受保护。
- `after_request/prevent_auth_caching()`：业务响应设置 `Cache-Control: no-store`，不删除 Cookie、不退出登录。

在 before_request 中返回 None 才是继续处理；返回响应则终止后续业务调用。`authenticate_session()` 返回的 True/False 是内部判断结果，不能混同为 Flask 响应。

登录前置验证成功后 `establish_session()` 撤销当前浏览器的旧会话，生成随机 sid/CSRF token，事务清理过期记录并插入会话，再写 `session["sid"]`。Flask 将其封装为签名 Cookie `lc_session`；它不是 JWT，也不把密码放入 Cookie。

MySQL 表结构：sid（SHA-256 摘要，主键）、username、credential（密码哈希和盐的摘要）、expires_at（Unix 秒）、csrf_token。使用 SQLAlchemy Core 和 `config.engine.begin()`，会话与账号共用现有连接池。启动执行 CREATE TABLE IF NOT EXISTS，需要相应建表权限；数据库失败不得放行受保护业务。

后续请求通过 sid 摘要查询会话，检查有效期，加载当前用户及最新权限，检查账号存在、配置禁用状态、密码凭据变化，最后设置 `g.current_user` 和 `g.csrf_token`。

- 未认证或会话失效：401 / SESSION_INVALID。
- 请求认证存储异常：503；登录/退出等其他路径以实际代码为准，不笼统承诺全部返回 503。
- 默认固定有效期 1800 秒，不随请求自动续期；不要描述为“空闲超时”。
- 改密、删除、改名使旧会话失效；退出撤销服务端记录，复制的旧 Cookie 不能重放。
- 重新登录只轮换当前浏览器会话，其他浏览器会话不自动撤销。

## 前端契约与来源检查

- POST `/permission/login`：保留登录信息并返回 csrf_token，通过响应 Cookie 建立登录态。
- GET `/permission/session`：返回用户名、最新权限和 csrf_token。
- POST `/permission/logout`：撤销当前会话。
- 同源浏览器自动携带 Cookie；不能用 localStorage 中的登录标记替代后端认证。
- POST 等非 GET/HEAD 请求需通过来源检查或 X-CSRF-Token 校验；脚本调用要同时携带 Cookie 和有效 CSRF token。登录请求有单独的跨源检查。
- 当前 `_same_origin()` 检查 Origin/Referer 或 Sec-Fetch-Site；Cookie Secure 配置影响预期协议。不要随意信任客户端伪造的代理头来绕过检查。
- OPTIONS 的 Allow 响应不是跨域授权，也不是登录成功。
- Socket.IO 在连接时校验；现存连接不会仅因 HTTP 退出即时断开。新增业务事件需考虑事件执行时会话是否仍有效。

## 持久启动配置

截至核对时，`session_config.py` 使用 `Path(__file__).resolve().parents[2] / "instance" / "session_config.json"`，解析为 **exec/instance/session_config.json**。历史对话使用 parents[1]，对应 exec/app/instance；不要照抄旧路径。默认路径变化时还要检查 `.gitignore` 是否覆盖新位置，避免真实密钥被提交。

配置可通过 SESSION_CONFIG_FILE 指定其他路径。配置内容：

| Key | 默认/含义 |
| --- | --- |
| FLASK_SECRET_KEY | 首次自动生成 64 字符随机密钥；后续保持稳定 |
| SESSION_COOKIE_SECURE | true；HTTP 调试设 false |
| AUTH_SESSION_SECONDS | 1800，正整数 |
| DISABLE_DEVELOPER_ACCOUNTS | true |
| DEVELOPER_ACCOUNTS | ["trinastorage"] |

文件锁 `.json.lock` 协调多个进程初始化，实际锁状态由 flock 管理，文件存在不意味着锁被占用。写配置采用临时文件、fsync 和原子替换。新建目录 0700、配置文件 0600；损坏配置不应通过重建密钥掩盖。

已有配置缺少禁用字段时按默认名单生效。Session 三个环境变量可覆盖文件值，已有文件不会被覆盖值重写；读取旧文件时先校验旧文件。设置映射到 Flask 配置后生效，修改文件需重启。多实例共享密钥、数据库和禁用策略。

`init_developer_accounts()` 维护规范化名单并在启动时撤销名单内账号旧会话；`load_user()` 派生 disabled，登录也检查名单。登录使用数据库实际用户名，避免大小写别名绕过。没有新增用户表 disabled 字段。重新启用后仍需重新登录，不恢复撤销记录。

## 尚不能据此推断的能力

已有用户表以 username 为主键，尚非不可变独立用户 ID。原有密码算法、密码过期强制限制、各接口角色授权和日志完整性需另查代码。不要将本次 Session 改动描述成完成所有认证安全要求。
