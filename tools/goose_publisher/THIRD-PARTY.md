# 第三方组件

Windows 构建使用 Python/Tcl/Tk、cryptography、pyOpenSSL、Scapy 及 PyInstaller。保留发行物内随依赖附带的许可证与版权信息；对应版本以 Windows 构建环境实际安装结果为准。PyInstaller 构建脚本收集运行库及主要依赖元数据。

- Python：https://www.python.org/ （PSF 许可；Tcl/Tk 附带自己的许可）
- cryptography：https://github.com/pyca/cryptography （Apache-2.0 或 BSD-3-Clause；附带 OpenSSL 等依赖许可）
- pyOpenSSL：https://github.com/pyca/pyopenssl （Apache-2.0）
- Scapy：https://github.com/secdev/scapy （GPL-2.0-only；源码及许可可从对应发行版获取）
- PyInstaller：https://pyinstaller.org/ （构建工具许可附带 bootloader 分发例外）

Npcap 是单独安装的网卡驱动，本构建包不包含 Npcap 安装程序或驱动文件。使用和再分发条款以 [Npcap 官方许可](https://npcap.com/#license) 为准。软件界面提供官方下载链接，不进行静默下载安装。
