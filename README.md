# 项目说明

这是一个 62443 认证项目。

## 功能
- 读取设备数据
- 修改设备参数

## Modbus TLS 桌面工具

支持 GUI 客户端与服务端、TLS 双向认证、证书导入/导出和寄存器读写。启动与联调步骤见 [使用说明](tools/modbus_gui/README.md)。

```bash
python3 -m tools.modbus_gui --role client
python3 -m tools.modbus_gui --role server
```
