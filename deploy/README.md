# 现有 EM-1000 一键升级

无授权、无需 C 编译的字节码分发可使用 `python3 deploy/build_pyc.py`，见
[PYC_BUILD.md](PYC_BUILD.md)。支持 x86 生成版本匹配的 ARM64 CPython 字节码，
但 `.pyc` 不等于强代码混淆。

快速 Python 混淆可使用 `python3 deploy/build_pyarmor.py`，见
[PYARMOR_BUILD.md](PYARMOR_BUILD.md)；设备继续用 Python 启动，Shell 保留明文。

设备端 Python 代码保护构建见 [PROTECTED_BUILD.md](PROTECTED_BUILD.md)，Shell 保留明文脚本。
构建入口为 `python3 deploy/build_protected.py`，不改写业务源码或自动部署；
保护产物与本页的源码升级包格式不同，不能交给现有安装器直接安装。

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
Python 环境、MySQL、tee-supplicant 和匹配的 OP-TEE。它不会安装操作系统或系统库；tems/Web 服务须已存在，GOOSE 服务可按下文首次安装。运行前安排维护窗口，SSH 账号需要 root。

在仓库根目录执行日常升级：

```sh
python3 deploy/deploy.py --host root@192.168.2.136
```

脚本自动准备项目内依赖、编译 tems/身份工具/通用 CLI/TA、libiec61850/HAL 和安全 GOOSE 桥接程序，打包代码、上传、
备份、停止服务、安装、检查现有证书与 INI、按原状态恢复服务，并检查
服务和后端 HTTP 就绪情况。可使用 SSH 密钥免重复输入密码。
默认包含后端 Python/Shell 代码；添加 `--with-frontend` 才更新 `exec/dist`。
`lc_data`、设备 INI、Session 配置/密钥、GOOSE PKI、GOOSE 日志、OTA 公钥、系统库和 HTTPS 配置不覆盖。

## GOOSE 与 Modbus 身份工具

默认构建和打包以下程序，不需要增加开关：

| 组件 | 构建产物 | 设备安装位置 |
| --- | --- | --- |
| GOOSE 安全桥接 | `goose/goose_test/build-deploy/goose_middle` | `/home/zlg/goose_middle` |
| GOOSE 服务模板 | `goose/goose_test/deploy/goose_middle.service` | 首次安装到 `/etc/systemd/system/goose_middle.service` |
| Modbus 身份工具 | `logger/build-deploy/modbus_tee_identity` | `/home/zlg/app/bin/modbus_tee_identity` |

`modbus_tee_identity` 是可执行辅助工具，不是独立 systemd 服务；它位于升级包的
`payload/home/zlg/app/bin/` 中。GOOSE 的 libiec61850/HAL 为静态链接输入，会先编译再链接
到 goose_middle，无需单独部署这两个静态库。libcrypto.so.1.1 等运行依赖仍由设备提供。

- 已有 GOOSE 服务：检查 ExecStart 是否指向上述安装位置，保留原 unit 和 drop-in 配置。
  更新前停止，更新后仅恢复原本运行的服务；原先停用的服务仍停用，enable 状态不改变。
- 首次部署 GOOSE：安装程序和默认 unit，执行 daemon-reload，保留服务停用且不执行 enable。
  先通过 GOOSE PKI 接口导入四类材料并 apply；确认通信后，再在设备显式执行
  `systemctl enable goose_middle.service` 设置开机启动。未配置 PKI 时不会启动明文通信。
- 服务已存在但路径不同、被 mask 或配置异常时，安装前拒绝继续，需先确认现场配置，
  不自动覆盖自定义启动方式。不要同时运行旧的手工启动 GOOSE 进程。
- GOOSE 程序纳入 ARM64 校验、设备 ldd 依赖检查、文件备份、服务检查和失败回滚。
  首次安装后失败会删除本次新建的 unit 并 daemon-reload。
- 不打包、不创建或覆盖 `/etc/ems/goose/` 的证书、私钥、CA、CRL，不改动
  `/mnt/nvme/goose_log/`，不生成密钥，也不自动执行 GOOSE PKI apply。

`--skip-build` 现在还要求已有 `goose/goose_test/build-deploy/goose_middle`；缺文件或架构
错误会直接拒绝打包。新包须配套本次 `deploy/install.py`，旧安装器不识别新增 GOOSE 路径。
没有 GOOSE 载荷的旧升级包仍可由新安装器按原范围安装，不触碰 GOOSE 服务。

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
不会判断它们是否对应最新源码；正常发布使用默认构建。GOOSE 程序和服务文件已包含在新包中。

## 备份和恢复范围

每次备份保存到设备 `/home/zlg/deploy-backups/时间-编号/`，包含被替换的
原文件、权限与服务状态。失败后脚本停止相关服务并尝试恢复这些文件、清除本次
新建的目标文件，再恢复原来运行中的服务；备份和上传包保留供排查。
目录和证书工具额外产生的备份目录不会自动删除。

这是异常处理回滚，不是掉电事务；进程被强杀或掉电时需要依据 state.json
与 files/ 手工恢复。首次创建的 TA 密钥无法通过此 ABI 回滚或删除，但不会
覆盖原通用密钥。数据库、配置和业务状态也不属于文件回滚范围。
成功标记只证明基础检查通过，部署后仍须验证真实 Modbus TLS 通信。
