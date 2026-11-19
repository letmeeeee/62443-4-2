# 补充组件清单

`components.json` 是适配 `GET /api/system/components` 的初始模板，不是已核实的整机 SBOM。部署前将“待确认”替换为实际版本，删除设备未安装或不属于交付范围的条目，并补充实际使用的固件、C/C++ 依赖及其他组件。

后端已自动列出 Python、Linux、当前 Python 环境包，以及可发现的 Node.js 和 MySQL 客户端，这些项目不在模板中重复列出。MySQL Server 与 MySQL 客户端版本应分别核实。`openssl version` 仅说明命令行程序的版本，不能证明所有应用链接的 OpenSSL 库版本。

每项支持字符串字段：`name`、`version`、`type`、`supplier`、`license`、`purl`、`sha256`。可选字段须有实际依据再填写；二进制摘要应根据最终交付文件计算。

设备上的默认示例部署位置为 `/home/zlg/app/sbom/components.json`，由 `security_config.json` 的 `COMPONENT_MANIFEST` 指定。修改清单后，下一次组件查询会重新读取，无需重启；修改安全配置文件路径或配置内容需要重启后端。

当前后端仅根据清单是否非空返回 `firmwareInventoryComplete`，即使有待确认项也可能返回 true。该字段不代表清单已经完整核验。
