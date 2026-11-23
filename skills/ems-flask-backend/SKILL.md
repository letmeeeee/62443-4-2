---
name: ems-flask-backend
description: 用于 62443-4-2 项目的 EMS/Modbus Flask 后端开发维护，定位 bug、解析功能、增加或调整接口，覆盖认证权限、PKI/HTTPS、安全中心、资源监控与升级。以当前代码和设备运行证据为准，不代替 IEC 认证评估。
---

# EMS 项目开发维护

适用于包含 `exec/app/main.py`、`routes/route_permission.py` 和 `utils/auth.py` 的 62443-4-2 仓库。仓库副本可搬迁，先确定根目录。本文于 2026-11-19 核对；代码优先于本文和历史对话。

## 工作方式

先检查适用的 AGENTS.md、工作区改动和实际调用入口。用户询问功能时沿请求链解释；用户要求修复或新增时完成实现及必要验证，不停留在建议。旧文档描述和历史故障只作为线索，不直接视为当前缺陷。

定位问题先分清：浏览器 → Nginx → Flask 认证/准入 → 路由 → 数据库或系统脚本 → 服务实际状态。结合 URL、方法、HTTP 状态、响应 code、trace_id 与日志匹配。只有截图或耗时不能证明根因；优先做可区分原因的只读检查，缺失的关键证据再向用户索取。

修改已有接口时核对调用方，保留路径、参数、响应和权限契约，除非用户明确要求调整。新增字段区分可选、默认及错误语义；系统命令或脚本失败保留关键诊断，日志不得泄露密码、私钥、Cookie、CSRF 或真实密钥配置。审计操作人取验证后的 `g.current_user`，不能信任 `operatorName`。

## 按任务读取

- 登录、账号、改密、Session、CSRF、权限：读 [认证参考](references/authentication.md)。
- CSR、证书、CRL、general/trina、私钥和 TLS：读 [PKI 参考](references/pki.md)。
- 部署、环境变量、SBOM、性能、升级与测试：读 [运行参考](references/operations.md)。

## 代码导航

| 位置 | 职责 |
| --- | --- |
| `exec/app/main.py` | 8000 主应用、蓝图、Socket.IO；模块导入就创建 app |
| `routes/route_permission.py`、`utils/auth.py` | 账号路由、会话、准入、CSRF |
| `utils/security_store.py`、`security_audit.py` | 安全状态、密码策略、审计及统一错误响应 |
| `routes/route_security.py`、`route_system.py` | 安全中心、组件清单、资源监控 |
| `routes/route_cert.py`、`script/custom_pki.py` | 证书接口、定制批次暂存及应用 |
| `script/pki_common.py`、`crl_store.py`、`https_certificates.py` | PKI 公共校验、吊销、HTTPS 身份 |
| `script/enable_https.sh`、`https_config.py` | Nginx/HTTPS 部署和维护 |
| `script/session_config.py`、`security_config.py` | 两套启动 JSON 配置入口 |
| `routes/route_g2.py`、`route_g3.py`、`utils/method.py` | INI、网络、设备业务、数据及升级入口 |
| `upgrade/upgrade.py`、`script/upgrade.sh`、`rollback.sh` | 独立 9000 查询、更新及回滚 |
| `config.py`、`utils/ini.py` | 数据库连接池、设备 INI 和角色配置 |
| `exec/dist` | 前端构建产物；先找前端源码，不直接重写压缩产物 |
| `logger`、`lc_data`、`goose` | 设备 C/C++ 配套模块，后端任务按实际依赖扩展范围 |

表中省略前缀的路径相对于 `exec/app/`。

## 项目边界

- 账号和 Session 使用现有 MySQL 连接池；测试可用 SQLite 替身，不擅自换 Redis/JWT 或真实数据库。
- 开发账号策略、账号 enabled 状态和角色权限分别核对；不要按管理员等级批量禁用账号。
- 独立 9000 升级状态查询保留免 Session 设计；不能扩展成升级写操作免认证。
- 不为读配置导入完整主应用或设备模块，可能初始化 MySQL、目录与连接。使用源码检查和隔离替身。
- 普通开发任务不自动包含设备部署、重启、网络变更、密钥删除或数据库迁移。已明确授权的操作继续执行；先完成本地可验证工作。
- 设备与开发机、运行目录与仓库、系统安装副本与 app 副本要明确区分。不把暂存目录、工具版本或服务名当成所有设备的固定事实。

## 验证与交付

按变更挑选现有测试及必要回归，确认依赖和副作用再运行。检查相关 diff 与 CRLF，保留用户改动。说明行为变化、测试范围和部署文件；本地通过不代表实机通过，历史测试数字不作为本次结果。前后端反馈文档写清路径、参数、响应、错误码及前端是否需改，区分已实现、建议与待验证事项。
