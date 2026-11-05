# 项目说明

这是一个 62443 认证项目。

## 开发者与 Agent 入口

[62443-4-2 开发者手册](62443-4-2开发者手册.md)：当前安全架构、代码导航、认证权限、审计、CA/TEE、部署、备份恢复、接口索引与验证边界。接手安全功能前优先阅读。


## 功能
- 读取设备数据
- 修改设备参数

## Modbus TLS 桌面工具

支持 GUI 客户端与服务端、TLS 双向认证、证书导入/导出和寄存器读写。启动与联调步骤见 [使用说明](tools/modbus_gui/README.md)。

```bash
python3 -m tools.modbus_gui --role client
python3 -m tools.modbus_gui --role server
```
