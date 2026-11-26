# PyArmor 快速混淆设备端 Python

适用于当前 `exec/app` 的 8000、9000、证书工具及其他 Python 模块。
独立入口是 `deploy/build_pyarmor.py`，不覆盖现有 Nuitka 构建器。
Python 只混淆，不构建独立可执行文件，不编译整个依赖树；设备继续需要
CPython 和原有 requirements 依赖。Shell 不混淆，其内联 Python 也保留明文。

## 在现有容器中使用

使用与设备相同的 CPython 主次版本。你此前的日志显示容器为 Python 3.13，
只有设备实际也使用兼容的 CPython 3.13 时，才用该环境混淆。
ARM64 运行库使用 `linux.aarch64`；glibc Linux 不要选择 Alpine/musl 运行库。

```bash
cd /workspace
source /tmp/ems-build-venv/bin/activate
python -m pip install 'pyarmor>=9,<10'
pyarmor --version
python --version
```

PyArmor 9 的支持矩阵包含 Python 3.13、Linux aarch64；具体 runtime 仍需实测。
试用版不能处理大脚本，本项目含大型常量与路由模块，可能报 `out of license`
或大脚本限制。遇到这些限制，使用正式授权，不跳过文件或保留其明文来凑包。
容器重建与构建机器计数、联网校验及离线构建能力按许可证类型确认；构建器
不会自动注册、购买许可证，也不会把注册文件放进产物。

先生成计划，无需安装 PyArmor：

```bash
python deploy/build_pyarmor.py --plan --output /tmp/ems-pyarmor-plan
```

正式混淆：

```bash
python deploy/build_pyarmor.py \
  --platform linux.aarch64 \
  --output deploy/build-output/pyarmor-v001
```

输出目录必须是新目录。程序打印文件数量、实际命令和输出位置。
基础模式不启用 BCC/JIT、RFT、private/restrict、设备绑定或到期限制。
命令隔离全局/本地配置路径，保留默认注册信息来源，避免继承已有高级模式设置。
runtime 尚未缓存时，首次运行可能需要下载相应平台组件。

### 出现 `out of license`

这是授权能力检查失败，大脚本是官方列出的常见原因，不能直接解释为许可证
过期。当前 `utils/method.py` 约 2348 行，若前面的小文件成功、在该模块失败，
应先核对试用版的大脚本限制及当前容器的注册状态；行数不是官方限制阈值。

在**执行构建的同一容器、同一用户及环境**运行：

```bash
/tmp/ems-build-venv/bin/pyarmor --version
# 已有适用授权时，用自己的注册文件路径执行，勿上传或提交注册文件：
/tmp/ems-build-venv/bin/pyarmor reg /secure/path/pyarmor-regfile-xxxx.zip
```

注册和容器构建次数遵循对应许可。确认具备大脚本授权后，使用新输出目录重试，
例如 `--output deploy/build-output/pyarmor-v002`。只需反馈版本及授权类型、是否
显示 trial，不必粘贴注册编号、激活码或注册文件。

构建器将完整诊断保存为 `pyarmor.log`，非零退出同时写入 `build-failure.json`，
然后停止。`work/generated` 中的部分结果不能发布；不会跳过失败模块、回退明文
或拆分模块来规避试用限制。此报错不通过更换 Python 版本或增加编译资源解决。

也可以在 x86_64 Linux 上用与设备相同主次版本的 Python，指定
`--platform linux.aarch64` 交叉生成；它不需要 ARM64 C 编译器，最终 runtime
必须去 ARM64 环境验证。仅测试本机 x86 输出时可用 `--platform linux.x86_64`。

## 产物和启动方式

```text
pyarmor-v001/
├── build-plan.json
├── ems-pyarmor-app.tar.gz
├── release/
│   ├── manifest.json
│   └── app/
│       ├── main.py                     # 混淆后的 Python 入口
│       ├── pyarmor_runtime_xxxxxx/     # 本次构建生成的 runtime
│       ├── upgrade/upgrade.py
│       ├── upgrade/pyarmor_runtime_xxxxxx/
│       ├── script/*.py
│       ├── script/*.sh                 # 可读脚本
│       └── script/pyarmor_runtime_xxxxxx/
└── work/                              # 明文构建副本，绝不能部署
```

runtime 复制到每个 Python 文件目录，避免直接运行 9000/证书脚本时，在脚本
尚未执行 sys.path 初始化之前就找不到 runtime。全部副本来自同一次混淆，
必须随对应 Python 文件一起更新，不能混用不同版本 runtime。

继续使用原来的 Python 启动方式，例如：

```bash
/home/zlg/myenv/bin/python /home/zlg/app/main.py
/home/zlg/myenv/bin/python /home/zlg/app/upgrade/upgrade.py
/home/zlg/myenv/bin/python /home/zlg/app/script/watch_upgrade_status.py task001 --once
```

`sys.executable` 继续是 Python，原有证书子进程调用无需改成 Nuitka 入口。
设备不需要安装 PyArmor 命令行或构建许可证，只需要匹配的 runtime、Python
和业务依赖。前端、原生辅助工具、设备配置、证书及业务状态需要独立保留，
这个包不替代完整运行目录或整机备份。

## 项目专用适配

业务源码不改动，只在构建副本中处理以下三个位置：

- `upgrade.sh`：不再 cat 混淆脚本后用 `python3 -c` 执行，改为在替换 app 前
  保存数据库工具文件和 runtime，随后用原 Python 执行临时文件；退出时清理。
- `enable_https.sh`：独立复制证书工具时同时复制其 runtime，原有 Python/bash
  启动、帮助文本和脚本路径不改。
- `generate_point_labels.py`：它需要解析源码 AST，混淆后改为使用构建时提取的
  点定义快照；业务点定义变化需要重新混淆，默认 XLSX 不包含在发布包内。

身份轮换 Shell 的内联 Python 保持原样；基础混淆模式允许其调用混淆后的
PKI 模块，不启用 private/restrict。其余普通模块的 `__file__`、`__main__`、
相对目录结构和导入逻辑保持原样。

## 验证和部署边界

构建器检查原 `.py` 文件均有 PyArmor bootstrap 和加密载荷、runtime 存在且
为目标架构，Shell 保持可读和可执行。输出签名形态检查不等于不可逆向证明。
在同架构环境构建时，只运行本地状态查询工具的 `--help` 作为冒烟检查，
不导入完整主服务、连接数据库、启动端口或执行升级。

只发布 `release` 或压缩包，不能发布 `work`。不要直接使用旧 `deploy/install.py`：
它的白名单目前拒绝 runtime `.so`。本次没有修改该安装器或自动接入 OTA。
9000 在升级期间仍要保持存活，旧 Python 进程退出前保留旧代码/runtime；
发布及回滚需要把同一批脚本和运行库作为整体保留和切换。

先在设备测试登录/Session/Socket.IO、数据库、Modbus、证书/HTTPS 独立服务、
停止 8000 后的 9000 查询，以及升级/失败回滚。混淆不能保证完全无法逆向，
不能把源码中的硬编码口令变成安全密钥。

官方资料：
[命令行](https://pyarmor.readthedocs.io/en/latest/reference/man.html)、
[平台与 Python 支持](https://pyarmor.readthedocs.io/en/latest/reference/environments.html)、
[授权与试用限制](https://pyarmor.readthedocs.io/en/latest/licenses.html)。
