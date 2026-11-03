# 设备 SSH 通道接口

接口控制 Web 后端所在设备的 systemd SSH 服务，支持 `ssh.service`、`sshd.service`、`dropbear.service`，按此顺序选择首个存在的服务。若设备同时运行多个 SSH 服务，本接口仅管理选中的服务。

## 查询状态

`GET /api/system/ssh/status`，需要登录，使用现有 Session Cookie。

成功返回 HTTP 200，例如：

```json
{
  "success": true,
  "service": "ssh.service",
  "state": "active",
  "socket": null,
  "socketState": null,
  "enabled": true
}
```

`state`、`socketState` 为 systemd 当前运行状态。服务或对应 socket 为 `active` 时，`enabled` 为 `true`；该字段不表示开机自启设置，也不保证网络、防火墙和 SSH 登录认证均可用。

## 开启或关闭

`POST /api/system/ssh`，仅允许现有管理员权限组（`PERMISSION_TABLE["usermanage"]`）操作，携带 Session Cookie、`X-CSRF-Token` 和 `Content-Type: application/json`。

```json
{"enabled": true}
```

`true` 开启，`false` 关闭，必须为 JSON 布尔值。服务名和命令由后端固定，不接受客户端传入。关闭时先停止对应 socket（如果存在），避免新连接自动唤起服务，再停止 SSH 服务。操作后复查状态，成功响应结构与查询相同。

操作日志使用当前登录用户名，不使用请求中的 `operatorName`。参数错误返回 400，未登录返回 401，权限不足或 CSRF 校验失败返回 403；服务不存在、系统命令失败、超时或状态未达到目标返回 503。多步操作失败时可能已有部分步骤生效，应重新查询状态。

仅改变当前运行状态，不修改开机自启，不保证断开已建立的 SSH 会话。后端进程需要具有启动/停止对应 systemd unit 的系统权限。部署后重启 Web 后端使路由生效；无需数据库迁移。
