# Windows GUI 与安装包

## 构建机

在 Windows 10/11 x64 安装 Python 3.12 x64（包含 Tcl/Tk、pip）和 Inno Setup 6。Linux 的 PyInstaller 不能直接生成 Windows EXE，需要在 Windows 完成构建。

解压 `GoosePublisher-Windows-buildkit.zip`，双击：

```text
tools\goose_publisher\build_windows.bat       → dist\GoosePublisher.exe
tools\goose_publisher\build_installer.bat     → dist\GoosePublisher-Setup-2026.11.18.exe
```

首次构建需联网下载 Python 依赖；脚本使用独立 `.venv-windows`。也可指定 Python：

```bat
build_installer.bat "C:\Users\yourname\AppData\Local\Programs\Python\Python312\python.exe"
```

Inno Setup 不在默认位置时，设置 `ISCC_EXE` 为 `ISCC.exe` 完整路径。安装包包含 Python/Tk、密码库和网卡调用库；目标 PC 不必安装 Python 或 OpenSSL 命令行。PKI 不会进入 EXE 或安装包，测试人员在界面单独选择。

## 目标测试 PC

1. 从 [Npcap 官网](https://npcap.com/#download) 安装 Npcap，按官方说明完成驱动安装。当前工具使用 Npcap 的标准以太网注入能力，不要求无线网卡原始 802.11 模式。
2. 运行 Setup 安装本工具，或直接运行便携 `GoosePublisher.exe`。EXE 请求管理员权限，以兼容限制管理员访问的 Npcap 配置。
3. 使用 PC 真实有线网卡连接设备 net2 所在的二层网络。相比 Ubuntu 虚拟机，直接使用 Windows 物理网卡可以排除虚拟机桥接造成的组播问题。
4. 界面刷新并选择本机网卡，列表显示名称、IPv4 和 MAC。填写设备 net2 IP，例如 `192.168.2.136`。这里不填写 Linux 的 `ens33` 或设备的 `net2`。
5. “选择 PKI 目录”加载发布端自己的 `enc.crt`、`enc.key`、`ca-roots.crt`、`crls.pem`。私钥为未加密 P-256 PKCS#8，与订阅端身份分开。点击“校验本端 PKI”。
6. 选择模式、数量、间隔及 8 个整数，点击“开始测试”。默认数据全零，同样可能触发业务写入，请只在隔离联调环境发送。需要连续业务转发时勾选“每帧递增 stNum”。
7. GUI 日志分别显示本端校验、等待 ACK、ACK 认证和发送进度；“保存日志”只保存界面诊断，不输出私钥或会话密钥。“停止”结束发送，关闭窗口时会等待当前操作停止。

设备必须放行 **UDP 30001**，TCP 30001 不能替代。UDP 握手和二层 EtherType `0x88b8` 发包使用同一选定网卡。独立运行之间停止旧发布端并空闲超过 30 秒，或经确认后重启设备服务。

正常、重放、篡改、明文、错误 HELLO 签名的含义见 README。界面显示“已发送”仅代表提交发包；是否收到和解密仍需对照设备的 `GOOSE authenticated`、拒绝日志和抓包。

## 排错

- 没有网卡或提示 Npcap 缺失：确认驱动安装成功并重启工具，以管理员身份运行。可使用同一 PC 的 Wireshark 检查该网卡能否抓包。
- 刷新网卡会打印 Npcap 状态、枚举数量及各网卡的 IPv4/MAC/排除原因。列表不再通过 Scapy 的 UP 标记预先过滤。若无可选地址，请保存窗口日志，并在 Windows PowerShell 查看 `Get-NetAdapter`、`Get-NetIPAddress -AddressFamily IPv4` 和 `Get-Service npcap`，区分驱动、系统网卡配置与程序枚举问题。
- ACK 超时：检查目标 IP、UDP 30001、防火墙、设备运行日志和旧会话空闲时间。
- ACK 成功、设备无业务帧：在 Windows Wireshark 与设备 tcpdump 同时检查 `eth.type == 0x88b8` / `ether proto 0x88b8`，排查交换机组播转发。
- PKI 错误：核对 P-256 设备身份、未加密私钥格式、双方信任根、CRL 有效期和系统时间。不提供跳过认证选项。

当前仓库在 Linux 验证共享密码协议、内置证书校验和 GUI/发送流程；Windows Npcap 驱动交互、EXE 与 Setup 安装需要 Windows 构建和实机验证。

官方参考：[Scapy Windows 安装](https://scapy.readthedocs.io/en/latest/installation.html)、[Npcap 安装说明](https://npcap.com/guide/npcap-users-guide.html)、[pyOpenSSL 证书与 CRL 校验](https://www.pyopenssl.org/en/stable/api/crypto.html)。
