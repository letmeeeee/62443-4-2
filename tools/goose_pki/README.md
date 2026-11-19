# GOOSE P-256 证书工具

在项目根目录启动：

```bash
python3 -m pip install -r provisioning/requirements-ca.txt
python3 goose_pki_gui.py
```

Linux 需要系统安装 `python3-tk` 并在图形桌面运行；Windows 可使用带 Tkinter 的 Python，执行 `python goose_pki_gui.py`。签发在本机完成，不依赖 OpenSSL 命令行。

1. 填写设备 CN，例如 `LC400-001-goose`，点击“生成私钥和 CSR”。算法固定为 prime256v1 / P-256，CSR 使用 ECDSA/SHA-256。
2. 立即“导出设备私钥”和“导出 CSR”。导出的私钥是设备导入接口所需的未加密 PKCS#8 PEM，在 Linux 上以 0600 权限创建。关闭窗口会丢失未保存的密钥。
3. 有现有 CA：选择签发 CA 证书及对应 CA 私钥，点击“加载现有 CA”，输入私钥口令（未加密时留空）。支持 RSA（至少 2048 位）或 EC CA；只有 CA 证书、没有 CA 私钥时无法签发，可把导出的 CSR 交给 CA 管理员签发。导入已有 CSR 时工具不持有设备私钥。
4. 无现有 CA：点击“新建根 CA”，设置名称和至少 12 位保护口令，选择保存位置。工具新建独立目录并保存 `ca-private.key`（加密 CA 私钥）、`ca-roots.crt` 和 `crls.pem`，同时加载 CA。根 CA 有效期 10 年，初始空 CRL 有效期 30 天。该 CA 只能签发终端证书，不能签发中间 CA。
5. 设置设备证书有效期，点击“签发证书”，核对身份与 CA 后确认，再“导出设备证书”为 `enc.crt`。证书包含关键的 `CA:FALSE`、Digital Signature、SKI 和 AKI，限制握手证书大小；无 TLS 专用 EKU。
6. 对 GOOSE 后端，在同一 `batch_id` 内依次导入四类材料，最后 apply：

| 导入项 | 文件 |
|---|---|
| identity | `enc.crt`，设备证书；有中间 CA 时追加中间证书链 |
| key | `enc.key`，该设备对应的 P-256 私钥 |
| ca | 信任根，例如新建 CA 的 `ca-roots.crt` |
| crl | 当前有效的 `crls.pem`；存在中间 CA 时需所有适用 CRL |

“导出签发 CA 证书”导出的是加载的签发者，不保证它是根 CA。使用现有 SCADA CA 时，信任根、链和 CRL 从原 CA 管理系统取得。新 CA 与原 SCADA CA 属于不同信任体系，通信双方必须配置兼容的信任材料，双方设备证书及私钥分别生成。

本工具提供单次离线签发，不提供签发台账、吊销及 CRL 续期。新 CA 的 CRL 到期前须通过 CA 管理工具维护；已有 CA 的 CRL 不会被本工具重新生成或清空。导出拒绝覆盖已有文件；生成新身份前会提示保留当前文件。修改 CN 输入框不会更改已经生成的 CSR；需重新生成。

验证：

```bash
python3 -m unittest tools.goose_pki.test_crypto -v
```
