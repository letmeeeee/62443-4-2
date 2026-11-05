# HTTPS：外部 CA 签发、独立设备私钥与续签

设备只使用外部 CA 签发的身份证书，不在设备生成自签叶证书，不保留自签回退。HTTPS、Modbus 主机、Modbus 从机分别生成 CSR，使用三个独立私钥；默认共用同一受控 CA 根信任文件。CA 私钥始终留在外部 CA 系统。

## 配置

`/home/zlg/lc_data_set.ini`：

```ini
[TLS]
ca_file = /etc/ems/pki/ca-roots.crt

[HTTPS]
device_ips = 192.168.3.136,192.168.2.136
```

无需 certificate_mode 开关；旧配置如果保留非 external_ca 的 certificate_mode 值会被拒绝，不能恢复旧模式。`LC_INI_PATH` 可指定其他 INI；主服务、证书工具和 tems 应使用一致配置。ca_file 必须为绝对路径，仅保存可信根 CA 公共证书。中间 CA 证书随设备叶证书导入，不当作根信任锚。

HTTPS 私钥为 `/etc/ssl/g3/g3.key`，CSR 为 `g3.csr`，部署文件 `g3.crt` 为“叶证书 + 按签发关系排列的中间链”，不包含 CA 私钥。CSR CN 固定 logger，全部 device_ips 写入 IP SAN。device_ips 是本机访问地址，不是来源白名单，不负责配置网卡。

## 首次签发

将以下四个文件配套部署至 `/home/zlg/app/script/`：enable_https.sh、https_config.py、https_certificates.py、pki_common.py。工具需要 Python 3、OpenSSL 1.1.1+；部署代理还需要 Nginx、systemd、flock 和适当的本机文件/服务权限。

```bash
# 在设备上，仅生成设备密钥和 CSR；存在密钥时复用，不自动轮换。
python3 /home/zlg/app/script/https_certificates.py csr
python3 /home/zlg/app/script/https_certificates.py csr-export --out /tmp/https.csr
```

将 https.csr 交给外部 CA，按以下身份配置签发：CA:FALSE、digitalSignature、EKU 仅 serverAuth，CN logger，SAN 覆盖所有配置的设备 IP。新建私钥使用 RSA-3072；已有合格 HTTPS 私钥可以复用。不要复制 Modbus 私钥作为 HTTPS 私钥。

外部 CA 返回 HTTPS 叶证书、按顺序排列的中间链和根 CA 公共证书。通过可信渠道核对根 CA SHA-256 指纹后在设备导入：

```bash
python3 /home/zlg/app/script/https_certificates.py ca-import \
  --cert /tmp/roots.pem --fingerprint ROOT_CA_SHA256
python3 /home/zlg/app/script/https_certificates.py identity-import \
  --cert /tmp/https-leaf.pem --chain /tmp/intermediates.pem
python3 /home/zlg/app/script/https_certificates.py check
sudo bash /home/zlg/app/script/enable_https.sh --install-service
```

多个根用于受控轮换时，重复传 --fingerprint，须与整个根包一致。根信任变更也影响 Modbus：两个角色始终使用同一 CA 信任体系，需要维护窗口更新并重启相关 tems 进程。不要用另一张设备叶证书替代根 CA。

导入验证 CA 根、完整链、有效期、算法强度、CA:FALSE、EKU、digitalSignature、CSR 公钥/CN/SAN、当前 IP 集合及设备私钥匹配。失败不覆盖原身份证书。根证书不加入发送链；证书更新先备份旧公开证书，保留原私钥，并标记需要 reload。

签发证书就绪后才可安装/启动 HTTPS 代理。首次没有签发证书时，prepare 会生成待签 CSR 并失败，不会临时开放自签 HTTPS。通过受控本地终端完成首次签发，避免在重启后失去管理入口。

## 应用、检查与自动续签

```bash
sudo bash /home/zlg/app/script/enable_https.sh --apply
sudo bash /home/zlg/app/script/enable_https.sh --check
sudo systemctl start g3-cert-renew.service
```

- 每日 timer 继续运行，但功能变为检查签发证书和维护续签请求。有效期不足 30 天时复用原私钥生成 CSR，写 renewal-status.json，输出续签告警；仍在有效期内时保留原证书并继续服务。
- 证书缺失、过期、链不可信、私钥不匹配或当前 IP 未被 SAN 覆盖时，准备流程失败；绝不本地签叶证书或自动替换丢失的私钥。
- 外部 CA 完成续签后，再执行 identity-import 和 --apply；无需也不会把 CA 私钥放进设备。未接入 ACME/CA 在线协议，timer 无法代替外部 CA 完成签发。
- Nginx 使用 g3.crt 中的叶证书与中间链。导入产生的 reload 标记会触发实际 reload；失败时保留待应用标记以便重试。--prepare 只做准备与 nginx -t，不启动服务。
- 修改 IP 需要重新申请包含新 SAN 的证书，不会重新生成身份私钥。正常重启与续签也保留私钥。

`--install-service` 将四个脚本复制至 `/usr/local/lib/g3-https/`，安装初始化服务和每日 timer；更新后需重新执行安装命令刷新独立副本。HTTPS_CERT_DIR 可为工具/API 指定目录，Nginx 渲染相同证书路径；目录需位于受控持久分区。

现有 443 代理及 9000 精确查询转发保持原路径。80 端口未被其他服务占用时添加 HTTPS 重定向。脚本日志仍在 `/var/log/ems/https/https-YYYY-MM-DD.log`；续签失败还会出现在 systemd journal。客户端需信任外部 CA，不关闭证书验证。

不自动恢复旧自签证书。上线前必须完成三类 CSR 的外部签发与证书/CA 导入，再切换新程序并按维护流程验收。TEE 持久存储、CA 吊销服务和实际设备重启验证仍需平台验收。
