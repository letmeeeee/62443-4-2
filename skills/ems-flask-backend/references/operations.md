# 运行边界与验证

## 服务和 HTTPS

当前主服务 8000、独立升级查询服务 9000 在 HTTPS_ENABLE 开启时监听 127.0.0.1，关闭时监听 0.0.0.0。该开关控制绑定地址，不表示 Flask 本身启用 TLS。TLS 在 Nginx 终结；Cookie Secure 还由 Session 配置控制，两者需要一致。

用户明确接受 9000 只读查询不加 Session。核查 `upgrade/upgrade.py` 的 GET `/api/upgrade/process`：参数合法性、任务路径边界及返回信息仍需控制。若后续增加写接口，重新设计其认证，不能沿用只读豁免。

HTTPS 当前部署说明以 `exec/app/script/HTTPS.md` 和脚本为准：

- 设备 INI 默认 `/home/zlg/lc_data_set.ini`；`[HTTPS] device_ips` 是设备访问地址集合，不是客户端白名单。当前通过 INI 选择 IP，不沿用旧 CLI IP 参数或 DEVICE_IP。
- CN 为 logger，设备 IPv4 地址放在证书 SAN；精确路径 `/api/upgrade/process` 转到 9000，其余业务及 Socket.IO 到 8000。
- `enable_https.sh --install-service` 安装独立副本、g3-https.service、续期 service/timer 以及 Nginx 依赖；脚本有真实系统写入和 reload 副作用。
- 自签名证书需客户端信任，正常重启不应轮换证书；不要将关闭证书验证当作部署方案。
- HTTPS 脚本日志位于 `/var/log/ems/https/`，按日追加；当前无自动历史清理。
- 不要执行部署来验证普通代码编辑，也不要在开发机上运行设备专用安装操作。

以上 HTTPS 内容来自本次核对时的工作区，晚于对话最初的旧脚本；后续修改先查看当前选项与实际实现。

## 环境副作用

`config.py` 导入可能创建设备路径目录；`utils/method.py` 的模块级 `ini_param()` 会初始化连接。Flask 主模块在导入时创建 app；不要为了读取端口或常量而启动生产连接。用文本检查或受控测试替身。

现有工程依赖 Flask、Flask-SocketIO、SQLAlchemy、MySQL 驱动以及设备库（如 pymodbus）。认证代码使用 SQLAlchemy 1.4+ API。不要把某次 /tmp 下的临时测试虚拟环境路径固化成项目运行依赖。

## 测试选择

从仓库根目录运行相关测试：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=exec/app python3 -m pytest -q \
  exec/app/tests/test_auth_session.py \
  exec/app/tests/test_session_config.py
```

- 认证测试用 SQLite/SQLAlchemy 替身，不连接真实设备或生产 MySQL；MySQL 方言编译检查不等同真实 MySQL 执行。
- 主应用路由拦截测试替换了设备 handler，只证明注册和拦截路径，不证明真实设备行为或每个接口的角色授权。
- 配置测试覆盖首次生成、并发进程共享密钥、重启复用、环境覆盖和非法配置拒绝。
- 升级上传、BMS 参数映射以及 HTTPS 相关测试按当前 tests 目录选择，导入前关注设备依赖。
- 修改 Session 时优先覆盖未登录拦截、改密/删除/禁用失效、退出后的 Cookie 重放、CSRF 及存储失败不放行。
- 若新版本增加 HTTPS_ENABLE 等导入配置，同步测试替身，不能为了测试通过删除产品代码。

对原有 CRLF 文件，可用 `git -c core.whitespace=cr-at-eol diff --check` 排除换行误报；仍需检查真实尾随空白。仅文档/技能变更无需跑设备测试。
