# Modbus CA 身份与 file/TEE 私钥后端

只支持外部 CA 签发身份。file/tee 选择的是私钥存储，不是证书签发模式；没有自签或故障时自动回退。主机和从机必须各有独立私钥，属于同一受控 CA 体系；默认根信任与 HTTPS 共用 `/etc/ems/pki/ca-roots.crt`。

## 配置与文件

```ini
[TLS]
ca_file = /etc/ems/pki/ca-roots.crt
```

主服务、证书脚本及 tems 使用相同的设备 INI，默认 `/home/zlg/lc_data_set.ini`，可用 LC_INI_PATH 指定。无需 certificate_mode 开关，旧的非 external_ca 值会被拒绝。启用 Modbus TLS 后，双方校验 CA 链、当前时间、显式 CA:FALSE、digitalSignature 与各自 EKU；主机额外按实际 TCP 从机 IP 校验 IP SAN。

```text
/etc/ems/modbus/master.crt  # clientAuth 叶证书 + 中间链
/etc/ems/modbus/slave.crt   # serverAuth 叶证书 + 中间链
/etc/ems/modbus/master.csr
/etc/ems/modbus/slave.csr
/etc/ems/modbus/master.key  # 仅 file 后端
/etc/ems/modbus/slave.key   # 仅 file 后端
```

不再读取 master-ca.crt 叶证书钉扎列表。根文件只接受 CA:TRUE、keyCertSign、自签名及有效期验证通过的根 CA；中间 CA 随身份导入。运行时也拒绝用设备叶证书充当根信任。

默认 MODBUS_KEY_BACKEND=file，使用独立持久 RSA-3072 文件私钥。设置 tee 则复用现有 TA 角色槽与签名适配器，不新增 TA 命令，不导出私钥。两个服务的环境变量需一致；交互终端 export 不修改已运行的 systemd 服务。

file 密钥要求运行用户所有、0600，父目录不可被组/其他用户写。拒绝符号链接、损坏/加密/非 RSA-3072 私钥。切换 file/tee 不迁移私钥，需要与新后端对应的 CSR 和签发证书；不存在自动降级。

## CSR、签发与导入

配套部署 `modbus_certs.py` 至 `/home/zlg/app/script/`，并部署共享 `pki_common.py` 至 `/home/zlg/app/script/`；使用本次构建的 modbus_tee_identity，旧辅助程序不支持 CSR。CMake install 已将两个 Python 工具和共享 pki_common.py 纳入对应 script/scripts 目录。

```bash
export MODBUS_KEY_BACKEND=file
python3 /home/zlg/app/script/modbus_certs.py csr --role master --name device-master
python3 /home/zlg/app/script/modbus_certs.py csr --role slave --name device-slave --ip 192.168.2.136
python3 /home/zlg/app/script/modbus_certs.py csr-export --role master --out /tmp/master.csr
python3 /home/zlg/app/script/modbus_certs.py csr-export --role slave --out /tmp/slave.csr
```

外部 CA 分别签发 clientAuth 主机身份和 serverAuth 从机身份，不签双用途设备证书。CA:FALSE、digitalSignature、CSR 的 CN/公钥/SAN 必须保留。从机证书须覆盖客户端实际连接的 IP。

```bash
python3 /home/zlg/app/script/modbus_certs.py ca-import --cert /tmp/roots.pem --fingerprint ROOT_CA_SHA256
python3 /home/zlg/app/script/modbus_certs.py identity-import --role master --cert /tmp/master-leaf.pem --chain /tmp/intermediates.pem
python3 /home/zlg/app/script/modbus_certs.py identity-import --role slave --cert /tmp/slave-leaf.pem --chain /tmp/intermediates.pem
python3 /home/zlg/app/script/modbus_certs.py check --role master
python3 /home/zlg/app/script/modbus_certs.py check --role slave
```

重复 csr 复用已有密钥，续签通过再次导入 CA 返回的证书完成；不再有 generate/renew/trust-add/remove 子命令。已有身份或 CSR 的密钥丢失时拒绝重新创建。导入失败不覆盖证书；只备份旧公开链，不复制 TA 私钥。根 CA 更新也会影响 HTTPS 及其他角色，需在维护窗口保留 CA 轮换重叠根并重启相关服务。

辅助程序接口保持旧程序名，但仅提供：

```text
modbus_tee_identity [--dir DIR] ensure ROLE
modbus_tee_identity [--dir DIR] check ROLE CERT
modbus_tee_identity [--dir DIR] check-csr ROLE CSR
modbus_tee_identity [--dir DIR] csr[-existing] ROLE CN SAN
```

ensure 是显式初次密钥配置；csr-existing、check 和运行时不会补建丢失的私钥。辅助程序不执行 CA 签发；链校验由 Python 导入流程和 tems 运行时共同完成。

## 构建与验证

```bash
cmake -S logger -B /tmp/ems-modbus-file-build -DMODBUS_WITH_TEE=OFF
cmake --build /tmp/ems-modbus-file-build --target tems modbus_tee_identity -j4
# 双后端目标使用 -DMODBUS_WITH_TEE=ON 及匹配的 libteec/TA
python3 logger/tests/test_modbus_file_identity.py
python3 logger/tests/test_modbus_tee_identity.py
```

文件测试使用真实 CA、独立文件身份和生产 Modbus TLS 代码，通过 127.0.0.1 临时 TCP 端口验证双向 TLS、Modbus 报文和 IP SAN 拒绝；需要允许回环套接字。TEE 测试使用软件 TEEC 替身，验证 CSR、CA 证书匹配和丢失密钥拒绝，不代表实机安全存储或断电持久化验收。
