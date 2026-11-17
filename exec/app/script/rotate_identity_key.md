# 设备身份密钥轮换

`rotate_identity_key.sh` 为 `master`、`slave` 或 `https` 更换文件形式的
RSA-2048 公私钥对，并生成与新密钥匹配的 CSR。原 RSA-2048/3072 文件密钥均可轮换。
依赖 Python 3.8+、OpenSSL
及同目录下现有 Python 证书工具，无需导入 Flask 或连接数据库。

此脚本用于密钥泄露后的更换或计划轮换。普通证书续期仍调用原 CSR 接口，
保留原密钥。脚本不会吊销旧证书，也不会更新 CA/CRL 或自动签发证书。

## 执行方式

在维护窗口停止使用对应身份的服务，再运行脚本。Modbus 主从通常在同一个
`tems` 进程中；HTTPS 对应 Nginx。脚本不自动停止、启动或重载任何服务。
不要在等待 CA 签发期间通过旧证书恢复服务。

使用与证书服务一致的运行用户执行，身份目录必须归该用户所有且不可由组或
其他用户写入，原私钥权限须为 `0600`。

```sh
# Modbus 主机：默认保留原 CSR/证书的 CN 和 SAN
sh /home/zlg/app/script/rotate_identity_key.sh master --confirm ROTATE_IDENTITY_KEY

# Modbus 从机：显式指定 CN 和 SAN；--ip、--dns 可以重复
sh /home/zlg/app/script/rotate_identity_key.sh slave \
  --name slave-001 --ip 192.168.2.136 --dns logger.example.com \
  --confirm ROTATE_IDENTITY_KEY

# HTTPS：CN=LC400-logger，SAN 按 INI 的 [HTTPS] device_ips 生成
sh /home/zlg/app/script/rotate_identity_key.sh https --confirm ROTATE_IDENTITY_KEY
```

默认配置文件为 `/home/zlg/lc_data_set.ini`，可通过 `--config PATH` 或
`LC_INI_PATH` 指定。Modbus 默认目录为 `/etc/ems/modbus`，HTTPS 默认目录为
`/etc/ssl/g3`；支持 `--dir PATH`，或分别设置 `MODBUS_CERT_DIR`、
`HTTPS_CERT_DIR`。`PYTHON` 可指定 Python 解释器路径。

Modbus 若只提供 `--name`，仍保留原 SAN；若显式提供任一 `--ip` / `--dns`，
则以这次提供的全部 SAN 替换原 SAN。HTTPS 不接受这些覆盖参数。

## 执行结果与后续操作

脚本先生成并校验新密钥和 CSR，再将旧 `.key`、`.csr`、`.crt`（存在时）
保存到身份目录下的 `backups/<身份>-rotation-<随机值>/`。备份目录权限为
`0700`，备份文件权限为 `0600`，其中包含旧私钥，应限制访问并按维护策略处理。

随后撤下旧 `.crt`，安装新 `.key`（`0600`）和 `.csr`（`0644`）。主机、从机
分别使用 `master.*`、`slave.*`，HTTPS 使用 `g3.*`。仅处理选中的身份。
HTTPS 还会备份并移走旧的 `.reload-required` 和 `renewal-status.json`。
日志输出备份路径、CSR 路径及新公钥的 SHA-256 摘要，不输出私钥。

1. 导出对应的 CSR，交给 CA 签发；私钥泄露场景应先由 CA 吊销旧证书。
2. 用现有证书导入 API 或 `modbus_certs.py` / `https_certificates.py`
   的 `identity-import` 命令导入新证书及中间证书链。
3. 校验证书，再重启 `tems` 或执行 HTTPS apply，使服务使用新身份。

脚本使用现有全局证书操作锁和身份目录锁，与导入、CSR 操作互斥。
安装阶段发生可捕获异常时尝试恢复原文件；若掉电、强制终止或恢复失败，
可能留下 `.<身份>-rotation-incomplete.json`。此记录指向备份目录，并通过
`restore_files` 记录哪些原文件存在。下次轮换会拒绝继续。维护人员应在服务
停止状态检查和恢复一致的文件集合后处理该记录；泄露恢复场景不应重新启用
已泄露的旧密钥。多个文件的切换不具备掉电原子性。

## Modbus TEE 后端

执行环境中的 `MODBUS_KEY_BACKEND` 应与 `tems` 使用的后端一致，也可用
`--backend` 显式指定。脚本默认值与现有证书工具一致，为 `file`。
当前 TA 没有主从槽位轮换命令，因此 `--backend tee` 或
`MODBUS_KEY_BACKEND=tee` 下的 Modbus 轮换会在写入前失败。
不要为了绕过检查将实际使用的 TEE 后端改成 file；文件轮换不会修改 TEE。
通用 `crypto_ta_client rotate-rsa` 也不会更换 Modbus 主从槽位。
HTTPS 的本地密钥轮换不受这个 Modbus 后端设置影响。
