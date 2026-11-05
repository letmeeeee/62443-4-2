# CA 双向 Modbus TLS 手动联调

使用 modbus_tls_peer.py 可在电脑上模拟主机/从机，只用 Python 标准库。先为电脑角色生成独立 CSR，经与设备相同的外部 CA 体系签发，再通过 modbus_certs.py identity-import 导入叶证书及中间链。完整流程见 MODBUS_KEY_BACKENDS.md。

电脑从机证书的 IP SAN 必须覆盖设备实际连接的电脑 IP；电脑主机按 --host 校验设备从机的 SAN。两个角色均要求 CA 证书链验证，不存在关闭验证选项。--no-cert 只用于不发送客户端证书的拒绝反例，不会关闭对服务端的验证。

```bash
# 已有 CA 签发的 master.crt/fullchain 和 master.key
python3 logger/scripts/modbus_tls_peer.py master \
  --host 192.168.2.136 --port 18020 --cert-dir /path/to/master-identity --ca-file /path/to/roots.pem

# 已有 serverAuth 的 slave.crt/fullchain 和 slave.key
python3 logger/scripts/modbus_tls_peer.py slave \
  --bind 192.168.2.100 --port 18020 --cert-dir /path/to/slave-identity --ca-file /path/to/roots.pem
```

证书目录不得包含 CA 私钥。设备与电脑只交换 CSR、签发身份链和可信根公共证书，不复制设备角色私钥。模拟从机只返回地址构造的寄存器值，不执行设备控制操作。此标准库工具适用于文件私钥；TEE 身份需用实际 tems/适配器测试。

应验证：正常链可收发；不带客户端证书被拒绝；未知 CA、过期证书、错误用途、错误从机 IP SAN 被拒绝；失败时不转明文连接。生产设备还需验证重启后指纹与私钥保留、外部 CA 续签和维护重启流程。
