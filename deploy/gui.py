#!/usr/bin/env python3
"""Tk desktop frontend for the existing deployment CLI (no third-party Python packages)."""
from dataclasses import dataclass
from datetime import datetime
import ipaddress
import os
from pathlib import Path
import queue
import re
import shlex
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Options:
    host: str = 'root@192.168.2.136'
    jobs: str = '4'
    frontend: bool = False
    skip_build: bool = False
    initialize_baseline: bool = False
    master_enabled: bool = False
    master_name: str = ''
    slave_enabled: bool = False
    slave_name: str = ''
    slave_ips: str = ''
    trust_enabled: bool = False
    certificate: str = ''
    fingerprint: str = ''


def validate_host(value):
    value = value.strip()
    if not re.fullmatch(r'(?:[A-Za-z0-9_]+@)?[A-Za-z0-9][A-Za-z0-9.-]*', value):
        raise ValueError('请输入 SSH 地址，例如 root@192.168.2.136')
    return value


def build_command(options, bundle_only=False):
    command = [sys.executable, '-u', str(ROOT / 'deploy/deploy.py'), '--batch-mode']
    if options.host.strip():
        command += ['--host', validate_host(options.host)]
    elif not bundle_only:
        raise ValueError('部署时必须填写工控机地址')
    try:
        jobs = int(options.jobs)
    except ValueError:
        raise ValueError('编译并行数必须为整数')
    if not 1 <= jobs <= 64:
        raise ValueError('编译并行数范围为 1～64')
    command += ['--jobs', str(jobs)]
    for enabled, flag in ((bundle_only, '--bundle-only'), (options.frontend, '--with-frontend'),
                          (options.skip_build, '--skip-build'),
                          (options.initialize_baseline, '--initialize-ini-baseline')):
        if enabled:
            command.append(flag)
    for role in ('master', 'slave'):
        if getattr(options, role + '_enabled'):
            name = getattr(options, role + '_name').strip()
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', name):
                raise ValueError(('主机' if role == 'master' else '从机') + '名称须为 1～64 位字母、数字、点、下划线或连字符')
            command += ['--' + role + '-name', name]
    if options.slave_enabled:
        addresses = re.split(r'[,\s]+', options.slave_ips.strip())
        if not addresses or not addresses[0]:
            raise ValueError('迁移从机证书时须填写全部 IP 地址')
        for address in addresses:
            try:
                ipaddress.ip_address(address)
            except ValueError:
                raise ValueError('无效的从机 IP：' + address)
            command += ['--slave-ip', address]
    if options.trust_enabled:
        path = Path(options.certificate).expanduser()
        if not options.certificate.strip() or not path.is_file():
            raise ValueError('请选择可信主机公开证书文件')
        if path.stat().st_size > 1024 * 1024 or not path.read_bytes().lstrip().startswith(b'-----BEGIN CERTIFICATE-----'):
            raise ValueError('请选择 PEM 格式公开证书，不接受私钥文件')
        fingerprint = options.fingerprint.strip().replace(':', '')
        if not re.fullmatch(r'[0-9a-fA-F]{64}', fingerprint):
            raise ValueError('请输入可信渠道取得的完整 SHA-256 指纹')
        command += ['--trust-master', str(path.resolve()), '--trust-master-fingerprint', fingerprint.upper()]
    return command


def main():
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox
        from tkinter.scrolledtext import ScrolledText
    except ImportError:
        raise SystemExit('缺少 Tkinter。Ubuntu 开发机请安装：sudo apt install python3-tk')

    class Window:
        def __init__(self, root):
            self.root = root
            self.busy = False
            self.events = queue.Queue()
            self.logfile = None
            self.variables = {}
            defaults = Options()
            for field, value in vars(defaults).items():
                self.variables[field] = tk.BooleanVar(value=value) if isinstance(value, bool) else tk.StringVar(value=value)
            root.title('EM-1000 项目部署')
            root.geometry('980x850')
            root.minsize(820, 720)
            frame = ttk.Frame(root, padding=14)
            frame.pack(fill='both', expand=True)
            ttk.Label(frame, text='EM-1000 项目部署', font=('', 18, 'bold')).pack(anchor='w')
            ttk.Label(frame, text='升级已有工控机环境 · 使用 SSH 密钥 / ssh-agent · 复用部署脚本的备份与回滚').pack(anchor='w', pady=(3, 10))
            connection = ttk.LabelFrame(frame, text='目标与构建', padding=10)
            connection.pack(fill='x')
            ttk.Label(connection, text='SSH 地址').grid(row=0, column=0, sticky='w')
            ttk.Entry(connection, textvariable=self.variables['host'], width=35).grid(row=0, column=1, sticky='ew', padx=8)
            ttk.Label(connection, text='并行数').grid(row=0, column=2)
            ttk.Spinbox(connection, from_=1, to=64, textvariable=self.variables['jobs'], width=5).grid(row=0, column=3, padx=8)
            self.ssh_button = ttk.Button(connection, text='检查 SSH', command=self.check_ssh)
            self.ssh_button.grid(row=0, column=4)
            connection.columnconfigure(1, weight=1)
            switches = ttk.Frame(connection)
            switches.grid(row=1, column=0, columnspan=5, sticky='w', pady=(8, 0))
            for key, text in [('frontend', '同时更新前端'), ('skip_build', '复用已有构建产物'),
                              ('initialize_baseline', '仅在缺失时初始化 INI 基准')]:
                ttk.Checkbutton(switches, text=text, variable=self.variables[key]).pack(side='left', padx=(0, 12))
            certs = ttk.LabelFrame(frame, text='可选：首次迁移 / 更新证书（普通升级无需勾选）', padding=10)
            certs.pack(fill='x', pady=10)
            for row, role, label in [(0, 'master', '主机身份'), (1, 'slave', '从机身份')]:
                ttk.Checkbutton(certs, text=label, variable=self.variables[role + '_enabled']).grid(row=row, column=0, sticky='w')
                ttk.Label(certs, text='名称 CN').grid(row=row, column=1, padx=6)
                ttk.Entry(certs, textvariable=self.variables[role + '_name']).grid(row=row, column=2, sticky='ew', pady=3)
            ttk.Label(certs, text='从机全部 IP').grid(row=2, column=1, padx=6)
            ttk.Entry(certs, textvariable=self.variables['slave_ips']).grid(row=2, column=2, columnspan=2, sticky='ew', pady=3)
            ttk.Label(certs, text='多个地址以逗号或空格分隔；证书更新后可能需要更新对端信任。').grid(row=3, column=0, columnspan=4, sticky='w', pady=(5, 0))
            certs.columnconfigure(2, weight=1)
            trust = ttk.LabelFrame(frame, text='可选：导入可信主机公开证书', padding=10)
            trust.pack(fill='x')
            ttk.Checkbutton(trust, text='导入证书', variable=self.variables['trust_enabled']).grid(row=0, column=0, sticky='w')
            ttk.Entry(trust, textvariable=self.variables['certificate']).grid(row=0, column=1, sticky='ew', padx=8)
            ttk.Button(trust, text='选择文件', command=self.select_certificate).grid(row=0, column=2)
            ttk.Label(trust, text='SHA-256 指纹').grid(row=1, column=0, sticky='w', pady=(6, 0))
            ttk.Entry(trust, textvariable=self.variables['fingerprint']).grid(row=1, column=1, columnspan=2, sticky='ew', padx=8, pady=(6, 0))
            trust.columnconfigure(1, weight=1)
            actions = ttk.Frame(frame)
            actions.pack(fill='x', pady=12)
            self.deploy_button = ttk.Button(actions, text='开始部署', command=lambda: self.start(False))
            self.deploy_button.pack(side='left')
            self.package_button = ttk.Button(actions, text='只生成升级包', command=lambda: self.start(True))
            self.package_button.pack(side='left', padx=8)
            ttk.Button(actions, text='复制命令', command=self.copy_command).pack(side='left')
            ttk.Button(actions, text='保存当前日志', command=self.save_log).pack(side='right')
            self.status = tk.StringVar(value='就绪。首次连接请先在终端完成 SSH 主机确认及密钥认证。')
            ttk.Label(frame, textvariable=self.status).pack(anchor='w')
            self.progress = ttk.Progressbar(frame, mode='indeterminate')
            self.progress.pack(fill='x', pady=(5, 8))
            self.log = ScrolledText(frame, wrap='word', height=16, state='disabled', font=('monospace', 10))
            self.log.pack(fill='both', expand=True)
            root.protocol('WM_DELETE_WINDOW', self.close)
            root.after(100, self.poll)

        def options(self):
            return Options(**{key: value.get() for key, value in self.variables.items()})

        def append(self, text):
            self.log.configure(state='normal')
            self.log.insert('end', text)
            if int(self.log.index('end-1c').split('.')[0]) > 20000:
                self.log.delete('1.0', '1001.0')
            self.log.see('end')
            self.log.configure(state='disabled')

        def set_busy(self, value):
            self.busy = value
            for button in (self.deploy_button, self.package_button, self.ssh_button):
                button.configure(state='disabled' if value else 'normal')
            if value:
                self.progress.start(15)
            else:
                self.progress.stop()

        def select_certificate(self):
            path = filedialog.askopenfilename(title='选择可信主机公开证书', filetypes=[('PEM 证书', '*.crt *.pem'), ('所有文件', '*')])
            if path:
                self.variables['certificate'].set(path)
                self.variables['trust_enabled'].set(True)

        def copy_command(self):
            try:
                text = shlex.join(build_command(self.options()))
            except ValueError as exc:
                messagebox.showerror('参数错误', str(exc))
                return
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.status.set('已复制部署命令。')

        def save_log(self):
            path = filedialog.asksaveasfilename(title='保存部署日志', defaultextension='.log')
            if path:
                try:
                    Path(path).write_text(self.log.get('1.0', 'end-1c'), encoding='utf-8')
                except OSError as exc:
                    messagebox.showerror('日志保存失败', str(exc))

        def check_ssh(self):
            if self.busy:
                return
            try:
                host = validate_host(self.options().host)
            except ValueError as exc:
                messagebox.showerror('参数错误', str(exc))
                return
            self.launch(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', host,
                         'test "$(id -u)" -eq 0 && echo "SSH root authentication OK"'], 'SSH 检查')

        def start(self, bundle_only):
            if self.busy:
                return
            try:
                command = build_command(self.options(), bundle_only)
            except ValueError as exc:
                messagebox.showerror('参数错误', str(exc))
                return
            if not bundle_only:
                summary = ('目标：' + self.options().host + '\n\n将编译并替换程序，部署期间暂停 tems 和后端服务。\n'
                           '失败时脚本会尝试恢复原文件与服务。请在维护窗口操作。')
                if self.variables['master_enabled'].get() or self.variables['slave_enabled'].get():
                    summary += '\n\n已选择更新证书，请准备同步更新对端信任。'
                if not messagebox.askokcancel('确认开始部署', summary):
                    return
            self.launch(command, '生成升级包' if bundle_only else '部署')

        def launch(self, command, label):
            self.set_busy(True)
            self.status.set(label + '进行中，请等待完成。')
            self.append('\n[' + label + '] ' + shlex.join(command) + '\n')
            threading.Thread(target=self.worker, args=(command, label), daemon=True).start()

        def worker(self, command, label):
            path = None
            try:
                directory = ROOT / 'deploy/build-output/logs'
                directory.mkdir(parents=True, exist_ok=True)
                path = directory / (datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.log')
                env = dict(os.environ, PYTHONUNBUFFERED='1')
                with path.open('w', encoding='utf-8') as logfile:
                    logfile.write(shlex.join(command) + '\n')
                    process = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
                    for line in process.stdout:
                        logfile.write(line)
                        logfile.flush()
                        self.events.put(('text', line))
                    result = process.wait()
                self.events.put(('done', (label, result, str(path))))
            except Exception as exc:
                self.events.put(('text', '\n启动/执行失败：' + str(exc) + '\n'))
                self.events.put(('done', (label, -1, str(path or '未创建日志'))))

        def poll(self):
            for _ in range(300):
                try:
                    kind, value = self.events.get_nowait()
                except queue.Empty:
                    break
                if kind == 'text':
                    self.append(value)
                else:
                    label, result, path = value
                    self.set_busy(False)
                    message = label + ('完成' if result == 0 else '失败（退出码 %s）' % result)
                    self.status.set(message)
                    self.append('\n' + message + '\n日志：' + path + '\n')
                    if result != 0:
                        self.append('SSH 认证失败时，请先在终端执行 ssh root@设备IP 确认主机，并配置 SSH 密钥/ssh-agent。\n')
            self.root.after(100, self.poll)

        def close(self):
            if self.busy:
                messagebox.showinfo('任务执行中', '请等待任务完成后关闭，避免中断设备安装或回滚。')
                return
            self.root.destroy()

    root = tk.Tk()
    Window(root)
    root.mainloop()


if __name__ == '__main__':
    main()
