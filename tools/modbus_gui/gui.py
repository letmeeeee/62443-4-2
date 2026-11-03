"""Tkinter GUI. All network and certificate generation work runs off the UI thread."""
import argparse
from datetime import datetime
import math
from pathlib import Path
import queue
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import certificates
from .core import RegisterBank, Server, exchange, request_pdu, tls_context


def integer(text):
    text = text.strip()
    return int(text, 16 if text.lower().startswith('0x') else 10)


def values(text):
    return [integer(word) for word in re.split(r'[,，;；\s]+', text.strip()) if word]


class Window:
    def __init__(self, root, role='client'):
        self.root = root
        self.events = queue.Queue()
        self.server = None
        self.bank = RegisterBank()
        self.fields = {}
        self.client_busy = False
        self.loop_running = False
        self.loop_timer = None
        self.loop_count = self.loop_success = self.loop_failure = 0
        root.title('Modbus TLS 客户端 / 服务端')
        root.geometry('1080x850')
        root.minsize(900, 720)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.split = tk.PanedWindow(root, orient='vertical', sashwidth=8, sashrelief='raised', borderwidth=0)
        self.split.pack(fill='both', expand=True, padx=10, pady=8)
        self.tabs = ttk.Notebook(self.split)
        self.split.add(self.tabs, height=550, minsize=300, stretch='always')
        for name, label in [('client', 'Modbus 客户端'), ('server', 'Modbus 服务端')]:
            tab = self.scroll_tab(label)
            self.build_role(tab, name)
        self.tabs.select(0 if role == 'client' else 1)
        cert_tab = self.scroll_tab('证书管理 / 快速联调')
        self.build_certificates(cert_tab)
        log_panel = ttk.Frame(self.split)
        self.split.add(log_panel, height=260, minsize=180, stretch='always')
        toolbar = ttk.Frame(log_panel)
        toolbar.pack(fill='x', pady=4)
        ttk.Label(toolbar, text='TX 发送 / RX 接收完整报文（ADU = MBAP + PDU，拖动上方分隔条调整高度）').pack(side='left')
        ttk.Button(toolbar, text='清空日志', command=self.clear_log).pack(side='right')
        ttk.Button(toolbar, text='复制全部', command=lambda: self.copy_log(all_text=True)).pack(side='right', padx=4)
        self.logbox = ScrolledText(log_panel, height=12, state='disabled', wrap='word',
                                   exportselection=False, takefocus=True, font=('TkFixedFont', 10))
        self.logbox.pack(fill='both', expand=True)
        self.logbox.tag_configure('TX', foreground='#0056A6')
        self.logbox.tag_configure('RX', foreground='#137333')
        self.logbox.bind('<Button-1>', lambda event: self.logbox.focus_set())
        self.logbox.bind('<<Copy>>', self.copy_log)
        for key in ('<Control-c>', '<Control-C>'):
            self.logbox.bind(key, self.copy_log)
        for key in ('<Control-a>', '<Control-A>'):
            self.logbox.bind(key, self.select_log)
        if root.tk.call('tk', 'windowingsystem') == 'aqua':
            self.logbox.bind('<Command-c>', self.copy_log)
            self.logbox.bind('<Command-a>', self.select_log)
        self.log_menu = tk.Menu(self.logbox, tearoff=False)
        self.log_menu.add_command(label='复制所选', command=self.copy_log)
        self.log_menu.add_command(label='全选', command=self.select_log)
        self.log_menu.add_command(label='复制全部', command=lambda: self.copy_log(all_text=True))
        self.logbox.bind('<Button-3>', self.log_context_menu)
        if root.tk.call('tk', 'windowingsystem') == 'aqua':
            self.logbox.bind('<Button-2>', self.log_context_menu)
        root.after(80, self.drain)

    def copy_log(self, event=None, all_text=False):
        if all_text:
            text = self.logbox.get('1.0', 'end-1c')
        else:
            if not self.logbox.tag_ranges('sel'):
                return 'break'
            text = self.logbox.get('sel.first', 'sel.last')
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
        return 'break'

    def select_log(self, event=None):
        self.logbox.focus_set()
        self.logbox.tag_add('sel', '1.0', 'end-1c')
        return 'break'

    def log_context_menu(self, event):
        self.logbox.focus_set()
        self.log_menu.entryconfigure(0, state='normal' if self.logbox.tag_ranges('sel') else 'disabled')
        try:
            self.log_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.log_menu.grab_release()
        return 'break'

    def scroll_tab(self, label):
        tab = ttk.Frame(self.tabs)
        self.tabs.add(tab, text=label)
        canvas = tk.Canvas(tab, highlightthickness=0)
        scrollbar = ttk.Scrollbar(tab, orient='vertical', command=canvas.yview)
        scrollbar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        content = ttk.Frame(canvas, padding=10)
        item = canvas.create_window(0, 0, window=content, anchor='nw')
        content.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(item, width=event.width))
        return content

    def clear_log(self):
        self.logbox.configure(state='normal')
        self.logbox.delete('1.0', 'end')
        self.logbox.configure(state='disabled')

    def log(self, text):
        # Capture the event time in the network thread, before UI queue delays.
        self.events.put(('log', (datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3], str(text))))

    def drain(self):
        for _ in range(200):
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'log':
                timestamp, payload = payload
                self.logbox.configure(state='normal')
                direction = payload.split(' ', 1)[0]
                tags = (direction,) if direction in ('TX', 'RX') else ()
                self.logbox.insert('end', timestamp + ' ' + payload + '\n\n', tags)
                if int(self.logbox.index('end-1c').split('.')[0]) > 1500:
                    self.logbox.delete('1.0', '300.0')
                self.logbox.see('end')
                self.logbox.configure(state='disabled')
            else:
                payload()
        self.root.after(80, self.drain)

    def work(self, action, done=None, button=None, on_error=None, finished=None):
        if button:
            button.configure(state='disabled')
        def run():
            try:
                result = action()
                if done:
                    self.events.put(('ui', lambda result=result: done(result)))
            except Exception as exc:
                self.log('失败：' + str(exc))
                if on_error:
                    self.events.put(('ui', lambda text=str(exc): on_error(text)))
                else:
                    self.events.put(('ui', lambda text=str(exc): messagebox.showerror('操作失败', text)))
            finally:
                if button:
                    self.events.put(('ui', lambda: button.configure(state='normal')))
                if finished:
                    self.events.put(('ui', finished))
        threading.Thread(target=run, daemon=True).start()

    def field(self, frame, row, label, default='', password=False):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky='w', padx=4, pady=3)
        variable = tk.StringVar(value=default)
        ttk.Entry(frame, textvariable=variable, show='*' if password else '').grid(row=row, column=1, sticky='ew', padx=4, pady=3)
        frame.columnconfigure(1, weight=1)
        return variable

    def cert_field(self, frame, row, role, key, label):
        variable = self.field(frame, row, label)
        self.fields[role][key] = variable
        def select():
            path = filedialog.askopenfilename(title=label, filetypes=[('PEM / 证书 / 私钥', '*.pem *.crt *.cer *.key'), ('所有文件', '*')])
            if path:
                variable.set(path)
                self.log('已导入配置：' + path)
        ttk.Button(frame, text='导入…', command=select).grid(row=row, column=2, padx=3)
        if key != 'key':
            ttk.Button(frame, text='导出…', command=lambda: self.export(variable.get())).grid(row=row, column=3, padx=3)
            ttk.Button(frame, text='查看', command=lambda: self.show_certificate(variable.get())).grid(row=row, column=4, padx=3)

    def build_role(self, tab, role):
        self.fields[role] = f = {}
        connection = ttk.LabelFrame(tab, text='TLS 连接设置', padding=5)
        connection.pack(fill='x')
        f['host'] = self.field(connection, 0, '目标 IP / DNS' if role == 'client' else '监听 IPv4', '127.0.0.1')
        f['port'] = self.field(connection, 1, '端口', '18020')
        f['unit'] = self.field(connection, 2, '站号（Unit ID）', '1')
        self.cert_field(connection, 3, role, 'cert', '本端身份证书（PEM）')
        self.cert_field(connection, 4, role, 'key', '本端私钥（PEM）')
        self.cert_field(connection, 5, role, 'ca', '可信 CA / 对端自签证书')
        f['password'] = self.field(connection, 6, '私钥密码（未加密时留空）', password=True)
        f['mutual'] = tk.BooleanVar(value=True)
        ttk.Checkbutton(connection, text='发送客户端证书' if role == 'client' else '验证客户端证书（要求客户端出示证书）',
                        variable=f['mutual']).grid(row=7, column=1, sticky='w')
        if role == 'client':
            f['verify_peer'] = tk.BooleanVar(value=True)
            ttk.Checkbutton(connection, text='验证服务端证书（取消后跳过证书链和名称校验，仍使用 TLS）',
                            variable=f['verify_peer']).grid(row=8, column=1, sticky='w')
            f['server_name'] = self.field(connection, 9, '验证服务端名称（留空使用目标 IP / DNS）')
            f['timeout'] = self.field(connection, 10, '连接 / 收包超时（秒，最大 120）', '5')
        else:
            controls = ttk.Frame(tab)
            controls.pack(fill='x', pady=6)
            self.start_button = ttk.Button(controls, text='启动服务端', command=self.start_server)
            self.start_button.pack(side='left', padx=4)
            self.stop_button = ttk.Button(controls, text='停止服务端', command=self.stop_server, state='disabled')
            self.stop_button.pack(side='left', padx=4)
            self.status = tk.StringVar(value='已停止；每个连接空闲超时 5 秒')
            ttk.Label(controls, textvariable=self.status).pack(side='left', padx=12)
        registers = ttk.LabelFrame(tab, text='寄存器操作：零起始地址；数值支持十进制 / 0x 十六进制', padding=5)
        registers.pack(fill='x', pady=5)
        f['function'] = tk.StringVar(value='03 保持寄存器')
        choices = ['03 保持寄存器', '04 输入寄存器']
        if role == 'client':
            choices += ['06 写单个保持寄存器', '16 写多个保持寄存器']
        ttk.Label(registers, text='功能 / 数据区').grid(row=0, column=0, sticky='w')
        ttk.Combobox(registers, values=choices, state='readonly', textvariable=f['function']).grid(row=0, column=1, sticky='ew')
        f['address'] = self.field(registers, 1, '起始地址', '0')
        f['count'] = self.field(registers, 2, '读取数量（1～125）', '10')
        f['values'] = self.field(registers, 3, '写入值（空格或逗号分隔，写入数量由值决定）', '123, 456')
        button = ttk.Button(registers, text='发送请求' if role == 'client' else '刷新寄存器',
                            command=lambda: self.read_or_send(role))
        button.grid(row=4, column=1, sticky='w', pady=3)
        if role == 'client':
            self.send_button = button
            loop_controls = ttk.Frame(registers)
            loop_controls.grid(row=5, column=0, columnspan=3, sticky='ew', pady=5)
            ttk.Label(loop_controls, text='循环间隔（毫秒）').pack(side='left')
            self.loop_interval = tk.StringVar(value='1000')
            ttk.Entry(loop_controls, textvariable=self.loop_interval, width=10).pack(side='left', padx=5)
            self.loop_start_button = ttk.Button(loop_controls, text='开始循环', command=self.start_loop)
            self.loop_start_button.pack(side='left', padx=4)
            self.loop_stop_button = ttk.Button(loop_controls, text='停止循环', command=self.stop_loop, state='disabled')
            self.loop_stop_button.pack(side='left', padx=4)
            self.loop_status = tk.StringVar(value='未循环')
            ttk.Label(loop_controls, textvariable=self.loop_status).pack(side='left', padx=6)
        else:
            ttk.Button(registers, text='设置本地寄存器值', command=self.edit_bank).grid(row=4, column=2)
        result = tk.StringVar(value='结果将在这里显示；服务端初始寄存器全部为 0。')
        f['result'] = result
        ttk.Label(tab, textvariable=result, wraplength=980, justify='left').pack(fill='x', pady=6)

    def snapshot(self, role):
        return {key: variable.get() for key, variable in self.fields[role].items()}

    def context(self, role, settings):
        return tls_context(role == 'server', settings['cert'], settings['key'], settings['ca'],
                           settings['mutual'], settings['password'], verify_peer=settings.get('verify_peer', True))

    def read_or_send(self, role):
        if role == 'client':
            if not self.client_busy and not self.loop_running:
                self.send_client(self.snapshot(role))
            return
        settings = self.snapshot(role)
        self.work(lambda: self.perform_request(role, settings), lambda result: self.fields[role]['result'].set(result))

    def perform_request(self, role, settings):
        function = int(settings['function'][:2])
        address = integer(settings['address'])
        if role == 'server':
            data = self.bank.snapshot(function, address, integer(settings['count']))
        else:
            data = exchange(self.context(role, settings), settings['host'].strip(), integer(settings['port']),
                            integer(settings['unit']), function, address,
                            integer(settings['count']), values(settings['values']),
                            float(settings['timeout']), settings['server_name'].strip(), self.log)
        return '成功：' + '  '.join('{}={} (0x{:04X})'.format(address + i, value, value) for i, value in enumerate(data))

    def client_buttons(self):
        state = 'disabled' if self.client_busy or self.loop_running else 'normal'
        self.send_button.configure(state=state)
        self.loop_start_button.configure(state=state)
        self.loop_stop_button.configure(state='normal' if self.loop_running else 'disabled')

    def send_client(self, settings, cycling=False):
        self.client_busy = True
        self.client_buttons()
        if cycling:
            self.loop_count += 1
        def done(result):
            self.fields['client']['result'].set(result)
            if cycling:
                self.loop_success += 1
        def failed(text):
            if cycling:
                self.loop_failure += 1
                self.fields['client']['result'].set('失败：' + text)
            else:
                messagebox.showerror('操作失败', text)
        def finished():
            self.client_busy = False
            if cycling:
                prefix = '循环中' if self.loop_running else '已停止'
                self.loop_status.set('{}：发送 {} / 成功 {} / 失败 {}'.format(
                    prefix, self.loop_count, self.loop_success, self.loop_failure))
                if self.loop_running:
                    self.loop_timer = self.root.after(self.loop_delay, self.loop_tick)
            self.client_buttons()
        self.work(lambda: self.perform_request('client', settings), done, on_error=failed, finished=finished)

    def start_loop(self):
        if self.client_busy or self.loop_running:
            return
        try:
            delay = integer(self.loop_interval.get())
            if not 10 <= delay <= 3600000:
                raise ValueError('循环间隔范围为 10～3600000 毫秒')
            settings = self.snapshot('client')
            timeout = float(settings['timeout'])
            if not settings['host'].strip() or not 1 <= integer(settings['port']) <= 65535 or not 0 <= integer(settings['unit']) <= 255:
                raise ValueError('检查目标地址、端口及站号')
            if not math.isfinite(timeout) or not 0 < timeout <= 120:
                raise ValueError('超时必须大于 0 且不超过 120 秒')
            request_pdu(int(settings['function'][:2]), integer(settings['address']),
                        integer(settings['count']), values(settings['values']))
        except ValueError as exc:
            messagebox.showerror('参数错误', str(exc))
            return
        self.loop_settings, self.loop_delay = settings, delay
        self.loop_count = self.loop_success = self.loop_failure = 0
        self.loop_running = True
        self.loop_status.set('循环中')
        self.log('开始循环发送：每次请求结束后等待 {} 毫秒；使用启动时的参数'.format(delay))
        self.loop_tick()

    def loop_tick(self):
        self.loop_timer = None
        if self.loop_running:
            self.send_client(self.loop_settings, cycling=True)

    def stop_loop(self):
        was_running = self.loop_running
        self.loop_running = False
        if self.loop_timer is not None:
            self.root.after_cancel(self.loop_timer)
            self.loop_timer = None
        if was_running:
            text = '已停止循环；当前请求完成或超时后结束' if self.client_busy else '已停止循环'
            self.loop_status.set(text)
            self.log(text)
        self.client_buttons()

    def edit_bank(self):
        try:
            f = self.snapshot('server')
            data = values(f['values'])
            self.bank.edit(int(f['function'][:2]), integer(f['address']), data)
            self.log('已更新本地寄存器：起始地址 {}，值 {}'.format(f['address'], data))
            self.read_or_send('server')
        except ValueError as exc:
            messagebox.showerror('参数错误', str(exc))

    def start_server(self):
        settings = self.snapshot('server')
        if self.server:
            return
        def action():
            port = integer(settings['port'])
            if not 1 <= port <= 65535:
                raise ValueError('端口范围 1～65535')
            server = Server(self.context('server', settings), settings['host'].strip(), port,
                            integer(settings['unit']), self.bank, self.log)
            server.start()
            return server
        self.start_button.configure(state='disabled')
        def done(server):
            self.server = server
            self.status.set('正在监听 {}:{}'.format(server.host, server.port))
            self.stop_button.configure(state='normal')
        def guarded():
            try:
                return action()
            except Exception:
                self.events.put(('ui', lambda: self.start_button.configure(state='normal')))
                raise
        self.work(guarded, done)

    def stop_server(self):
        if not self.server:
            return
        server = self.server
        def done(_):
            self.server = None
            self.status.set('已停止')
            self.start_button.configure(state='normal')
            self.stop_button.configure(state='disabled')
        self.stop_button.configure(state='disabled')
        self.work(server.stop, done)

    def build_certificates(self, tab):
        ttk.Label(tab, text='默认生成适配 EMS 的直接自签身份证书（CA:FALSE，有效期 365 天）。\n客户端 client.crt 可供设备 modbus_certs.py trust-add 导入；两端直接信任对端证书。\n取消下方设备模式，可生成 CA 签发的通用联调证书。\n客户端可分别设置“发送客户端证书”和“验证服务端证书”；服务端可设置“验证客户端证书”。',
                  justify='left', wraplength=930).pack(anchor='w', pady=10)
        box = ttk.Frame(tab)
        box.pack(fill='x')
        self.san = self.field(box, 0, '服务端证书 SAN（实际连接 IP / DNS）', '127.0.0.1')
        self.device_certificates = tk.BooleanVar(value=True)
        ttk.Checkbutton(tab, text='EMS 设备模式：直接自签证书（适用于 trust-add）',
                        variable=self.device_certificates).pack(anchor='w', pady=5)
        button = ttk.Button(tab, text='生成联调证书并配置两端…')
        button.configure(command=lambda: self.generate(button))
        button.pack(anchor='w', pady=12)
        ttk.Label(tab, text='本地联调：生成证书 → 服务端启动 → 客户端发送请求。\n连接实际设备：把 client.crt 导入设备信任列表，把设备 slave.crt 导入客户端信任栏。\n生成目录包含未加密私钥，请妥善保管。修改证书设置后需重启服务端。\n服务端仅操作内存中的模拟寄存器；关闭程序后寄存器数据不保存。',
                  justify='left', wraplength=930).pack(anchor='w', pady=10)

    def generate(self, button):
        parent = filedialog.askdirectory(title='选择证书保存位置（会新建独立子目录）')
        if not parent:
            return
        host = self.san.get()
        device_mode = self.device_certificates.get()
        def done(folder):
            for role in ('client', 'server'):
                trust = ('server.crt' if role == 'client' else 'client.crt') if device_mode else 'ca.crt'
                for key, path in [('cert', folder / (role + '.crt')), ('key', folder / (role + '.key')), ('ca', folder / trust)]:
                    self.fields[role][key].set(str(path))
                self.fields[role]['password'].set('')
                self.fields[role]['mutual'].set(True)
            self.fields['client']['host'].set(host.strip())
            self.fields['client']['server_name'].set('')
            self.log('联调证书已生成并配置：' + str(folder))
            messagebox.showinfo('证书已生成', '保存目录：' + str(folder) + '\n现在可以启动服务端并发送请求。')
        generate = certificates.generate_device if device_mode else certificates.generate_demo
        self.work(lambda: generate(parent, host), done, button)

    def export(self, source):
        if not source:
            messagebox.showerror('缺少证书', '请先导入或生成证书')
            return
        target = filedialog.asksaveasfilename(title='导出公开证书', initialfile=Path(source).name, defaultextension='.crt')
        if target:
            self.work(lambda: certificates.export_certificate(source, target), lambda _: self.log('已导出：' + target))

    def show_certificate(self, path):
        if path:
            self.work(lambda: certificates.inspect(path), lambda text: messagebox.showinfo('证书信息', text))

    def close(self):
        self.stop_loop()
        if self.server:
            self.server.stop()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description='Modbus TLS 桌面客户端 / 服务端')
    parser.add_argument('--role', choices=['client', 'server'], default='client')
    args = parser.parse_args()
    root = tk.Tk()
    Window(root, args.role)
    root.mainloop()
