# Windows EXE 打包与使用

## 一键打包

在 Windows 10/11 x64 电脑安装 python.org 的 Python 3.12 x64，保留 Tcl/Tk 和 Python Launcher 选项。首次构建需要联网下载依赖。

解压打包源码包，双击 `tools\modbus_gui\build_windows.bat`。也可从完整仓库内双击同一文件。脚本会创建独立的 `.venv-windows`，安装 PyInstaller 与 cryptography，生成：

```text
tools\modbus_gui\dist\ModbusTLS.exe
```

脚本会依次检测已有构建环境、`py -3.12`、`py -3`、`python`、`python3` 与常见安装目录，不要求必须有 `py` 启动器。没有找到可用环境时，可在提示中粘贴现有 `python.exe` 的完整路径，或通过命令指定：

```bat
build_windows.bat "C:\Users\你的用户名\AppData\Local\Programs\Python\Python312\python.exe"
```

也可设置环境变量 `MODBUS_PYTHON_EXE` 指向解释器。需 Python 3.10+ 且包含 Tcl/Tk、venv、pip；推荐安装 Python 3.12 x64。如果仅看到安装 Python 的提示，意味着构建尚未开始，按任意键只会关闭旧脚本，不会安装 Python 或生成 EXE。依赖安装日志保存在 `build-windows-pip.log`，只有构建命令成功且确认 EXE 存在才显示 Success。

此 EXE 内含 Python、Tkinter、TLS 和证书生成依赖，运行电脑无需另装 Python 或 OpenSSL。同一个 EXE 包含客户端和服务端，可直接双击运行。保留自签/CA 证书生成、证书导入/导出、TLS 验证开关、完整 TX/RX 日志、复制和循环发送功能。

[PyInstaller 官方说明](https://github.com/pyinstaller/pyinstaller/blob/develop/README.rst)要求在目标操作系统上运行，因此 Linux 上的 Python 不能直接生成此 Windows EXE。当前提供的是构建源码包；最终 EXE 必须在 Windows 完成构建和验证。

## 使用

- 双击 `ModbusTLS.exe`，在页签中选择客户端或服务端。
- 可通过 `ModbusTLS.exe --role server` 默认打开服务端页。
- 客户端填写 Windows 电脑可达的设备 IP/端口；设备连接 GUI 服务端时，监听可填 `0.0.0.0`，设备连接目标填写 Windows 电脑实际 IP。
- Windows 防火墙询问入站权限时，允许需要使用的网络；或为监听 TCP 端口添加入站规则。
- 证书由使用者选择目录保存，建议使用当前用户可写的文档目录。不会打包、携带或自动复用仓库中的 `keys`、已有证书或私钥。
- 循环时间间隔为毫秒；日志使用 Windows 本机时间，含完整日期与毫秒。

## 诊断构建

在构建完成的目录中执行，生成带控制台的 EXE，便于查看启动错误：

```bat
.venv-windows\Scripts\python.exe build_windows.py --console
```

## 构建后检查

在 Windows 上运行 EXE，生成证书，用同一窗口启动本机服务端并从客户端读写，检查循环停止、TX/RX 日志和复制；再在没有安装 Python/OpenSSL 的目标电脑运行同一个 EXE。设备自签证书兼容性与 TLS 功能已有 Linux 回环测试，Windows EXE 需通过这些检查后再分发。
