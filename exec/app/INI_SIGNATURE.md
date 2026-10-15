# INI SHA-256 完整性校验

受检文件：`/home/zlg/lc_data_set.ini`。
基准文件：`/home/zlg/signature/lc_data_set.ini.sha256`，内容为 64 位十六进制摘要。
无需公钥、私钥或 OpenSSL，旧 `.sig` 文件不再用于本检测，OTA 公钥保持不变。

确认配置正确后，在设备上手动生成基准：

```bash
python3 /home/zlg/app/script/sign_ini.py
```

脚本保留原文件名，但功能已改为生成 SHA-256。支持 `--ini`、`--output`。
生成过程检查配置是否发生变化，并原子替换基准文件。
后端不会自动创建或更新基准，避免将未授权改动接受为正常配置。

通过 main.py 启动后立即检查，随后每轮完成等待 60 秒再次检查。
匹配打印 `[INI Integrity] PASS`；不匹配、文件缺失或基准格式错误打印 ERROR/FAIL，
继续运行并继续检测。合法修改配置后，确认内容无误再手动运行生成命令。

这是变化检测，不是数字签名；能同时修改 INI 和基准文件的人可绕过检测。
当前工作区的修改需要部署到 Linux 并重启后端后生效。
