# 在 x86 主机生成设备用 .pyc

`build_pyc.py` 用标准库 `py_compile` 编译 `exec/app` 设备运行代码，Shell 保持
明文。不调用 Nuitka、PyArmor、C 编译器或 ARM64 仿真器，不导入设备服务。
这只是无源码分发，不是加密或强混淆；字节码仍能反汇编/反编译，字符串、SQL、
硬编码口令仍可能被提取。已有 Nuitka/PyArmor 构建器保持独立。

## 先获取设备 Python 信息

必须用 **systemd 服务实际使用的 Python** 检查，不默认等同于系统 python3。
在设备上执行，例如：

```bash
/home/zlg/myenv/bin/python -c 'import sys,importlib.util; print(sys.implementation.name); print(sys.version); print(importlib.util.MAGIC_NUMBER.hex())'
```

构建环境要使用相同的 CPython 主次版本，并匹配字节码 magic；推荐连补丁版本
也保持一致。CPU 架构可以不同，例如 x86_64 CPython 3.13 生成的纯 Python
字节码可在格式匹配的 ARM64 CPython 3.13 上运行。
构建器不会跨版本转换字节码；用本机 Python 3.8 不能生成 Python 3.13 字节码。
PyPy、自由线程等不同解释器/构建变体不能仅凭版本号假设兼容，应实际验证。

## 使用已有 x86 Python

设备为 CPython 3.13 时，项目根目录执行：

```bash
python3.13 deploy/build_pyc.py \
  --target-python 3.13 \
  --output deploy/build-output/pyc-v001
```

建议同时提供设备刚才输出的 magic，例如追加 `--target-magic <8位十六进制值>`。
如果 Python 版本或 magic 不匹配，构建会在创建输出目录前停止。
不需要安装业务 requirements 来生成字节码，构建只使用标准库；依赖仍需在
ARM64 运行设备上正确安装，不能把 x86 的虚拟环境、NumPy/cryptography 等
原生扩展复制给设备。

仅生成适配计划，不实际编译：

```bash
python3 deploy/build_pyc.py --plan --target-python 3.13 --output /tmp/ems-pyc-plan
```

## 使用原生 x86 Docker（不需要 QEMU）

在 x86 Docker 主机的项目根目录执行，不在已有 ARM64 容器里执行：

```bash
# 使用 stdin 构建，无需发送仓库或历史编译产物作为 Docker context。
docker build --platform linux/amd64 \
  --build-arg PYTHON_IMAGE=python:3.13-slim \
  -t ems-pyc:3.13 - < deploy/pyc.Dockerfile

docker run --rm --platform linux/amd64 \
  --user "$(id -u):$(id -g)" \
  -v "$PWD:/workspace" \
  ems-pyc:3.13 \
  --target-python 3.13 \
  --output deploy/build-output/pyc-v001
```

正式发布应固定经过验证的镜像补丁版本/digest，并追加设备 magic。
Dockerfile 不安装编译工具、业务依赖或许可证，不将源码复制进镜像；仓库
运行时挂载，输出按主机用户 UID/GID 写入。当前不自动安装 Docker 或拉取镜像。

## 输出与执行

```text
pyc-v001/
├── build-plan.json
├── ems-pyc-app.tar.gz
├── release/
│   ├── manifest.json           # Python/magic/源文件摘要/产物摘要
│   ├── verify_pyc.py           # 公开的部署校验工具，不含业务代码
│   └── app/
│       ├── __init__.pyc
│       ├── main.pyc
│       ├── upgrade/upgrade.pyc
│       ├── script/*.pyc
│       ├── script/*.sh         # 明文、可执行
│       └── utils/*.pyc
└── work/source/app/            # 明文临时副本，绝不能部署
```

使用传统 `module.pyc` 布局，不把字节码只放进 `__pycache__`，支持删除源码后的
普通 `import`。优化级别固定为 0，保留 assert、docstring 和原业务语义。
构建器直接向 release 输出字节码，不通过删除仓库 `.py` 来生成无源码目录。

只发布 release 或其压缩包，保留设备本地配置、密钥、前端、原生工具和依赖。
在临时解压目录、安装前先验证：

```bash
/home/zlg/myenv/bin/python /path/to/ems-pyc/verify_pyc.py /path/to/ems-pyc
```

它只检查解释器/magic、清单及文件摘要，不启动服务。清单不能替代可信签名。
成功只表示字节码格式和文件完整性通过，不代表实际业务联调通过。

8000/9000 的 systemd ExecStart 需要分别改为使用原 Python 执行：

```text
/home/zlg/myenv/bin/python /home/zlg/app/main.pyc
/home/zlg/myenv/bin/python /home/zlg/app/upgrade/upgrade.pyc
```

原用户、环境变量、工作目录等配置继续保留。Shell 仍按原解释器启动。
本次不自动修改设备 unit 或重启服务。

## 构建副本适配范围

- 证书接口子进程路径改为 `modbus_certs.pyc`、`https_certificates.pyc`；
  原来的 `sys.executable` 仍是真实 Python。
- HTTPS 脚本的启动、独立复制路径及 main 文件存在性检查改为 `.pyc`。
- 升级前保存旧数据库工具的 `.pyc` 文件，再用 `python3 文件.pyc` 执行，
  避免把二进制文件交给 `cat`/`python3 -c`；正常退出时清理私有临时目录。
- 点表生成器使用编译时的点定义快照，不能扫描发布后的源码 AST；修改点定义
  后需重新构建。默认 XLSX 不包含在包内。
- 其他 Python 的模块名、`__main__`、`__file__` 层级及导入关系保持原样。
  身份轮换 Shell 的明文内联 Python 可照常导入相邻 `.pyc` 模块。

所有改动均发生在 work 构建副本，仓库业务源码保持不变。

## 尚未接入的部署流程

旧 `deploy.py`/`install.py` 按 `.py/.sh` 打包和校验，不能直接接收这个包；
旧源代码版本与 `.pyc` 版本的 OTA、回滚和服务入口迁移还需统一适配。
不能直接覆盖运行目录，也不能混放新 `.pyc` 与旧 `.py`（旧源码可能优先被导入）。
升级期间继续保留 9000 和其旧版本文件，终态写入后再切换 9000。

上线前仍需实机验证登录/Session/权限/Socket.IO、MySQL、Modbus、证书和 HTTPS
独立服务，以及主服务停止后的升级查询、升级失败回滚。

官方资料：[compileall 的 legacy 布局](https://docs.python.org/3/library/compileall.html)、
[无源码字节码加载及版本限制](https://docs.python.org/3/library/importlib.html#importlib.machinery.SourcelessFileLoader)。
