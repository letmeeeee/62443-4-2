# 手动验证：主动发起 Modbus 的主机必须证明身份

工具 `modbus_tls_peer.py` 可当主机，也可当模拟从机，需 Python 3.8+，无第三方 Python 依赖。以下命令在仓库根目录运行。

流程：主机建立 TCP → TLS 握手时出示证书并证明持有对应私钥 → 从机检查是否信任、是否过期、用途是否正确 → 通过后才处理 Modbus。

与当前项目一致：只验证主动方（主机）的身份；主机不验证从机证书。TLS 建立后输出协议版本和加密算法；主机还需收到正确 Modbus 响应才显示读取成功，不能只凭 TCP 连接成功或客户端握手返回判断认证成功。

## 先在电脑上看懂正常和拒绝过程

首次生成三组独立测试身份，目录已存在身份时生成命令会拒绝覆盖。这里只为本机演示而在同一电脑生成，实际设备各自保管自己的私钥。

```sh
python3 logger/scripts/modbus_certs.py --dir /tmp/modbus-demo-master generate --role master --name demo-master
python3 logger/scripts/modbus_certs.py --dir /tmp/modbus-demo-slave generate --role slave --name demo-slave
python3 logger/scripts/modbus_certs.py --dir /tmp/modbus-demo-slave trust-add --cert /tmp/modbus-demo-master/master.crt
python3 logger/scripts/modbus_certs.py --dir /tmp/modbus-demo-stranger generate --role master --name stranger
```

终端 A，启动从机（持续接受连接，Ctrl+C 退出）：

```sh
python3 logger/scripts/modbus_tls_peer.py slave --cert-dir /tmp/modbus-demo-slave
```

终端 B，依次运行三个对照：

```sh
# 1. 可信主机：应读取成功，寄存器值为 {10: 10, 11: 11}
python3 logger/scripts/modbus_tls_peer.py master --cert-dir /tmp/modbus-demo-master --address 10 --count 2

# 2. 不带证书：应失败，终端 A 不应处理 Modbus 请求
python3 logger/scripts/modbus_tls_peer.py master --no-cert

# 3. 有证书但从机没有信任：应失败，终端 A 不应处理 Modbus 请求
python3 logger/scripts/modbus_tls_peer.py master --cert-dir /tmp/modbus-demo-stranger
```

成功命令退出码 0，失败为 1。不同 OpenSSL 版本的拒绝文字可能不同。单纯超时、断网或端口错误不能证明身份校验正常：应先确认第 1 项成功，再结合从机证书错误日志判断第 2、3 项。

模拟从机支持功能码 03/04，寄存器值等于协议地址，其他功能码返回异常；不模拟 PCS/BMS 的完整业务，不处理写寄存器。只把它用于测试配置。

## 验证实际项目作为从机

电脑运行工具主机 → 设备上实际 `tems` 从机。这才是在验证项目入口，而不是两个 Python 工具之间的演示。

1. 设备的 TLS 编译开关为 1，已配置 `slave.crt`、`slave.key`。
2. 将电脑 `/tmp/modbus-demo-master/master.crt` 的**公开证书**通过可信渠道复制到设备；在设备用 `modbus_certs.py trust-add --cert 路径` 导入到实际证书目录，重启 `tems`。不复制主机私钥。
3. 运行下面命令，将 IP、端口、站号和寄存器地址换成设备真实配置。端口来自 `localEmsPort`；地址为协议零起始地址，不是 40001 表示法。

```sh
python3 logger/scripts/modbus_tls_peer.py master --host 192.168.1.100 --port 802 --cert-dir /tmp/modbus-demo-master --unit 1 --function 3 --address 0 --count 1
python3 logger/scripts/modbus_tls_peer.py master --host 192.168.1.100 --port 802 --no-cert
python3 logger/scripts/modbus_tls_peer.py master --host 192.168.1.100 --port 802 --cert-dir /tmp/modbus-demo-stranger
```

预期：可信证书读取成功；无证书和陌生证书被拒绝。若可信主机收到 Modbus 异常码，说明已经能交换 TLS 内的 Modbus 数据，但应调整寄存器参数再完成正常读取验证。既有网络白名单也需允许测试电脑连接。

## 验证实际项目作为主机

设备上实际 `tems` 主机 → 电脑模拟从机。

将设备的 `master.crt` **公开证书**复制到电脑，例如 `/tmp/device-master.crt`，导入模拟从机后重新启动工具：

```sh
python3 logger/scripts/modbus_certs.py --dir /tmp/modbus-demo-slave trust-add --cert /tmp/device-master.crt
python3 logger/scripts/modbus_tls_peer.py slave --bind 192.168.1.50 --port 18020 --cert-dir /tmp/modbus-demo-slave
```

`--bind` 改为电脑网卡 IP。在测试设备的相应 Modbus 目标配置中，把远端 IP/端口指向电脑。收到连接时应显示“主机身份验证通过”、证书主体、SHA256 指纹及 Modbus 请求。模拟值不代表真实设备数据。

反例：用另一个只信任演示主机、未导入设备证书的从机证书目录启动工具，设备连接应被拒绝。此步骤需要手动修改测试设备配置；工具不会修改设备、部署或重启服务。

## 验证边界

项目原生 C 传输层与此工具的认证交互、工具主从读取及负例已纳入 `logger/tests/test_modbus_transport.py`。本机测试不等于实机验证。工具显示 TLS 版本和 cipher 可确认协商加密通道；如需线缆侧证据，可在测试网络抓取对应 TCP 端口，查看 TLS 握手和加密 Application Data，而不是可直接解码的明文 Modbus 请求。
