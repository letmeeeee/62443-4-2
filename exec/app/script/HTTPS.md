# HTTPS 自动配置

设备配置文件为 `/home/zlg/lc_data_set.ini`，添加以下字段（不要覆盖文件内其他配置）：

```ini
[HTTPS]
device_ips = 192.168.3.136,192.168.2.136
```

`device_ips` 是客户端用于访问本设备的 IPv4 地址，不是客户端来源白名单。支持逗号、空格分隔，去重排序；仅一个地址时直接填写该地址。地址配置错误或字段缺失会使初始化失败，不会使用默认 IP 或覆盖原 INI。脚本不会配置网卡或判断这些地址是否已经分配，必须先确保设备网络配置正确。

证书 subject 的 CN 固定为 `logger`，自签名证书的 issuer 同样为 `CN=logger`；所有地址写入同一张证书的 SAN，Nginx 仍使用 `listen 443 ssl` 监听所有 IPv4 网口。指定 IP 不限制客户端来源。升级查询 `/api/upgrade/process` 精确转发到回环 9000，其余业务和 Socket.IO 走回环 8000；两个后端应开启 `HTTPS_ENABLE`。前端统一使用 HTTPS 同源相对路径。

## 首次部署

需要设备上已安装 Nginx、支持 `-addext` 的 OpenSSL、Python 3、systemd 和 flock。将 `enable_https.sh` 与 `https_config.py` 一起部署到 `/home/zlg/app/script/`，填写 INI 后执行：

```bash
sudo bash /home/zlg/app/script/enable_https.sh --install-service
```

安装操作会应用配置、启动或 reload Nginx，并安装：

- `/usr/local/lib/g3-https/`：脚本及 INI 解析程序的独立副本，避免应用升级替换代码目录时丢失。
- `g3-https.service`：开机等待 `network-online.target` 后准备证书与配置。Nginx 通过 drop-in 依赖该服务，初始化失败时不会启动 Nginx。
- `g3-cert-renew.service` / `g3-cert-renew.timer`：每天约 03:00 重新读取 INI，按需续期和更新配置。

证书不存在、有效期不足 30 天、IP 集合变化、subject 不是 `CN=logger` 或证书私钥不匹配时重新生成，有效期 398 天；正常重启不更换证书。配置或证书变更前备份到 `/etc/ssl/g3/backup/`，`nginx -t` 失败时恢复原文件。reload 本身失败时保留已通过校验的新文件并报告失败，需检查 Nginx 日志。脚本不会等待后端返回 200，因此后端尚未启动不会阻止 TLS 初始化。

这是自签名证书，客户端需要信任它。IP 变更或续期生成新证书后可能需要更新客户端信任；不应通过长期关闭证书校验替代信任配置。若使用自有 CA 签发的证书，应先调整证书管理流程，避免本自动化替换它。

## 配置更新与检查

修改 INI 后立即应用（否则等待每日 timer）：

```bash
sudo systemctl start g3-cert-renew.service
sudo bash /usr/local/lib/g3-https/enable_https.sh --check
sudo journalctl -u g3-https.service -u g3-cert-renew.service -u nginx -n 100 --no-pager
```

`--prepare` 仅生成和校验文件，供启动服务调用；无参数或 `--apply` 会额外启动/reload Nginx。旧的命令行 IP 和 `DEVICE_IP` 环境变量不再用于选择地址，INI 为唯一地址来源。

## 文件日志

脚本自动创建 `/var/log/ems/https/`，按执行开始日期追加到 `https-YYYY-MM-DD.log`。日志包含执行模式、进程 ID、开始/结束记录及退出码，同时收集后续命令的标准输出和错误（包括 INI 解析、OpenSSL 和 Nginx 校验输出）。终端和 systemd journal 仍保留输出。日志目录权限为 0750，文件为 0640；帮助、参数错误和 root 权限检查发生在日志初始化前，不写入文件。日志按日分文件，当前不自动清理历史文件。

例如查看当天日志：

```bash
sudo tail -n 100 -f /var/log/ems/https/https-$(date +%F).log
```

以后更新脚本时，重新执行 `--install-service` 更新独立副本及 unit。应用服务仍独立运行，不需要给 Flask root 权限。修改 INI 不会即时监控触发更新；新增 IP 的 Cookie 也不与其他 IP 自动共享，需要从该 IP 登录。
