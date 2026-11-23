# 部署、配置、性能和验证

## 运行边界

开发机仓库与设备 `/home/zlg/app/` 不同。先查 systemd 的 ExecStart、WorkingDirectory 和具体环境变量，必要时核对进程实际加载的代码路径；不要因文件已上传就认为进程已使用。常见服务为 `python_app.service`、`tems.service`、`g3-https.service`，具体设备仍需确认。

8000 是 Flask 主服务、9000 是独立升级查询，HTTPS_ENABLE 开启时通常监听回环，由 Nginx 443 终结 TLS。`/api/upgrade/process` 的代理、查询格式及状态文件位置按当前升级代码确认，升级期间不能依赖主 Flask 一直存活。升级脚本会操作数据库和服务，普通状态解析问题不应直接执行升级。

`enable_https.sh --install-service` 会安装独立脚本副本和 systemd 配置，有真实副作用。设备 INI 常见 `/home/zlg/lc_data_set.ini`，HTTPS IP/CN 规则以当前 https_config.py 为准，不沿用旧版 CN=logger 的假设。

## 环境变量与 SBOM

`script/security_config.py` 读取环境变量 `SECURITY_CONFIG_FILE` 指向的 JSON，没有默认文件路径。`COMPONENT_MANIFEST` 是其中的配置项，当前不直接读取同名环境变量，也没有默认清单路径。值必须是绝对路径。示例：

```json
{"COMPONENT_MANIFEST": "/home/zlg/app/instance/sbom/components.json"}
```

实际部署中安全配置可在 `/home/zlg/instance/security/security_config.json`，这是已见设备配置而非程序默认值。以服务实际环境为准。终端 export 不会改变已运行进程，也不会自动传给 systemd 服务；服务可使用 drop-in 的 `[Service] Environment=...`，修改后 daemon-reload 并重启相应服务。只有清单内容更新时，下次组件查询重新读取，无需重启。

只读定位命令示例（设备执行，路径按实际配置）：

```bash
systemctl show python_app.service -p MainPID --no-pager
systemctl show python_app.service -p Environment --no-pager | tr ' ' '\n' | grep '^SECURITY_CONFIG_FILE='
ls -lh /home/zlg/app/instance/sbom/components.json
python3 -m json.tool /home/zlg/app/instance/sbom/components.json
```

用 `--no-pager` 防止用户停在分页界面。不要要求贴出完整环境或含密钥配置。SSH 会话不能从用户终端直接接管；授权后可使用已知连接和密钥，不存放密码到技能，不绕过主机指纹校验。认证失败应说明缺少哪项，不重复猜测用户名或密码。

组件入口 `GET /api/system/components` 自动采集 Python、Linux、当前 Python 环境包、可发现的 Node.js 与 MySQL client，追加 COMPONENT_MANIFEST JSON 数组。支持字符串字段 `name/version/type/supplier/license/purl/sha256`，大小限 1 MiB，不是通用 SPDX/CycloneDX 解析器。

- `firmwareInventoryComplete=false`：未加载清单配置或数组为空。
- `RESOURCE_NOT_FOUND`：FileNotFoundError 映射，优先查清单真实路径、目录和链接；不是一定缺少路由。
- 配置存在但清单缺失通常返回错误，不会安静回落 false。
- 非空数组会令 complete 为 true，并不验证完整性和真实版本。仓库 `exec/app/sbom/components.json` 含待确认项，不能当作已核验整机 SBOM。
- 不用开发机包版本、构建目录中的头文件版本替代设备实际部署版本。

安全配置还支持空闲超时、审计保留、限流、代理信任、破坏操作开关、状态/磁盘/证书路径、设备 ID 和出厂备份信息。完整字段及类型以 security_config.py 的 DEFAULTS/PATHS/STRINGS 为准；避免给可选路径填空或随意捏造备份摘要。

## 刷新与 CPU

浏览器请求耗时包含等待、排队、I/O、采样及认证，不能等同 CPU 时间。查每次刷新是否重复启动进程、做 PBKDF2、OpenSSL 自检或全表统计，再考虑缓存/合并；分开报告首次请求、热缓存、并发及目标设备实测。

当前 `utils/system_usage.py` 将 CPU 0.2 秒采样在进程内复用 1 秒；cpu-usage、disk-usage 和安全 status 可共享。`utils/public_read_cache.py` 为 network-rules 提供两秒公开采集缓存，合并两次 ip 和一次 firewall-cmd；内存和 maintenance 等并不因此全部缓存。

`utils/pki_read_cache.py` 缓存公开 PKI 查询两秒，检查配置、文件元数据/内容和待应用标志，带锁和深拷贝。导入、CSR、显式 check/verify、应用和真实 TLS 校验不要因复用查询缓存而被跳过。认证和 CSRF 每个请求仍执行。多进程缓存不共享；时间和外部状态最多有短暂显示延迟，不能承诺“完全无行为变化”或没有首次 CPU 峰值。

## 测试与交付

先发现可用解释器及依赖，不把历史 `/tmp/...venv` 路径写进正式部署要求。模块导入可能初始化设备和生产数据库，测试使用既有 config/device 替身。不为技能和纯文档改动运行设备服务。

示例（按任务选择文件，不机械全跑）：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=exec/app python3 -m pytest -q \
  exec/app/tests/test_security_center.py exec/app/tests/test_auth_session.py
```

性能采集可选 `test_refresh_telemetry.py`、`test_firewalld_rules.py`；PKI 见专门参考；升级先搜索当前 tests 中 upgrade 相关覆盖。替身测试不代表真实网络规则、MySQL 锁或 ARM 性能；失败时区分环境缺依赖与代码回归。保留测试输出中的实际通过、失败和跳过数量。

检查修改范围和换行：`git diff --check`；旧 CRLF 可用 `git -c core.whitespace=cr-at-eol diff --check`，不要全文件转换掩盖差异。交付列出需同步的新增依赖模块、是否要重启/重编译、是否仅本地验证，以及剩余实机验证。除用户要求，不自动部署、提交或修改前端构建产物。
