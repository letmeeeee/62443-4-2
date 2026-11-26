# 设备端 Python 代码保护构建（Shell 保留明文）

`build_protected.py` 仅构建 `exec/app` 下的设备运行代码，包含 8000、9000、
证书、升级、回滚及辅助脚本。测试、第三方源码、开发机工具和设备私有目录
不发布。仅 Python 文件进行编译保护，Shell 以可读、可执行脚本发布。
构建时动态扫描文件，不把当前的文件数量写死。

业务源码保持原样，全部适配发生在 `work/source` 构建副本。原有
`deploy.py` / `install.py` 仍使用源码部署格式，没有改成发布保护产物。

## 依赖与构建环境

在与目标设备兼容的 **Linux ARM64** 构建环境执行。Python 主次版本、glibc
及原生扩展必须与部署环境兼容；推荐使用与设备同版本的系统。不能直接把
x86 开发机的 Nuitka 产物复制到 ARM64。脚本默认校验本机架构，不隐式交叉编译。

以下安装命令仅供构建机执行，不要求在运行设备上安装编译器：

```bash
sudo apt-get install build-essential python3-dev python3-venv patchelf
python3 -m venv /tmp/ems-build-venv
source /tmp/ems-build-venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install Nuitka ordered-set zstandard
python -m pip freeze > /tmp/ems-build-requirements.lock
```

正式发布应保存并复用通过实机验证的锁文件及系统版本。当前仓库的依赖清单
仍需要结合目标设备核对；不要在混有无关业务包的 Python 环境中构建。
Socket.IO 的 threading 驱动及 SQLAlchemy 的 MySQL/PyMySQL 方言显式包含；
如果设备实际使用 eventlet/gevent，需要核对并包含对应动态驱动后验证。

先生成构建计划（只用 Python 标准库，不依赖 Nuitka，不启动服务）：

```bash
python3 deploy/build_protected.py --plan --output /tmp/ems-protected-plan
```

在项目根目录执行实际构建：

```bash
python deploy/build_protected.py \
  --output deploy/build-output/protected-v001 \
  --jobs 4
```

已有输出目录会被拒绝，防止误删文件或混入旧版本。每次使用新的目录。
`--target-arch x86_64` 仅用于 Linux x86 的本机构建调试，不代表 ARM64 验证。
`--logical-root` 默认 `/home/zlg/app`；它保持现有资源与配置的路径语义，
不是把所有硬编码设备路径改成可配置路径。

## 产物与运行方式

```text
protected-v001/
├── build-plan.json                # 文件清单、源码摘要、构建命令
├── nuitka-report.xml             # Nuitka 编译报告
├── ems-protected-app.tar.gz      # 仅 release 目录的压缩包
├── release/
│   ├── manifest.json             # 构建信息、文件摘要
│   └── app/
│       ├── main.py               # ELF 可执行入口，保留历史文件名
│       ├── upgrade/upgrade.py    # ELF 可执行入口
│       ├── script/*.py           # ELF 可执行入口
│       ├── script/*.sh           # 可读、可执行的 Shell 脚本
│       └── .runtime/ems.dist/    # 必须完整保留的 Nuitka Standalone
└── work/                         # 含明文源码、生成 C 等，仅留在构建机
```

**只发布 `release` 或其压缩包；绝不能发布整个构建输出目录。**
构建检查 Python 文件均有 ELF 替代物，Shell 文件保持文本格式及执行权限；
拒绝产物中的明文 `.py`、`.pyc/.pyo` 和 `.c/.h`。manifest 提供完整性比对，
不等于可信签名。

Python 入口保留 `.py` 后缀，以兼容程序中的固定路径和文件存在性检查，
其内容已经是 ELF，必须直接执行。Shell 继续使用原解释器，也可直接执行：

```bash
/home/zlg/app/main.py
/home/zlg/app/upgrade/upgrade.py
/home/zlg/app/script/watch_upgrade_status.py task001 --once
/home/zlg/app/script/enable_https.sh --help
```

Python 入口不再写成 `python3 main.py`，也不能 `source` 这些 ELF 文件。
Shell 仍可使用 `bash upgrade.sh`（按脚本原有解释器选择），保留原有执行方式。
内部原有的 `sys.executable + 脚本路径` 调用则由 Standalone
入口分发器接收，参数和退出码保持传递，不会再次启动 8000。

两个服务是独立 OS 进程，使用同一份只读 Standalone 文件，停止 8000 不会
停止 9000。构建不会启动它们。无业务导入的自检命令：

```bash
/home/zlg/app/.runtime/ems.dist/ems-runtime --ems-info
```

## 构建副本中做了哪些适配

1. 为全部自有 Python 模块生成静态导入分支，编译未被 HTTP 入口引用的模块；
   只执行选中的分支。原 `__main__` 判断增加入口选择条件，保留 CLI 的模块
   全局变量作用域，不用 `exec(源码)`、`runpy` 或临时解密 `.py`。
2. 模块的 `__file__` 映射回稳定安装目录，构建副本中去掉对该路径的 `resolve()`，
   防止版本目录符号链接将 Session/安全状态路径带入具体发布版本。
   保护模式通过导入模块进入主逻辑，Flask 的模块名会由
   `__main__` 变为 `main` 等正常模块名，应纳入实机联调。
3. HTTPS apply 保留原有 `bash` 调用；Shell 直接执行编译后的证书工具。
   `enable_https.sh` 保留原有 `BASH_SOURCE` 定位和读取自身注释的帮助输出。
4. HTTPS 独立安装复制完整 Standalone 和必要入口到
   `/usr/local/lib/g3-https/`，生成的 unit 使用其 `script/enable_https.sh`。
   现有安装副本仍需在迁移时显式更新，构建不会修改系统文件。
5. 升级开始时保存数据库工具及完整运行库到私有临时目录，替换 app 后仍可
   执行；正常退出时清理。Shell 中的 ZIP 校验内联 Python 随脚本保持明文，
   运行时仍需要系统 Python。强杀可能留下临时目录，排障后人工清理。
6. 身份轮换 Shell 内联 Python 仍单独纳入 Nuitka，这是因为它需要导入已编译的
   本地 PKI 模块；Shell 本身是明文调用包装，保留原调用参数。
7. 点表生成器依赖读取源码 AST，保护模式改用本次构建提取的点定义。
   它仍可处理外部 XLSX，但不再扫描设备上新增/改动的 Python 定义；点定义
   变化后需要重新构建。默认 XLSX 不包含在发布包内。

新增适配均附注释；构建打印清单、编译命令、输出位置，失败立即退出。
运行入口仅在启动失败时打印诊断，不在标准输出增加内容，以免破坏 JSON/CLI
输出协议。原业务日志继续保留。

## 部署接入边界

这是**构建与打包工具**，不是设备安装器。不要把产物直接传给原
`deploy/install.py`，也不要伪装成旧 `app.zip` 使用原 OTA/回滚流程：原流程
包含源码格式校验和整个目录替换，尚未适配受保护运行库的生命周期。

受保护版本应安装到不可变版本目录，例如：

```text
/home/zlg/protected-releases/v001/app/
/home/zlg/app -> protected-releases/v001/app
```

迁移前需要保留现有 `app/bin` 的原生工具、设备本地配置及原有运行资源；
此构建包只包含代码与显式允许的公共资源，不是整机运行目录备份。
前端 `/home/zlg/dist`、外部配置、数据库、PKI、日志和状态目录独立保留。
`security_config.json` 不作为设备配置覆盖发布。

systemd 中的 Python 入口需改成直接执行 ELF，例如：

```ini
# python_app.service 的 drop-in 示例
[Service]
ExecStart=
ExecStart=/home/zlg/app/main.py
```

9000 使用 `/home/zlg/app/upgrade/upgrade.py`；升级与回滚服务继续按原有方式
执行 `/home/zlg/app/script/upgrade.sh`、`rollback.sh`，不因本次调整更换 Shell
解释器。示例不重置原服务的用户、
环境变量和工作目录，需要按实际 unit 核对。配置、密钥和状态不得放入
不可变代码目录。

切换发布时，先安装完整新版本，保留旧版本；切换稳定 app 路径并重启 8000，
验证正常并写入升级终态后，再重启 9000。旧 9000 的 `sys.executable` 指向旧的
真实版本目录，因此完整旧版本必须保留到进程退出。**不能原地覆盖运行库，
不能在旧 9000 存活时清理它的版本目录。**部署器和 OTA/回滚要实现同样的版本
切换协议后，才能将保护模式接入现有自动升级；当前未承诺这一迁移已完成。

## 验证

开发机离线验证（无设备服务、网络和数据库访问）：

```bash
python3 -m unittest discover -s deploy -p 'test_*.py'
```

覆盖：构建副本语法、源码未改动、入口白名单/参数/退出码、HTTPS 配置解析、
本地升级状态查询、身份轮换帮助、点定义快照、Shell 调用适配、泄漏检查和
本地真实 C 入口桥接。这些测试不替代 Nuitka 实际编译。

目标设备还需验证完整 Standalone 无源码启动、登录/Session/CSRF/Socket.IO、
MySQL、Modbus、证书工具、HTTPS 独立服务、停主服务后的 9000 查询，以及
接入版本化部署后的升级/失败回滚。构建成功也不能代替这些实机验证。

Nuitka 提高 Python 逆向成本，不能保证不可逆向，硬编码口令仍可能被提取。
Shell 不进行混淆，其脚本正文和保留的内联代码可直接阅读。
官方说明：[Nuitka 手册](https://nuitka.net/user-documentation/user-manual.html)。
