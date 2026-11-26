# 加密 GOOSE 发布端模拟器

**Windows GUI**：支持网卡选择、自动加载 PKI 目录、校验、六种测试模式、开始/停止和日志保存。
Windows EXE 与 Setup 安装包的构建、Npcap 驱动安装见 [WINDOWS.md](WINDOWS.md)。
当前 Linux 工作区可生成不含私钥的 Windows 构建源码包：

```bash
python3 tools/goose_publisher/prepare_windows.py
# 输出 tools/goose_publisher/dist/GoosePublisher-Windows-buildkit.zip
```

GUI 源码也可在 Linux 图形桌面运行（网卡注入需要对应权限，另需系统 Tkinter）：

```bash
python3 -m pip install -r tools/goose_publisher/requirements-gui.txt
sudo /path/to/venv/bin/python -m tools.goose_publisher
```

GUI 内置证书链与 CRL 校验，不调用外部 OpenSSL 命令行。下文为保留的 Linux CLI 使用方式。

入口：项目根目录 `goose_publisher.py`。用于 Linux PC 与运行 `/home/zlg/goose_middle` 的设备进行隔离联调。发布端执行 GSEC1 HELLO、验证 ACK 证书链/CRL/签名、ECDHE P-256、HKDF-SHA256 和 AES-128-GCM，然后经真实网卡发送以太网 GOOSE 帧。

合法数据可能触发现有 Modbus 写寄存器流程。请使用隔离测试网和测试设备；默认 8 个值全零也是业务数据，不能视为无副作用。模拟器不会自动连接、修改或重启目标设备。

## 1. 准备两套独立身份

在 CA Web 管理界面，用同一个 CA 签发两张 **GOOSE / P-256** 证书，例如：

| 身份 | CN 示例 | 部署位置 |
|---|---|---|
| 订阅端 | `LC400-001-goose` | 目标设备，四文件导入后 apply |
| 发布端 | `EMS-SIM-001-goose` | Linux 测试 PC，供模拟器读取 |

两端各用自己的证书与私钥，共用受信任根和适用的有效 CRL，不共用设备私钥，不向设备导入发布端的私钥。

从 CA 导出发布端完整 ZIP 包，私钥格式选择“未加密 PKCS#8”，解压到测试 PC 的独立目录，例如 `./publisher-pki/`：

```text
publisher-pki/
├── enc.crt
├── enc.key
├── ca-roots.crt
└── crls.pem
```

私钥设置 `chmod 600 publisher-pki/enc.key`。如有中间 CA，发布端 `enc.crt` 在叶证书后追加中间证书，`crls.pem` 需包含全部适用 CRL；验证订阅端所需的中间证书也可追加在 `crls.pem` 中。原始 CA Server 的直接根签发不需要中间链。

## 2. 网络和设备准备

测试 PC 的有线网口连接设备 **net2 所在的同一个二层网络**。可以经过支持该组播的交换机，不能仅凭 IP 路由跨网段测试二层 GOOSE。PC 网口与设备 net2 配置可达 IPv4 地址；示例假设：

```text
Linux PC enp3s0（192.168.2.100）
              │ 同一二层网络
设备 net2（192.168.2.200）
```

IP 为示例，不会被模拟器自动配置。将命令中的网卡和目标地址替换为现场地址。

设备上确认：

```bash
ip -br addr show net2
sudo systemctl status goose_middle.service --no-pager -l
sudo journalctl -u goose_middle.service -f
```

另一终端可以观察每日业务日志：

```bash
tail -f /mnt/nvme/goose_log/$(date +%F).log
```

握手需要 PC 到设备 UDP **30001** 可达，业务使用以太网 **0x88B8**。原有明文 GOOSE 发布器不具备 GSEC1 握手和 allData 加密能力，不能直接替代此模拟器。

## 3. 安装和正常发送

在 Linux PC 的项目根目录执行（需要 Python 3.9+、OpenSSL 命令行）：

```bash
python3.9 -m venv .venv-goose-test
.venv-goose-test/bin/python -m pip install -r tools/goose_publisher/requirements.txt

sudo .venv-goose-test/bin/python goose_publisher.py \
  --interface enp3s0 --target 192.168.2.200 \
  --cert ./publisher-pki/enc.crt --key ./publisher-pki/enc.key \
  --ca ./publisher-pki/ca-roots.crt --crl ./publisher-pki/crls.pem \
  --count 10 --interval 1 --values 0,0,0,0,0,0,0,0
```

需要 root 或等效网络权限以创建 AF_PACKET 原始套接字和绑定网卡。使用虚拟环境解释器的完整相对路径，避免 sudo 后丢失 cryptography 依赖。

模拟器参数与当前订阅端一致：APPID `0x1000`，目的 MAC `01:0c:cd:01:00:00`，goCbRef `TEMPLATEPIGO/LLN0$GO$gocb1`，8 个 MMS INTEGER；仅 allData.value 加密。

模拟器应打印：

```text
ACK 证书链/CRL/签名已验证；ECDHE/HKDF 完成。对端=...
已发送 stNum=1 sqNum=0 mode=normal ...
已发送 stNum=1 sqNum=1 mode=normal ...
```

设备应出现：

```text
GOOSE session established: ECDSA/ECDHE P-256, HKDF-SHA256, AES-128-GCM keyId=1
GOOSE authenticated APPID=0x1000 stNum=1 sqNum=0 ...
Receive data lenth: 8
```

认证日志有抽样，不保证每帧都输出。默认 `stNum=1`、`sqNum` 逐帧递增；当前 `middle.c` 只对新 stNum 触发业务转发，因此重复状态不会逐帧写 Modbus。

若要让每帧都成为新状态，在命令末尾增加 `--change-state`，必要时显式填写经确认的测试值，例如 `--values 1,2,3,4,5,6,7,8`。这会生成 `(stNum,sqNum)=(1,0),(2,0),...`；不要在运行设备上盲目发送该测试值。

## 4. 负例测试

在正常命令末尾添加以下参数之一：

| 参数 | 发包顺序 | 预期 |
|---|---|---|
| `--mode replay` | 每个合法帧发送两次完全相同的字节 | 首次接受，第二次因重放被拒绝 |
| `--mode tamper` | 仅发 GCM tag 翻转一位的帧，不发送原合法帧 | 全部被拒，不新增 Modbus 写请求 |
| `--mode tamper-recover` | 先发错误 tag 帧，再发同一计数的原合法帧 | 错误帧被拒，后续合法帧可触发新状态写入；用于验证失败不污染重放状态 |
| `--mode plaintext` | 完成握手后发送无安全域的明文 GOOSE | 明文帧被拒绝，不进入业务解码 |
| `--mode bad-signature` | HELLO 签名翻转一位，重试同一 HELLO | 接收端拒绝握手；超时需结合接收端日志判断 |

每次独立运行都会生成新的临时 ECDHE 密钥和 SALT。当前接收端会在会话活跃时拒绝重新握手。连续切换测试时，停止旧模拟器、等待 **超过 30 秒无业务活动** 再启动下一次；或者在确认可中断测试服务后在设备执行 `sudo systemctl restart goose_middle.service`。模拟器不会替你重启服务。

2026-11-24 修正：旧版 `tamper` 实际执行的是现在的 `tamper-recover`，因此会看到原合法帧导致的业务写入。重放模式也有首次合法帧，不能要求整个测试零写入。订阅端修复了同一 stNum 的业务去重标记；默认不勾选“每帧递增 stNum”时，整个正常/重放测试仅首次新状态入队（当前双 BUS 为两次 0x10，地址 27204、27504，各 4 个寄存器）。已排队的合法请求可能在拒绝日志之后由发送线程执行，应对照新增的 `stNum/sqNum` 日志，不按打印先后顺序判断授权关系。

握手默认重试 10 次，每次 500ms；成功前不发送业务帧。所有发送完成日志只代表 PC 已提交发包，不代表设备已接受；验收依据为设备认证/拒绝日志和测试 Modbus 侧观测。

## 5. 抓包与定位

设备上（或 PC 将 net2 改为自己的网卡）：

```bash
sudo tcpdump -ni net2 -e 'udp port 30001 or ether proto 0x88b8'
```

- 无 ACK：看设备服务是否 active、net2 是否有 IP、UDP 是否可达、CRL 是否过期，以及旧会话是否仍活跃。
- HELLO 认证失败：检查发布端是否使用自己的 P-256 身份，两端信任根/CRL 是否包含彼此证书的签发方，系统时间是否正确。
- ACK 验证失败：模拟器会停止，不会跳过证书、CRL 或签名检查。
- 有认证日志、没有 Modbus 写入：检查是否仍是同一个 stNum；确认 8 个 INTEGER 及 `127.0.0.1:502` 上的测试 Modbus 服务。
- PC 抓到发送、设备抓不到：检查二层拓扑和组播转发。建议真实有线网口；虚拟机需桥接到该网口并允许组播，容器默认 NAT 不足以完成本测试。

## 6. 本地密码协议回归（不发网卡）

开发机需 GCC、OpenSSL 开发库和 pytest：

```bash
PYTHONPATH=.:exec/app python3 -m pytest -q \
  tools/goose_publisher/test_protocol.py \
  goose/goose_test/tests/test_goose_security.py
```

测试编译并调用真实 C 安全层，不需要真实设备或网卡权限。覆盖模拟器 ACK 信任校验、GCM 解密、8 元素数据集、重放/篡改/明文拒绝及原有密码协议回归；不代替真实网卡和 Modbus 实机联调。

另有 `goose/goose_test/tests/test_bridge_authorization.py`，设置 `GOOSE_TEST_LIBIEC` 为本机构建的 `libiec61850.so` 后运行。它执行真实 `middle.c` 的业务回调、队列与 Modbus 写报文构造，仅替换最终 send/recv，检查被拒帧不能增加写请求、同一状态重发不能重复入队。
