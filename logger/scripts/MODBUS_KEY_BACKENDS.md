# Modbus TLS 可切换密钥后端

已实现。改动限定于密钥存储、证书生成/校验、TLS 身份加载及相应构建配置。
Modbus 收发、帧处理、连接管理、超时、TLS 协议和对端验证策略保持原有实现。
TA 源码、TA 文件、HTTPS 及业务配置结构未修改。

## 环境变量

```bash
# 默认 Linux 普通世界文件存储；不设置变量时也是 file
export MODBUS_KEY_BACKEND=file

# 使用原有 TA 角色密钥及签名接口
export MODBUS_KEY_BACKEND=tee
```

仅接受小写 file、tee，空值或其他值会在使用身份接口时明确报错。
TEE 不可用时不自动切换到 file。后端在每个进程首次使用身份接口时固定，修改后
需要重启进程。证书工具及辅助程序也遵循同一变量。

终端 export 不会修改已运行进程或独立 systemd 服务的环境。对应 tems 服务可配置：

```ini
[Service]
Environment=MODBUS_KEY_BACKEND=file
```

修改 unit/drop-in 后执行 daemon-reload 并重启对应服务。调用证书脚本的 Web 服务
如需使用 tee，也必须设置同一个变量。不要只在交互终端设置。

## 路径及安全边界

为保持现有业务流程，本次保留所有原有证书和信任文件路径，不引入后端子目录：

```text
/etc/ems/modbus/
  master.crt        # 主机证书，原路径
  slave.crt         # 从机证书，原路径
  master.key        # file 模式的 RSA-3072 私钥
  slave.key         # file 模式的 RSA-3072 私钥
  master-ca.crt     # 从机信任的主机证书，原路径
  backups/          # 原有公开证书/信任列表备份
```

file 私钥为无口令 PKCS#8 PEM，权限 0600，位于持久分区。生成采用临时文件、
文件 fsync、原子无覆盖发布及目录 fsync；已有私钥不覆盖。证书写入使用原子替换，
增加父目录 fsync。私钥不写入证书备份、不通过 export 命令导出、不进入日志。

私钥及其所在目录必须属于程序运行用户；目录不允许组或其他用户写入，私钥不允许
组或其他用户访问。拒绝私钥符号链接、非普通文件、损坏文件、加密 PEM 和非
RSA-3072 密钥。默认部署为 root 时使用 root:root；目录建议 0700。

file 的私钥由 Linux 进程读取并在普通世界使用，具有读取权限的进程/root 能获得
私钥。tee 的私钥由 TA 管理，实际持久后端仍取决于平台配置；本改动不修复设备
当前的 TEE 跨重启存储问题。

## 证书工具

沿用现有脚本和辅助程序名，`modbus_tee_identity` 现已同时支持 file/tee。
历史环境变量 MODBUS_TEE_IDENTITY 仍可覆盖辅助程序位置，避免影响现有部署。

```bash
# 首次创建从机身份；主机使用 --role master
MODBUS_KEY_BACKEND=file python3 /home/zlg/app/scripts/modbus_certs.py \
  generate --role slave --name EM-1000 --ip 192.168.2.136

MODBUS_KEY_BACKEND=file python3 /home/zlg/app/scripts/modbus_certs.py \
  check --role slave

# 复用已有私钥续期；不会补建丢失的密钥
MODBUS_KEY_BACKEND=file python3 /home/zlg/app/scripts/modbus_certs.py \
  renew --role slave --name EM-1000 --ip 192.168.2.136
```

- generate：已有证书时仍拒绝覆盖；不存在密钥时显式创建，存在时验证并复用。
- renew：仅使用已有密钥签证书；file/tee 密钥丢失时均报错，不会静默换身份。
- check、tems 启动和握手：只读取并校验证书/密钥，不能生成密钥。
- show、export、trust-add/list/remove：沿用原有公开证书和信任列表流程。
- `--dir` 仍用于脚本的自定义目录；辅助程序新增对应的 `--dir DIR` 前缀。
  tems 继续使用原有编译配置的证书路径，并在同目录查找同名 .key。

辅助程序接口：

```text
modbus_tee_identity [--dir DIR] ensure ROLE
modbus_tee_identity [--dir DIR] check ROLE CERT
modbus_tee_identity [--dir DIR] cert ROLE CN DAYS SAN
modbus_tee_identity [--dir DIR] cert-existing ROLE CN DAYS SAN
```

cert 保留首次创建能力；脚本 renew 调用 cert-existing。check 使用指定角色的
本机身份验证 CERT，避免将传入证书文件名误当作角色选择依据。

## 切换已有部署

切换后端只改变密钥来源，不自动替换证书或导出/迁移 TEE 私钥。两个后端通常
对应不同私钥，必须使用匹配的证书。

从旧 TEE 部署改为 file 时，在维护窗口保存现有证书，然后将原证书移至备份位置，
再显式执行 generate 创建文件身份。不要直接用旧证书搭配新文件私钥。
已有文件私钥时 generate 会复用它；如需全新身份，应先妥善保存原身份。

主机身份改变后，需更新从机信任的 master 证书；从机证书的分发遵循原有部署流程。
备份和切换都应按角色进行。回到 tee 前恢复与 TA 密钥匹配的证书，并在运行程序
及管理工具中显式设置 MODBUS_KEY_BACKEND=tee。已丢失的 TEE 私钥无法通过证书恢复。

仅设置环境变量不能实现旧私钥在两个后端之间迁移，当前 TA 没有私钥导出接口。

## 构建

```bash
# 双后端，运行时仍默认 file；需要目标 libteec
cmake -S logger -B /tmp/ems-modbus-dual-build -DMODBUS_WITH_TEE=ON
cmake --build /tmp/ems-modbus-dual-build --target tems modbus_tee_identity -j4

# 纯文件版本，不编译 TEE 适配器，也不依赖 libteec
cmake -S logger -B /tmp/ems-modbus-file-build -DMODBUS_WITH_TEE=OFF
cmake --build /tmp/ems-modbus-file-build --target tems modbus_tee_identity -j4
```

双后端版本的运行环境仍需有 libteec，即使运行时选择 file。纯文件版本设置 tee
会明确报“构建未包含 TEE 后端”。辅助程序和更新后的 Python 脚本必须配套部署。

## 验证

```bash
python3 logger/tests/test_modbus_file_identity.py
python3 logger/tests/test_modbus_tee_identity.py
```

文件测试使用真实 RSA 密钥和生产 modbus_transport.c 验证 TLS 双向身份及 Modbus
数据收发，覆盖独立进程读取、续期保留密钥、错误后端、私钥丢失/错配/符号链接/
权限错误/损坏及无 libteec 依赖。TEE 测试使用软件 TEEC 替身验证原接口及失效行为，
不代表设备安全存储验证。板端仍需执行整机重启后的身份指纹及 TLS 通信验收。
