#!/usr/bin/env python3
"""LC400 PC SSH 部署工具；在 PC 运行，通过 SSH 管理设备 CSR 和 CA 身份证书。"""
import argparse
import getpass
import json
import os
from pathlib import Path

from provisioning.ssh_device import SSHDeviceProvisioner


DEVICE_FIELDS=('app','config','backend','modbus_dir','https_dir','helper')


def gui():
    from provisioning.ui import Window, filedialog, messagebox, tk, ttk
    w=Window('LC400 PC SSH 部署 — 设备 CSR / CA 身份证书')
    w.root.geometry('1120x900')
    notebook=ttk.Notebook(w.root);notebook.pack(before=w.form,fill='x',padx=12,pady=8)
    connection=ttk.Frame(notebook,padding=10);device=ttk.Frame(notebook,padding=10)
    notebook.add(connection,text='SSH 连接');notebook.add(device,text='设备路径与证书材料')
    w.form.pack_forget()
    for key,label,default in [('host','设备 IP / 主机名',''),('port','SSH 端口','22'),
        ('username','SSH 用户','root'),('host_fingerprint','SSH 主机指纹（SHA256:...）',''),
        ('remote_python','设备 Python 3 绝对路径','/usr/bin/python3')]:
        w.field(key,label,default,parent=connection)
    w.field('identity_file','PC SSH 私钥文件（可选，或使用 SSH Agent）','',file=True,parent=connection)
    w.field('known_hosts','PC known_hosts（可选，默认 ~/.ssh/known_hosts）','',file=True,parent=connection)
    w.field('password','SSH 登录口令（可选，仅当前窗口）','',secret=True,parent=connection)
    w.field('key_passphrase','SSH 私钥解密口令（可选，仅当前窗口）','',secret=True,parent=connection)
    sudo=tk.BooleanVar(value=False)
    ttk.Checkbutton(connection,text='设备端使用 sudo -n（需已配置免交互 sudo）',variable=sudo).grid(row=9,column=0,columnspan=3,sticky='w')
    for key,label,default in [('app','设备 app 目录','/home/zlg/app'),
        ('config','设备已有 INI 路径（只读）','/home/zlg/lc_data_set.ini'),
        ('backend','Modbus 密钥后端（file / tee）','file'),
        ('modbus_dir','设备 Modbus 身份目录','/etc/ems/modbus'),
        ('https_dir','设备 HTTPS 身份目录','/etc/ssl/g3'),
        ('helper','设备身份辅助程序','/home/zlg/app/bin/modbus_tee_identity'),
        ('device_id','设备编号','LC400-001'),
        ('output','下载到 PC 的 CSR 新目录',str(Path.home()/'LC400-001-csr'))]:
        w.field(key,label,default,parent=device)
    w.field('bundle','PC 上 CA 返回的证书包目录','',directory=True,parent=device)
    w.field('fingerprints','可信根 CA SHA-256（十六进制，多根逗号分隔）','',parent=device)
    w.field('tems_service','设备实际 tems 服务名（含 .service）','',parent=device)
    install_timer=tk.BooleanVar(value=True)
    ttk.Checkbutton(device,text='应用时安装/刷新 HTTPS 定时服务',variable=install_timer).grid(row=11,column=0,columnspan=3,sticky='w')
    def load_delivery():
        if w.busy:return
        filename=filedialog.askopenfilename(title='选择 CA 签发包中的 deployment.json（旧包可选 manifest.json）',
            filetypes=[('CA 部署记录','*.json')])
        if not filename:return
        try:
            from provisioning.deployment_record import load_record
            record=load_record(filename)
            description='设备：'+record['device_id']+'\n证书包：'+record['bundle']+'\n根 CA SHA-256：\n'+'\n'.join(record['root_fingerprints'])
            if not messagebox.askyesno('确认 CA 交付来源',description+'\n请确认该文件来自可信 CA 管理端。首次使用请独立核对根指纹。是否填入？'):return
            w.fields['bundle'].set(record['bundle'])
            w.fields['fingerprints'].set(','.join(record['root_fingerprints']))
            w.output.insert('end','已加载 CA 部署记录：\n'+description+'\n请继续预检证书包。\n')
            w.output.see('end')
        except Exception as exc:messagebox.showerror('部署记录无效',str(exc))
    w.button('加载 CA 部署记录',load_delivery)
    def action(kind):
        if w.busy:return
        values=w.values();use_sudo=sudo.get();install=install_timer.get()
        if kind in ('import','apply','recover'):
            messages={'import':'将通过 SSH 导入共享根和三份身份证书。确认已核对 CA 根指纹？',
                'apply':'将应用 HTTPS 配置并重启指定 tems 服务。确认设备处于维护窗口？',
                'recover':'将恢复设备上未完成导入前的公开证书。确认继续？'}
            if not messagebox.askyesno('确认远程设备操作',values['host']+'\n'+messages[kind]):return
        def work():
            options={key:values[key] for key in DEVICE_FIELDS if values[key]}
            tool=SSHDeviceProvisioner(values['host'],int(values['port']),values['username'],
                password=values['password'] or None,identity_file=values['identity_file'] or None,
                key_passphrase=values['key_passphrase'] or None,host_fingerprint=values['host_fingerprint'] or None,
                known_hosts=values['known_hosts'] or None,sudo=use_sudo,remote_python=values['remote_python'],options=options)
            if kind=='probe':return tool.probe()
            with tool:
                fingerprints=[v.strip() for v in values['fingerprints'].split(',') if v.strip()]
                if kind=='connect':result=tool.info()
                elif kind=='generate':result=tool.generate(values['device_id'],values['output'])
                elif kind=='preview':result=tool.preflight(values['bundle'],fingerprints)
                elif kind=='import':result=tool.import_bundle(values['bundle'],fingerprints)
                elif kind=='check':result=tool.check()
                elif kind=='recover':result=tool.recover()
                else:result=tool.apply(values['tems_service'],install)
                if getattr(tool,'cleanup_warning',None):result['cleanup_warning']=tool.cleanup_warning
                return result
        w.task(work)
    for label,kind in [('探测 SSH 指纹','probe'),('测试连接','connect'),('生成并下载 CSR','generate'),
        ('预检证书包','preview'),('导入证书包','import'),('校验身份','check'),('应用并重启','apply'),('恢复中断导入','recover')]:
        w.button(label,lambda k=kind:action(k))
    credentials=ttk.Frame(w.root,padding=4);credentials.pack(before=w.buttons,fill='x')
    def clear():
        if not w.busy:
            w.fields['password'].set('');w.fields['key_passphrase'].set('')
    ttk.Button(credentials,text='清除当前窗口 SSH 口令',command=clear).pack(side='left')
    ttk.Label(credentials,text='SSH 登录口令不保存到磁盘；未知主机需独立核对指纹。').pack(side='left',padx=8)
    w.run()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host',help='设备 SSH 主机名或 IP')
    p.add_argument('--port',type=int,default=22)
    p.add_argument('--user',default='root')
    p.add_argument('--password',action='store_true',help='交互输入 SSH 登录口令，不把口令放命令行')
    p.add_argument('--identity',help='PC SSH 私钥文件，可配合 SSH Agent')
    p.add_argument('--key-passphrase',action='store_true',help='交互输入 SSH 私钥解密口令')
    p.add_argument('--host-fingerprint',help='已通过可信渠道核对的 SSH SHA256:... 指纹')
    p.add_argument('--known-hosts',help='PC known_hosts 文件，默认 ~/.ssh/known_hosts')
    p.add_argument('--sudo',action='store_true',help='设备端使用 sudo -n，需预先配置免交互权限')
    p.add_argument('--remote-python',default='/usr/bin/python3')
    p.add_argument('--app',default='/home/zlg/app');p.add_argument('--config',default='/home/zlg/lc_data_set.ini')
    p.add_argument('--backend',choices=['file','tee'],default='file')
    p.add_argument('--modbus-dir',default='/etc/ems/modbus');p.add_argument('--https-dir',default='/etc/ssl/g3')
    p.add_argument('--helper',help='设备上的 modbus_tee_identity 绝对路径')
    sub=p.add_subparsers(dest='command');sub.add_parser('gui');sub.add_parser('probe');sub.add_parser('connect')
    generate=sub.add_parser('generate');generate.add_argument('--device-id',required=True);generate.add_argument('--out',required=True,help='PC 输出新目录')
    for operation in ('preview','import'):
        item=sub.add_parser(operation);item.add_argument('--bundle',required=True,help='PC 上的证书包目录')
        item.add_argument('--fingerprint',required=True,action='append',help='可信 CA 根十六进制指纹，每根重复一次')
    sub.add_parser('check')
    recover=sub.add_parser('recover');recover.add_argument('--confirm',required=True,choices=['RESTORE_PUBLIC_CERTIFICATES'])
    apply=sub.add_parser('apply');apply.add_argument('--tems-service',required=True)
    apply.add_argument('--confirm',required=True,choices=['APPLY_AND_RESTART']);apply.add_argument('--no-install-timer',action='store_true')
    args=p.parse_args()
    if args.command in (None,'gui'):return gui()
    if not args.host:p.error('--host is required for SSH operations')
    password=getpass.getpass('SSH 登录口令: ') if args.password and args.command!='probe' else None
    passphrase=getpass.getpass('SSH 私钥解密口令: ') if args.key_passphrase and args.command!='probe' else None
    options={name:getattr(args,name) for name in DEVICE_FIELDS if getattr(args,name)}
    tool=SSHDeviceProvisioner(args.host,args.port,args.user,password,args.identity,passphrase,
        args.host_fingerprint,args.known_hosts,args.sudo,args.remote_python,options)
    if args.command=='probe':result=tool.probe()
    else:
        with tool:
            if args.command=='connect':result=tool.info()
            elif args.command=='generate':result=tool.generate(args.device_id,args.out)
            elif args.command=='preview':result=tool.preflight(args.bundle,args.fingerprint)
            elif args.command=='import':result=tool.import_bundle(args.bundle,args.fingerprint)
            elif args.command=='check':result=tool.check()
            elif args.command=='recover':result=tool.recover()
            else:result=tool.apply(args.tems_service,not args.no_install_timer)
            if getattr(tool,'cleanup_warning',None):result['cleanup_warning']=tool.cleanup_warning
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    os.umask(0o077)
    try:main()
    except Exception as exc:raise SystemExit('PC SSH 部署失败: '+str(exc))
