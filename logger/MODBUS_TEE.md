# Modbus TLS 的 OP-TEE 私钥后端

`tems` 使用 OpenSSL 1.1.1 EVP 适配层直接调用 libteec。主机和从机分别使用
TA 的独立 RSA-3072 逻辑槽 0/1，与通用 RSA 密钥和 HTTPS 密钥独立。
不读取 `master.key` 或 `slave.key`，旧文件不会自动删除、导入。
公开证书仍保存在 `master.crt` / `slave.crt`。

## ABI 和验证边界

共享头文件 `optee_ta_examples/ta/crypto_ta/include/crypto_ta.h` 新增命令
8～11：幂等生成、公钥导出、摘要签名、摘要验签。原命令 0～7 保留。
支持 SHA-256/384/512 的 PKCS#1 v1.5 与 PSS，PSS MGF1 使用相同哈希，
盐长等于摘要长度。传入已算好的摘要，TA 不重复哈希。

本机初始化与 `check` 比较证书公钥并执行 TA 签名/验签自检。
对端证书信任、有效期与 clientAuth 用途仍由 OpenSSL 校验。
TLS 1.2 限定 ECDHE-RSA AES-GCM；TLS 1.3 使用默认套件。
TA 不可用或证书错配时拒绝初始化，无文件私钥回退。
普通证书续期复用 TA 密钥，通用 `rotate-rsa` 不影响 Modbus 密钥槽。
主机仍沿用现有配置：不验证从机证书；从机强制验证主机证书。

`TEEC_LOGIN_PUBLIC` 不提供调用者授权。设备访问控制需限制谁能调用 TA；
管理员 HTTP 认证与 TA 调用权限是不同边界。

## 构建与首次迁移

在仓库根目录首次导入设备依赖，随后直接编译：

```sh
sh logger/scripts/prepare_optee_client.sh --device root@DEVICE_IP
make -C logger -j4
make -C optee_ta_examples/ta/crypto_ta \
  O="$PWD/optee_ta_examples/build-crypto-ta" \
  TA_DEV_KIT_DIR="$PWD/optee_ta_examples/dev_kit" CROSS_COMPILE=aarch64-linux-gnu-
```

在维护窗口停止 `tems`，备份安装文件，部署匹配的 `.ta`、`tems`、
`modbus_tee_identity` 和 `modbus_certs.py`。身份工具安装到
`/home/zlg/app/bin/modbus_tee_identity`；其他路径可用环境变量
`MODBUS_TEE_IDENTITY` 指定。`.ta` 安装到设备现有 UUID 文件路径。
私钥初始化由证书工具执行；`tems` 只打开已有密钥。

首次身份使用 `generate`；迁移已有文件身份使用 `renew`，备份旧证书并
生成与 TA 密钥匹配的新证书。旧 RSA-2048 证书不能直接用于 TA RSA-3072
密钥，须将新的主机公开证书导入对端从机信任文件，再启动双方。

```sh
python3 exec/app/script/modbus_certs.py renew --role master --name master-001
python3 exec/app/script/modbus_certs.py check --role master
python3 exec/app/script/modbus_certs.py renew --role slave --name slave-001
python3 exec/app/script/modbus_certs.py check --role slave
```

`route_cert.py` 原有生成/续期/检查接口继续调用此脚本，因此调用相同的 TA
身份工具。无需通过 HTTP 调用另一个 HTTP 接口。

## 验证

开发机的软件 TEEC 替代测试，不访问设备存储：

```sh
cc -std=c99 -Wno-deprecated-declarations -Ilogger/lib \
  -I/path/to/optee-client/include -Ioptee_ta_examples/ta/crypto_ta/include \
  logger/tests/test_modbus_tee.c logger/lib/modbus_tee.c \
  -lssl -lcrypto -lpthread -o /tmp/test-modbus-tee
/tmp/test-modbus-tee
OPTEE_CLIENT_INCLUDE_DIR=/path/to/optee-client/include \
  python3 logger/tests/test_modbus_tee_identity.py
```

测试覆盖独立密钥槽、客户端无私钥属性、证书错配、TLS 1.2/1.3 客户端证书
认证与加密数据交换，以及 TA 错误时拒绝使用身份。
实机还须验证真实 OP-TEE 存储、TLS 握手性能、进程重启后的密钥复用与
对端信任配置。TEE 测试替代实现中的软件私钥仅存在测试进程中。
