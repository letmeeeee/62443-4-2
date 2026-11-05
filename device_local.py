#!/usr/bin/env python3
"""LC400 设备本地维护后端；日常部署请在 PC 运行 device_deploy.py。"""
import argparse
import json
import os

from provisioning.device import DeviceProvisioner


def gui():
    from provisioning.ui import Window, messagebox
    w = Window('LC400 设备首次部署 — CSR / CA 身份证书')
    w.field('app', '设备 app 目录', '/home/zlg/app', True)
    w.field('config', '已有 INI 路径（只读）', '/home/zlg/lc_data_set.ini')
    w.field('backend', 'Modbus 密钥后端（file 或 tee）', 'file')
    w.field('modbus_dir', 'Modbus 身份目录', '/etc/ems/modbus')
    w.field('https_dir', 'HTTPS 身份目录', '/etc/ssl/g3')
    w.field('device_id', '设备编号', 'LC400-001')
    w.field('output', 'CSR 输出目录（必须不存在）', '/tmp/LC400-001-csr')
    w.field('bundle', 'CA 返回的证书包目录', '', True)
    w.field('fingerprints', '可信渠道确认的根 SHA-256（多根用逗号分隔）', '')
    w.field('tems_service', '实际 tems systemd 服务名（含 .service）', '')
    def action(kind):
        if w.busy: return
        values = w.values()
        if kind in ('import', 'apply', 'recover'):
            prompt = {'import':'将导入共享根 CA 及三份身份证书，替换设备公开证书文件。确认已核对根指纹？',
                      'apply':'将刷新 HTTPS 服务及定时器、应用 Nginx 配置，并重启指定 tems 服务。确认处于维护窗口？',
                      'recover':'将按未完成导入的恢复记录还原导入前的根信任和公开证书。确认继续？'}[kind]
            if not messagebox.askyesno('确认设备操作', prompt): return
        def work():
            tool = DeviceProvisioner(**{k:values[k] for k in ('app','config','backend','modbus_dir','https_dir')})
            fingerprints = [f.strip() for f in values['fingerprints'].split(',') if f.strip()]
            if kind == 'generate': return tool.generate(values['device_id'], values['output'])
            if kind == 'preview': return tool.preflight(values['bundle'], fingerprints)
            if kind == 'import': return tool.import_bundle(values['bundle'], fingerprints)
            if kind == 'check': return tool.check()
            if kind == 'recover': return tool.recover()
            return tool.apply(values['tems_service'])
        w.task(work)
    for label, kind in [('1 生成/导出三份 CSR','generate'),('2 预检证书包','preview'),('3 导入证书包','import'),('4 本机校验','check'),('5 应用并重启','apply'),('恢复中断导入','recover')]:
        w.button(label, lambda k=kind: action(k))
    w.run()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--app', default='/home/zlg/app')
    p.add_argument('--config', default='/home/zlg/lc_data_set.ini')
    p.add_argument('--backend', choices=['file','tee'], default=os.environ.get('MODBUS_KEY_BACKEND','file'))
    p.add_argument('--modbus-dir', default='/etc/ems/modbus')
    p.add_argument('--https-dir', default='/etc/ssl/g3')
    p.add_argument('--helper', help='modbus_tee_identity 的绝对路径（默认 app/bin 下）')
    sub = p.add_subparsers(dest='command')
    sub.add_parser('gui')
    generate = sub.add_parser('generate'); generate.add_argument('--device-id', required=True); generate.add_argument('--out', required=True)
    for operation in ('preview','import'):
        cmd = sub.add_parser(operation); cmd.add_argument('--bundle', required=True)
        cmd.add_argument('--fingerprint', required=True, action='append', help='每个根重复一次，必须经可信渠道核对')
    sub.add_parser('check')
    recover = sub.add_parser('recover'); recover.add_argument('--confirm', required=True, choices=['RESTORE_PUBLIC_CERTIFICATES'])
    apply = sub.add_parser('apply'); apply.add_argument('--tems-service', required=True)
    apply.add_argument('--confirm', required=True, choices=['APPLY_AND_RESTART'])
    apply.add_argument('--no-install-timer', action='store_true', help='仅应用 HTTPS，不刷新 systemd 定时服务')
    args = p.parse_args()
    if args.command in (None,'gui'): return gui()
    tool = DeviceProvisioner(args.app, args.config, args.backend, args.modbus_dir, args.https_dir, args.helper)
    if args.command == 'generate': result = tool.generate(args.device_id, args.out)
    elif args.command == 'preview': result = tool.preflight(args.bundle, args.fingerprint)
    elif args.command == 'import': result = tool.import_bundle(args.bundle, args.fingerprint)
    elif args.command == 'check': result = tool.check()
    elif args.command == 'recover': result = tool.recover()
    else: result = tool.apply(args.tems_service, not args.no_install_timer)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    os.umask(0o077)
    try: main()
    except Exception as exc:
        raise SystemExit('设备部署失败: ' + str(exc))
