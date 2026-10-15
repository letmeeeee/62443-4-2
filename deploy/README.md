# 现有 EM-1000 一键升级

## 桌面 GUI

在 Ubuntu 开发机、项目根目录启动：

```sh
python3 deploy/gui.py
```

缺少 Tkinter 时安装 `python3-tk`。界面可以填写目标地址、编译并行数，
选择前端更新、首次证书迁移、可信主机证书和 INI 基准初始化；支持
“检查 SSH”“开始部署”“只生成升级包”、复制命令和保存日志。
完整执行日志自动保存在 `deploy/build-output/logs/`。

GUI 使用 SSH 密钥或 ssh-agent，不保存密码。首次连接请在终端执行
`ssh root@设备IP` 核对主机指纹，并配置密钥认证。可用
`ssh -o BatchMode=yes root@设备IP 'id -u'` 验证；成功应输出 0。
GUI 的“检查 SSH”使用同一认证方式。命令行默认仍支持终端密码输入；
添加 `--batch-mode` 切换为 GUI 所用的非交互模式。

点击部署后会展示目标及停机提示供确认。任务运行时禁止重复启动和直接
关闭窗口，以免中断设备安装或回滚。GUI 只是调用下述 CLI，备份、安装和
回滚逻辑仍统一在现有脚本中。

面向已配置好的 AArch64 工控机：已有 `tems.service`、`python_app.service`、
Python 环境、MySQL、tee-supplicant 和匹配的 OP-TEE。它不会安装操作系统、
系统库或首次建立设备服务。运行前安排维护窗口，SSH 账号需要 root。

在仓库根目录执行日常升级：

```sh
python3 deploy/deploy.py --host root@192.168.2.136
```

脚本自动准备项目内依赖、编译 tems/身份工具/通用 CLI/TA、打包代码、上传、
备份、停止服务、安装、检查现有证书与 INI、按原状态恢复服务，并检查
服务和后端 HTTP 就绪情况。可使用 SSH 密钥免重复输入密码。
默认包含后端 Python/Shell 代码；添加 `--with-frontend` 才更新 `exec/dist`。
`lc_data`、设备 INI、Session 配置/密钥、OTA 公钥、系统库和 HTTPS 配置不覆盖。

## 首次迁移文件私钥到 TA

明确指定需要创建/更新的身份。现有证书使用 renew，缺失证书使用 generate；
均复用已有 TA 角色密钥，不执行 `rotate-rsa`。从机 SAN 必须显式列出全部 IP。

```sh
python3 deploy/deploy.py --host root@192.168.2.136 \
  --master-name master-001 \
  --slave-name slave-001 --slave-ip 192.168.2.136
```

如果还没有 INI 校验基准，先确认设备配置正确，再添加
`--initialize-ini-baseline`。已有基准与 INI 不匹配时始终停止，不自动重签。

需要一并导入可信主机公开证书时，添加：

```sh
--trust-master /path/to/master-001.crt \
--trust-master-fingerprint '完整SHA256指纹'
```

启用 TLS 的从机必须已有非空信任集合或同时导入。部署不会自动把本机
master.crt 当成上级主机信任。主机证书迁移后仍须将新公开证书分发给对端
从机；设备端无法替对端修改信任配置。

## 打包后离线安装

```sh
python3 deploy/deploy.py --bundle-only
```

输出 `deploy/build-output/em1000-upgrade.tar.gz`。将该包和 `deploy/install.py`
复制到设备，在 root 下执行（初始化/证书参数与上面相同）：

```sh
python3 install.py --bundle em1000-upgrade.tar.gz
```

打包时附带 trusted-master 输入的，安装时需同样传入
`--trust-master-fingerprint`。`--skip-build` 只打包既有 `build-deploy` 产物，
不会判断它们是否对应最新源码；正常发布使用默认构建。

## 备份和恢复范围

每次备份保存到设备 `/home/zlg/deploy-backups/时间-编号/`，包含被替换的
原文件、权限与服务状态。失败后脚本停止服务并尝试恢复这些文件、清除本次
新建的目标文件，再恢复原来运行中的服务；备份和上传包保留供排查。
目录和证书工具额外产生的备份目录不会自动删除。

这是异常处理回滚，不是掉电事务；进程被强杀或掉电时需要依据 state.json
与 files/ 手工恢复。首次创建的 TA 密钥无法通过此 ABI 回滚或删除，但不会
覆盖原通用密钥。数据库、配置和业务状态也不属于文件回滚范围。
成功标记只证明基础检查通过，部署后仍须验证真实 Modbus TLS 通信。
