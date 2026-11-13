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

此 EXE 内含 Python、Tkinter、TLS 和证书生成依赖，运行电脑无需另装 Python 或 OpenSSL。同一个 EXE 包含客户端和服务端，可直接双击运行。支持单角色CSR交接、企业CA签发包导入及隔离测试证书生成、证书导入/导出、TLS 验证开关、完整 TX/RX 日志、复制和循环发送功能。

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

在 Windows 上运行 EXE，生成证书，用同一窗口启动本机服务端并从客户端读写，检查循环停止、TX/RX 日志和复制；再在没有安装 Python/OpenSSL 的目标电脑运行同一个 EXE。企业CA单角色签发与双向 TLS 功能已有 Linux 回环测试，Windows EXE 需通过这些检查后再分发。

## 安装包构建（2026-11-06）

安装包构建包含当前企业CA单角色CSR/导入、循环TLS长连接和正常关闭修正。在Windows上安装Python 3.12 x64（含Tcl/Tk、pip）和Inno Setup 6，然后双击 `build_installer.bat`。首次需要网络安装Python依赖；脚本先生成便携EXE，再编译 `ModbusTLS.iss`。成功输出：

```text
tools\modbus_gui\dist\ModbusTLS-Setup-2026.11.06.exe
```

可以将 `ISCC_EXE` 设置为Inno Setup编译器完整路径，Python路径仍可作为脚本第一个参数传入。只需便携程序时继续使用build_windows.bat。

安装程序按当前用户安装到 `%LOCALAPPDATA%\Programs\ModbusTLS`，无需管理员权限，创建开始菜单快捷方式，可选桌面快捷方式。程序包仅含EXE和公开说明，不携带用户私钥、证书或CA数据；用户生成的身份目录应放在自己的数据目录，不放在安装目录。卸载不自动擦除外部身份数据。

当前构建机是Linux，尚未在Windows执行此安装脚本或验证最终安装程序。Windows交付前请检查安装/启动/卸载、单角色CSR及CA导入、双向TLS、循环连接复用、停止清理和防火墙入站提示；不要将构建源码ZIP当作已生成的安装EXE。
