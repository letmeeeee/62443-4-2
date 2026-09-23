---
name: ems-flask-backend
description: 维护 62443-4-2 仓库中的 EMS/Modbus Flask 后端，处理 Session 认证、开发账号禁用、权限与日志、HTTPS 部署及独立升级状态查询；用于此项目的开发、排错和代码讲解，不代替 IEC 标准认证评估。
---

# EMS Flask 后端项目技能

## 使用方式

在当前工作区定位 `exec/app/main.py`、`exec/app/routes/route_permission.py` 和 `exec/app/utils/auth.py`，确认是本项目后再使用。以下信息核对于 2026-09-21；路径均相对于仓库根目录，代码优先于历史对话和开发日志。用户的新指令优先于这里保存的设计选择。

先查看相关文件及工作区改动，再实施任务。不要因本技能包含安全背景就自动扩大为全面加固、部署或认证审核。讲解代码时，按实际请求路径说明返回值及副作用，区分已经实现的功能和预留能力。

## 代码导航

| 位置 | 职责 |
| --- | --- |
| `exec/app/main.py` | 主 Flask/Socket.IO 应用，8000 端口；加载 Session 配置、注册认证钩子及三个业务蓝图 |
| `exec/app/routes/route_permission.py` | 登录、会话查询、退出、用户增删改查及登录日志 |
| `exec/app/routes/route_g2.py` | 网络、INI、Modbus 请求、系统操作和数据查询 |
| `exec/app/routes/route_g3.py` | 设备数据、参数、故障及历史记录、升级上传和启动 |
| `exec/app/utils/auth.py` | MySQL 会话存储、统一认证、CSRF、开发账号禁用策略 |
| `exec/app/script/session_config.py` | 配置文件初始化、持久密钥、启动配置映射 |
| `exec/app/config.py`、`utils/ini.py` | 设备配置、角色权限映射、INI 读取和 SQLAlchemy engine 初始化 |
| `exec/app/utils/operationLog.py` | 操作日志；现有登录日志写入 MySQL |
| `exec/app/upgrade/upgrade.py` | 独立 9000 服务，查询升级状态 |
| `exec/app/script/enable_https.sh`、`https_config.py` | 设备 HTTPS/Nginx/证书初始化与维护 |
| `exec/dist` | 主应用提供的前端构建产物；不要当作前端源码直接重写 |
| `lc_data`、`logger` | 仓库中的 C/设备配套代码；普通 Flask 修改无需扩展到这里 |
| `Markdown/YYYYMMDD.md`、`开发进度.md` | 每日进度与模板；仅在任务需要时更新，不将计划当成已完成事实 |

认证或配置任务阅读 [认证与配置参考](references/authentication.md)。HTTPS、升级查询或验证任务阅读 [运行与验证参考](references/operations.md)。项目自身的 `exec/app/SESSION.md` 和 `exec/app/script/HTTPS.md` 有部署说明，使用前与当前代码核对。

## 需要保持的项目选择

- 会话使用现有 MySQL `config.engine`，不要悄悄恢复 SQLite 或引入 Redis/JWT。测试中的 SQLite 仅为数据库替身。
- 以经过验证的 `g.current_user["username"]` 作为操作人；客户端 `operatorName` 不作为权限或审计依据。目标用户 `username` 与操作人是不同概念。
- 开发账号明确为 `trinastorage`。按配置名单禁用，不按最高权限等级批量禁用个人账号；现行方案不增加账号启停接口或数据库 disabled 字段。
- 9000 查询服务保留独立、免 Session 的设计，便于主服务升级重启时查询进度。不要把免认证推广到升级上传、启动、回滚或其他写操作。
- 多级权限分配、身份认证、角色授权、审计是不同功能。全局 Session 钩子不代表每个业务接口已经正确授权。
- 当前允许同一账号在不同浏览器持有多个会话，没有按用户限制并发数。用户唯一标识不等同单会话登录；涉及 IEC 62443-4-2 判断时核对目标等级、版本与 CR 1.1 RE(1)/CR 2.7 等实际条款，不能据此技能宣称合规。

## 验证与交付

优先运行与修改相关的测试，明确哪些使用替身、哪些经过实机验证。历史上认证与配置测试曾通过，但不是当前版本永远通过的保证。不要仅为读配置而直接导入完整主应用：模块导入可能初始化 MySQL、目录或设备依赖。

保留用户尚未提交的改动，注意旧 Python 文件常用 CRLF、新文件多用 LF，避免无关换行重写。不复制真实密码、密钥、Cookie 或生成的配置到技能、日志或提交中。

交付时说明行为变化、相关文件、测试结果，以及必要的重启/配置迁移事项。设备部署脚本会修改系统服务和网络入口；普通代码任务不意味着要执行部署。
