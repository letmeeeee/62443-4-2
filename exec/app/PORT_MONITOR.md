# 网口和 USB 插拔日志

部署 `main.py` 和 `utils/port_monitor.py` 并重启后端，通过 main.py 启动监控线程。
自动创建 `/mnt/nvme/zlog` 和 `/mnt/nvme/zlog/USB.log`，每条日志以追加方式写入。
进程需有目标路径写入权限及接收 Linux 内核 uevent 的权限。

```text
[2026-10-12T14:30:00.123+08:00] [NET] net1 LINK_UP
[2026-10-12T14:30:05.123+08:00] [NET] net1 LINK_DOWN
[2026-10-12T14:30:10.123+08:00] [USB] 1-2 INSERTED sysfs=1-2
[2026-10-12T14:30:15.123+08:00] [USB] 1-2 REMOVED sysfs=1-2
```

时间为设备本地时间，包含时区。使用 `tail -f /mnt/nvme/zlog/USB.log` 查看。
net1–net4 启动时记录 INITIAL 状态，此后只在状态变化时记录。
网口通过 `/sys/class/net/<接口>/carrier` 每 0.5 秒采样；链路上下线不一定等同于
物理拔插（对端关机等也影响链路），采样间隔内极短的通断可能无法捕获。
接口不存在或被关闭导致读取失败时记录 UNKNOWN/STATE_UNAVAILABLE，不伪报物理拔出。

USB 使用内核 uevent 的 usb_device add/remove 事件，过滤接口重复事件和根集线器。
不读取 USB 文件内容；监控启动前已接入的 USB 不补报插入事件。
已按设备实际映射设置默认值：USB1=`3-1.3`、USB2=`3-1.4`。
日志示例：`[USB] USB1 INSERTED sysfs=3-1.3`、`[USB] USB2 REMOVED sysfs=3-1.4`。
依次在两个面板口插拔并查看日志，即可确认映射。服务环境变量可设置：

```text
USB1_SYSFS_PATH=3-1.3
USB2_SYSFS_PATH=3-1.4
```

环境变量可覆盖默认值；同一物理口的 USB2/USB3 设备可能走不同总线，可用逗号配置多个路径。
没有匹配的设备继续记录实际路径，避免误标。修改环境变量后需重启后端。

日志写入或监听出错时通过现有 DPrint 记录错误，5 秒后尝试重新启动监控，业务服务继续运行。
服务停止、重启或监控故障期间的事件无法补录。当前为持续追加，未自动删除历史记录。
