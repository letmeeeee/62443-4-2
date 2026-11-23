# 认证、账号与请求错误

## 实际链路

`main.create_app()` 调用 `configure_session()`（内部还调用 `configure_security()`）、`init_auth()`、`init_security_http()`，再注册蓝图。按当前代码核对顺序及公开路由。before_request 返回响应会提前结束请求，路由开头没日志可能是认证、CSRF 或准入拦截，不是路由未注册。

MySQL 会话 sid 以摘要保存，HTTP 使用 Authorization: Bearer，不能用 Cookie 自动携带代替；CSRF token 与登录会话关联。认证、授权、账号锁定、首次改密限制、频率与容量准入分别检查。登录成功并不代表所有接口可访问。

- `GET /permission/session` 查询会话；`POST /permission/login` 建立会话并返回 CSRF token；`POST /permission/logout` 撤销会话。
- 写请求通常需要同源检查或有效 `X-CSRF-Token`，脚本需同时携带 Bearer token。以 `auth.py` 的 `_same_origin()` 和豁免条件为准；不要把所有 POST 或所有接口一概而论。
- `AUTH_SESSION_SECONDS` 默认 1800 是会话寿命；`AUTH_IDLE_SECONDS` 默认 900 是另一项空闲超时。不要沿用旧文档“只有固定超时、不记录活动”的结论。
- 同账号可多会话，当前浏览器重新登录不代表其他会话撤销。改密会撤销目标会话；Socket.IO 当前有会话断连回调，修改时同时核对事件认证及撤销链路。
- `DISABLE_DEVELOPER_ACCOUNTS` 和 `DEVELOPER_ACCOUNTS` 是部署策略，默认名单含 trinastorage；另有 security_store 的账号状态，不能说项目完全不支持 enabled。

## 改密与耗时

本人修改入口 `POST /permission/update`：`username`、`old_password`、`password`（新密码）。本人改密验证旧密码，成功清除首次登录标志并撤销会话；管理员修改他人密码按重置处理。

`security_store.PASSWORD_POLICY` 当前 PBKDF2-HMAC-SHA256、600000 次迭代，最少 12、最多 128 字符，大小写、数字和特殊字符，不包含用户名。`_history()` 当前截取 5 项：当前密码加最多 4 个历史密码。`PASSWORD_REUSED` 表示与其中之一匹配，不代表旧密码验证失败。

设备上每次哈希可能耗时数秒，历史比较有多次哈希；不要凭日志推断具体比较次数。核对是否在共享锁/数据库事务里执行耗时计算。若移到锁外，写入前需重新校验凭据及历史版本，避免并发改密绕过策略。不要直接降低迭代数或取消历史限制来修 CPU 问题。

## 启动配置

`SESSION_CONFIG_FILE` 指定 Session JSON；默认 `Path(session_config.py).resolve().parents[2]/instance/session_config.json`，仓库对应 `exec/instance/`。不要凭 app 路径猜父目录。文件包含持久签名密钥、Cookie Secure、会话寿命及开发账号策略；读取前后均校验，损坏时不得自动重建密钥。`FLASK_SECRET_KEY`、`AUTH_SESSION_SECONDS`、`SESSION_COOKIE_SECURE` 有独立环境覆盖，具体类型看加载器。修改需重启进程。

安全中心另由 `SECURITY_CONFIG_FILE` 指向 JSON；详见运行参考。两者不是同一个文件。不要打印整份 Session 文件或进程环境以获取路径。

## 错误定位

统一归一化位于 `security_audit.init_security_http()` 的 after_request；错误响应可能删去原始数据，仅保留 code、通用 message、trace_id 等。不能仅凭前端泛化 message 断定根因。

- 401：先查会话、寿命、空闲和凭据变化。
- 403：查权限、来源/CSRF、锁定和强制改密等具体 reason。
- 登录 503 `SERVICE_UNAVAILABLE`：查全局 admission/认证存储日志；证书临期本身不能推出登录被限制。
- `RESOURCE_NOT_FOUND`：route_security 的 FileNotFoundError 也映射此码，并不必然是路由不存在。

测试入口：`test_auth_session.py`、`test_security_center.py`、`test_session_config.py`、`test_main_auth.py`（以当前 tests 文件为准）。不连接生产 MySQL；替身不能证明真实数据库锁行为或设备性能。
