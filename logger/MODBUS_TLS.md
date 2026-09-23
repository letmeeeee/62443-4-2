# Modbus TCP 编译开关

想手动观察“主机证明身份 → 从机允许/拒绝通信”，请先看 [主机/从机手动验证教程](scripts/MODBUS_TLS_PEER.md)。工具支持与实际 `tems` 对接，并提供可信证书、无证书、陌生证书三个对照操作。

开关在 `lib/modbus_transport.h`：

```c
#ifndef MODBUS_TLS_ENABLED
#define MODBUS_TLS_ENABLED 1
#endif
```

- `0`：本程序作为主机、从机均使用普通 Modbus TCP，不加载证书。
- `1`（当前设置）：双方使用 TLS 1.2 或更高版本，拒绝 TLS 1.1 及以下版本。本程序作为从机，强制校验主机客户端证书；作为主机，在对端请求时出示客户端证书，不校验从机服务端证书。
- 对端也必须使用匹配模式。TLS 失败不会回退明文。

修改宏后重新编译并重启 `tems`。也可通过编译参数 `-DMODBUS_TLS_ENABLED=1` 覆盖默认值；必须对整个目标使用同一个定义。

本次范围为 `logger`：EMS 从机、PCS/BMS/DIDO/CEM9000/以太网测控主机及其 Modbus TCP 心跳写入。HTTP、P2P 和串口 RTU 不使用这个 TLS 传输层。`lc_data` 目录中的另一套历史实现未修改。`ISPLANT_V` 将 COM 函数切换到 RTU，不能与本 Modbus TCP TLS 模式组合使用。

## 证书

| 角色 | 默认文件 | 用途 |
|---|---|---|
| 从机 | `/etc/ems/modbus/slave.crt` | 本机直接自签服务端证书，允许 serverAuth |
| 从机 | `/etc/ems/modbus/slave.key` | 服务端私钥 |
| 从机 | `/etc/ems/modbus/master-ca.crt` | 信任的对端主机自签证书集合（PEM） |
| 主机 | `/etc/ems/modbus/master.crt` | 本机直接自签客户端证书，允许 clientAuth |
| 主机 | `/etc/ems/modbus/master.key` | 客户端私钥 |

文件路径可通过同一头文件中的 `MODBUS_TLS_*` 宏调整。私钥只保存在所属设备，不能发送给对端；TLS 握手发送证书并证明私钥持有权。服务端仍须配置自己的证书/私钥，但主机不验证它。该模式不能声称主机已确认从机身份，也不是要求双向认证的完整 Modbus Security 配置。

证书初始化失败会记录错误：从机不启动监听，主机拒绝建立 TLS 通道。更换证书后重启进程；初始化结果按角色缓存，不提供热更新。证书有效期依赖设备时间，握手前应保证 RTC/系统时间正确。直接自签模式下，本实现通过预先导入的信任证书、有效期和客户端用途验证，不包含 CRL/OCSP、逐设备身份白名单或寄存器授权。

端口继续使用原有 INI 设置（`localEmsPort`、各设备远端端口），宏不自动修改端口。部署双方应约定相同端口；可配置为 802。不要让普通 Modbus 客户端访问 TLS 端口。

## 实现

- `lib/modbus_transport.c`：编译分支、角色证书配置、每连接 SSL、握手截止时间、TLS 收发、清理。
- `tcp_server/modbus_tcp_server.c`：工作线程先验证主机，再执行寄存器业务；所有回复走传输层；握手中连接也计入并发上限。
- `lib/tcp_socket.c`：`Create_Modbus_Client_Socket()` 在 TCP 连接后执行客户端握手；Modbus 接收函数不再自行关闭 fd，由连接拥有者关闭一次。
- `lib/modbus_protocol.c`：TCP 请求统一走 `Modbus_Send()`；RTU 请求仍走串口写入。
- 各设备模块：使用 Modbus 专用建连、关闭接口，关闭后将 fd 置为 -1。

TLS 模式按 MBAP 的两字节长度收齐完整 ADU，支持拆包和连续多帧；调用超时保留未完成报文。握手默认 5 秒，不完整 ADU 默认 3 秒，均使用单调时钟。SSL 对象按连接加锁，不在全局锁内阻塞收发。不可恢复错误和未完成发送导致连接失效，不继续发送新的请求。

## 构建与验证

原工程链接 AArch64 `libssl.so.1.1`、`libcrypto.so.1.1`。TLS 模式需要配套的目标 OpenSSL 1.1 开发头文件，包括 `openssl/opensslconf.h`，不能混用 OpenSSL 3.x 或其他架构的配置头文件。

推荐通过总 Makefile 一次完成头文件准备、CMake 配置和编译：

```sh
make --no-print-directory -C logger -j4
```

产物为 `logger/build/tems`。首次构建按需下载头文件，后续构建校验并复用缓存，不会重复下载。源文件、工具链和链接规则只维护在 `CMakeLists.txt`；`base/Makefile` 仅转发到总 Makefile，不再执行旧 ARM32 编译或 NFS 部署。`cmake.sh` 保留原有行为，不作为此统一构建入口。

```sh
# 自定义构建目录
make --no-print-directory -C logger -j4 BUILD_DIR=/tmp/ems-build-tls

# 离线开发包（绝对路径）
make --no-print-directory -C logger -j4 OPENSSL_DEB=/path/to/libssl-dev_1.1.1f-1ubuntu2.24_arm64.deb

# 使用已有目标 SDK，跳过自动下载
make --no-print-directory -C logger -j4 OPENSSL_INCLUDE_DIR=/path/to/target-openssl-1.1/include

# 编译参数覆盖示例：关闭 TLS
make --no-print-directory -C logger -j4 CMAKE_ARGS=-DCMAKE_C_FLAGS=-DMODBUS_TLS_ENABLED=0

# 清理编译产物，保留头文件缓存；不会下载依赖
make --no-print-directory -C logger clean
```

也可以手动执行以下步骤（不安装系统软件包、不替换运行库）：

```sh
sh logger/scripts/prepare_openssl_headers.sh
cmake -S logger -B /tmp/ems-build-tls -DCMAKE_C_FLAGS=-DMODBUS_TLS_ENABLED=1
cmake --build /tmp/ems-build-tls -j4
```

准备脚本下载 Ubuntu 官方 `libssl-dev_1.1.1f-1ubuntu2.24_arm64.deb`，校验固定 SHA-256 和包架构，只将公共头文件及 ARM64 `opensslconf.h` 提取到 `logger/.deps/openssl-arm64/include`。CMake 自动优先使用该目录。`.deps` 是忽略提交的本地依赖缓存，新工作区需要重新执行准备脚本。脚本重复执行会校验已有头文件，不重复下载。

离线机器可先传入相同软件包：

```sh
sh logger/scripts/prepare_openssl_headers.sh --deb /path/to/libssl-dev_1.1.1f-1ubuntu2.24_arm64.deb
```

已有完整目标 SDK 时，可通过 `-DMODBUS_OPENSSL_INCLUDE_DIR=/path/to/target-openssl-1.1/include` 覆盖自动目录。该目录必须同时包含 `openssl/ssl.h` 和目标架构的 `openssl/opensslconf.h`。不要通过添加 `/usr/include/x86_64-linux-gnu` 修复 ARM64 编译：那是主机架构的配置头文件。CMake 在 TLS 开启时会提前验证头文件是否可编译且版本为 1.1.1；关闭 TLS 不要求这些头文件。

本机独立传输层测试，不运行设备控制/数据库业务：

```sh
python3 logger/tests/test_modbus_transport.py
```

测试临时生成证书，覆盖 TLS 1.2/1.3、主从双方拒绝 TLS 1.1、证书拒绝、主机出示证书且不校验从机、拆包/连续帧、无效 MBAP 长度、握手/半帧超时，以及无证书情况下关闭宏的主从明文收发。测试需 C 编译器、OpenSSL 开发库、Python 和本机回环 socket 权限。

## 直接自签证书管理脚本

脚本：`logger/scripts/modbus_certs.py`，依赖 Python 3.8+ 与 OpenSSL 1.1.1+，不依赖 Python 第三方包。以下命令从仓库根目录执行。默认目录 `/etc/ems/modbus`；如编译宏使用其他路径，可用 `--dir /your/directory` 指定目录（放在子命令前）。用有目录写权限的账号执行，不会自动提权或重启服务。

### 首次配置

在主机本机生成身份并导出**公开证书**：

```sh
python3 logger/scripts/modbus_certs.py generate --role master --name master-001
python3 logger/scripts/modbus_certs.py check --role master
python3 logger/scripts/modbus_certs.py export --role master --out /tmp/master-001.crt
```

通过可信渠道把 `/tmp/master-001.crt` 传给从机，并核对脚本输出的 SHA-256 指纹。主机私钥不离开主机。

在从机本机生成身份，导入对端主机证书：

```sh
python3 logger/scripts/modbus_certs.py generate --role slave --name slave-001 --ip 192.168.1.100
python3 logger/scripts/modbus_certs.py trust-add --cert /tmp/master-001.crt
python3 logger/scripts/modbus_certs.py check --role slave
python3 logger/scripts/modbus_certs.py trust-list
```

`--ip` 改为实际从机 IP，也可省略或用 `--dns ems.example`，两者可重复。`--days` 默认 365，允许 1～3650 天。设备名称应唯一。同一设备承担两种角色时分别生成两套身份；本机作为从机时导入的是**上级主机**证书，本机 `master.crt` 则交给下级从机信任。脚本不会自动信任本机主机证书。

导入时可加 `--fingerprint 完整SHA256指纹` 强制比对。`trust-add` 每次导入一个主机证书，多次调用组成 `master-ca.crt` 信任集合；重复证书不重复添加。这个文件名为兼容现有代码保留，内容不是另建的 CA。

### 日常管理与换证

```sh
# 查看主体、签发者、有效期及指纹（不显示私钥）
python3 logger/scripts/modbus_certs.py show --role master

# 检查自签名、有效期、角色用途、证书/私钥匹配和私钥权限
python3 logger/scripts/modbus_certs.py check --role master

# 备份旧身份并生成新私钥和证书，IP/DNS 需重新显式传入
python3 logger/scripts/modbus_certs.py renew --role master --name master-001 --days 365

# 从机删除指定可信主机证书
python3 logger/scripts/modbus_certs.py trust-remove --fingerprint 完整SHA256指纹
```

`generate` 拒绝覆盖已有身份；`renew` 自动将旧证书和私钥保存到 `backups/时间-随机编号/`。信任文件修改前也自动备份。证书和私钥以 600 权限保存，默认新目录为 700，运行 `tems` 的账号必须能读取。备份含私钥，应按私钥保护。

换证前停止相关 `tems` 进程，避免进程在两份身份文件替换期间启动读取；脚本对单文件原子替换、命令间加锁，但不提供证书与私钥两文件的跨崩溃原子事务。主机换证后，先将新公开证书导入从机（可暂时保留旧证书），重启从机使新信任生效，再启动使用新证书的主机；确认通信后删除旧信任并再次重启从机。删除最后一个信任证书会生成空信任文件，当前 TLS 实现重启后不会启动从机监听，必须先导入新的可信证书。

生成的证书设为 `CA:FALSE`，按角色设置 `clientAuth` / `serverAuth`。为兼容项目 OpenSSL 1.1.1 对直接自签叶证书的信任验证，生成器不添加 Key Usage 扩展，也不会赋予设备 `keyCertSign`；使用 EKU 限定 TLS 用途。导入时实际调用 OpenSSL 验证自签名、有效期和用途，不能通过当前验证规则的外部证书会被拒绝。

所有示例只在执行所在设备生成本机私钥，不创建 CA、不自动发送证书、不调整 TLS 宏、不自动部署或重启。

测试：

```sh
python3 logger/tests/test_modbus_certs.py
python3 logger/tests/test_modbus_transport.py
```

第一组测试不需要网络；第二组使用本机回环 socket，并包含脚本生成的直接自签证书与当前 C 传输层的真实握手测试。
