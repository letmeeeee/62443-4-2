"""Tkinter publisher GUI; network/crypto work never runs on the UI thread."""
from datetime import datetime
from pathlib import Path
import queue
import json
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
import webbrowser

from . import runner

MODES = {'正常加密发送':'normal', '重放：合法帧 + 重复帧':'replay', '篡改：仅错误 tag':'tamper',
         '篡改恢复：错误 tag + 原合法帧':'tamper-recover',
         '明文拒绝测试':'plaintext', 'HELLO 错误签名测试':'bad-signature'}


class Application:
    def __init__(self, root):
        self.root = root
        root.title('GOOSE 加密发布端测试工具')
        root.geometry('1120x900')
        root.minsize(900,720)
        self.messages = queue.Queue()
        self.stop_event = threading.Event()
        self.busy = False
        self.closing = False
        self.adapters = []
        self.saved_states = []
        self.fields = {}
        title = ttk.Frame(root,padding=12)
        title.pack(fill='x')
        ttk.Label(title,text='GOOSE 加密发布端',font=('',18,'bold')).pack(side='left')
        ttk.Button(title,text='Npcap 下载',command=lambda:webbrowser.open('https://npcap.com/#download')).pack(side='right')
        self.form = ttk.LabelFrame(root,text='连接与 PKI',padding=12)
        self.form.pack(fill='x',padx=12)
        self.form.columnconfigure(1,weight=1)
        ttk.Label(self.form,text='本机网卡 / IPv4 / MAC').grid(row=0,column=0,sticky='w',padx=4,pady=6)
        self.adapter_box = ttk.Combobox(self.form,state='readonly',width=90)
        self.adapter_box.grid(row=0,column=1,sticky='ew',padx=4)
        ttk.Button(self.form,text='刷新网卡',command=self.refresh_adapters).grid(row=0,column=2)
        self.field(1,'target','设备 net2 IPv4','192.168.2.136')
        for row,(name,label) in enumerate([('cert','本端证书 enc.crt'),('key','本端私钥 enc.key'),
                                           ('ca','CA 信任根 ca-roots.crt'),('crl','CRL crls.pem')],2):
            self.field(row,name,label,file=True)
        ttk.Button(self.form,text='选择 PKI 目录（自动填入四文件）',command=self.choose_directory).grid(row=6,column=1,sticky='w',pady=6)
        self.settings = ttk.LabelFrame(root,text='测试参数',padding=12)
        self.settings.pack(fill='x',padx=12,pady=8)
        tabs=ttk.Notebook(self.settings)
        tabs.pack(fill='x')
        basic=ttk.Frame(tabs,padding=6)
        advanced=ttk.Frame(tabs,padding=6)
        tabs.add(basic,text='常规发送')
        tabs.add(advanced,text='自定义报文 / 配置')
        basic.columnconfigure(1,weight=1)
        advanced.columnconfigure(1,weight=1)
        self.field(0,'values','8 个 int32 数据（逗号分隔）','0,0,0,0,0,0,0,0',parent=basic)
        row = ttk.Frame(basic)
        row.grid(row=1,column=0,columnspan=3,sticky='ew')
        for index,(name,label,default) in enumerate([('count','帧数','10'),('interval','间隔 / 秒','1')]):
            ttk.Label(row,text=label).grid(row=0,column=index*2,padx=5)
            self.fields[name] = tk.StringVar(value=default)
            ttk.Entry(row,textvariable=self.fields[name],width=10).grid(row=0,column=index*2+1,padx=5)
        ttk.Label(row,text='模式').grid(row=0,column=4,padx=5)
        self.mode = ttk.Combobox(row,state='readonly',values=list(MODES),width=30)
        self.mode.current(0)
        self.mode.grid(row=0,column=5,padx=5)
        self.change_state = tk.BooleanVar(value=False)
        ttk.Checkbutton(basic,text='每帧递增 stNum（用于连续业务转发；默认仅 sqNum 递增）',variable=self.change_state).grid(row=2,column=0,columnspan=3,sticky='w',pady=8)
        for row,(name,label,default) in enumerate([
            ('st_start','起始 stNum','1'),('sq_start','起始 sqNum','0'),
            ('appid','APPID（十进制或 0x 十六进制）','0x1000'),
            ('reference','goCbRef','TEMPLATEPIGO/LLN0$GO$gocb1'),
            ('destination','目的组播 MAC','01:0c:cd:01:00:00')],0):
            self.field(row,name,label,default,parent=advanced)
        self.use_custom = tk.BooleanVar(value=False)
        ttk.Checkbutton(advanced,text='逐帧编辑（JSON 数组，启用后覆盖帧数、起始计数和统一数据值）',variable=self.use_custom).grid(row=5,column=0,columnspan=3,sticky='w')
        self.frame_editor = scrolledtext.ScrolledText(advanced,height=4,wrap='none')
        self.frame_editor.grid(row=6,column=0,columnspan=3,sticky='ew')
        self.frame_editor.insert('1.0',json.dumps([
            dict(stNum=1,sqNum=0,values=[0]*8),dict(stNum=2,sqNum=0,values=[1]*8)],ensure_ascii=False,indent=2))
        config_buttons = ttk.Frame(advanced)
        config_buttons.grid(row=7,column=0,columnspan=3,sticky='w')
        ttk.Button(config_buttons,text='导入报文配置',command=self.import_config).pack(side='left',padx=4,pady=4)
        ttk.Button(config_buttons,text='导出报文配置',command=self.export_config).pack(side='left',padx=4,pady=4)
        ttk.Label(root,text='在隔离测试网络使用：合法数据可能触发 Modbus 写入。独立测试之间需停止发送并空闲超过 30 秒。').pack(anchor='w',padx=16,pady=4)
        controls = ttk.Frame(root,padding=10)
        controls.pack(fill='x')
        self.verify_button = ttk.Button(controls,text='校验本端 PKI',command=self.verify_pki)
        self.verify_button.pack(side='left',padx=4)
        self.start_button = ttk.Button(controls,text='开始测试',command=self.start)
        self.start_button.pack(side='left',padx=4)
        self.stop_button = ttk.Button(controls,text='停止',command=self.stop,state='disabled')
        self.stop_button.pack(side='left',padx=4)
        ttk.Button(controls,text='保存日志',command=self.save_log).pack(side='right',padx=4)
        self.status = tk.StringVar(value='就绪')
        ttk.Label(controls,textvariable=self.status).pack(side='left',padx=12)
        self.output = scrolledtext.ScrolledText(root,wrap='word',height=14,state='disabled')
        self.output.pack(fill='both',expand=True,padx=12,pady=(0,12))
        root.protocol('WM_DELETE_WINDOW',self.close)
        root.after(100,self.poll)
        self.log('选择本机物理有线网卡、设备 IP 和独立的发布端身份。Windows 需安装 Npcap，设备需放行 UDP 30001。')
        root.after(200,self.refresh_adapters)

    def field(self,row,name,label,default='',file=False,parent=None):
        parent = parent or self.form
        ttk.Label(parent,text=label).grid(row=row,column=0,sticky='w',padx=4,pady=5)
        value = tk.StringVar(value=default)
        self.fields[name] = value
        ttk.Entry(parent,textvariable=value,width=85).grid(row=row,column=1,sticky='ew',padx=4)
        if file:
            def choose():
                path = filedialog.askopenfilename(title=label)
                if path:
                    value.set(path)
            ttk.Button(parent,text='选择',command=choose).grid(row=row,column=2)

    def log(self,message):
        self.output.configure(state='normal')
        self.output.insert('end',datetime.now().strftime('[%H:%M:%S] ')+str(message)+'\n')
        if int(self.output.index('end-1c').split('.')[0]) > 10000:
            self.output.delete('1.0','1001.0')
        self.output.see('end')
        self.output.configure(state='disabled')

    def set_busy(self,value):
        self.busy = value
        if value:
            self.saved_states = []
            def disable(parent):
                for widget in parent.winfo_children():
                    if isinstance(widget,(ttk.Entry,ttk.Combobox,ttk.Button,ttk.Checkbutton,tk.Text)):
                        self.saved_states.append((widget,widget.cget('state')))
                        widget.configure(state='disabled')
                    disable(widget)
            disable(self.form)
            disable(self.settings)
        else:
            for widget,state in self.saved_states:
                widget.configure(state=state)
            self.saved_states = []
        self.start_button.configure(state='disabled' if value else 'normal')
        self.verify_button.configure(state='disabled' if value else 'normal')
        self.stop_button.configure(state='normal' if value else 'disabled')

    def work(self,function,kind):
        if self.busy:
            return
        self.stop_event.clear()
        self.set_busy(True)
        self.status.set('正在处理…')
        def execute():
            try:
                self.messages.put(('done',kind,function()))
            except Exception as error:
                self.messages.put(('error',kind,str(error)))
        threading.Thread(target=execute,daemon=True).start()

    def choose_directory(self):
        directory = filedialog.askdirectory(title='选择发布端 PKI 文件目录')
        if not directory:
            return
        paths = {name:Path(directory)/filename for name,filename in [('cert','enc.crt'),('key','enc.key'),('ca','ca-roots.crt'),('crl','crls.pem')]}
        missing = [path.name for path in paths.values() if not path.is_file()]
        if missing:
            messagebox.showerror('文件不完整','缺少：'+', '.join(missing))
            return
        for name,path in paths.items():
            self.fields[name].set(str(path))

    def data(self):
        values = {name:value.get().strip() for name,value in self.fields.items()}
        values.update(mode=MODES[self.mode.get()],change_state=self.change_state.get())
        values['custom_frames'] = self.frame_editor.get('1.0','end-1c') if self.use_custom.get() else ''
        if self.use_custom.get() and not values['custom_frames'].strip():
            raise ValueError('逐帧报文列表不能为空')
        for name in ('cert','key','ca','crl'):
            path = Path(values[name])
            if not values[name] or not path.is_file() or path.stat().st_size > 1024*1024:
                raise ValueError(name+' 请选择不超过 1 MiB 的文件')
        return values

    def packet_config(self):
        names = ('count','interval','values','st_start','sq_start','appid','reference','destination')
        data = {name:self.fields[name].get().strip() for name in names}
        data.update(mode=MODES[self.mode.get()],change_state=self.change_state.get(),
                    custom_frames=self.frame_editor.get('1.0','end-1c') if self.use_custom.get() else '')
        runner.validate(dict(data,target='192.168.2.136'))
        return dict(format='goose-publisher-config-v1',**data)

    def export_config(self):
        try:
            data = self.packet_config()
            path = filedialog.asksaveasfilename(title='导出报文配置（不含 PKI）',defaultextension='.json')
            if path:
                Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
                self.log('已导出报文配置：'+path)
        except Exception as error:
            messagebox.showerror('导出失败',str(error))

    def import_config(self):
        path = filedialog.askopenfilename(title='导入报文配置',filetypes=[('JSON','*.json')])
        if not path:
            return
        try:
            if Path(path).stat().st_size > 4*1024*1024:
                raise ValueError('配置文件不能超过 4 MiB')
            data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
            if not isinstance(data,dict) or data.get('format') != 'goose-publisher-config-v1':
                raise ValueError('不支持的报文配置格式')
            names = ('count','interval','values','st_start','sq_start','appid','reference','destination')
            if any(not isinstance(data.get(name),str) for name in names) or type(data.get('change_state')) is not bool or not isinstance(data.get('custom_frames'),str):
                raise ValueError('报文配置字段不完整或类型错误')
            runner.validate(dict(data,target='192.168.2.136'))
            for name in names:
                self.fields[name].set(data[name])
            self.mode.set(next(label for label,mode in MODES.items() if mode == data['mode']))
            self.change_state.set(data['change_state'])
            self.use_custom.set(bool(data['custom_frames'].strip()))
            self.frame_editor.delete('1.0','end')
            self.frame_editor.insert('1.0',data['custom_frames'])
            self.log('已导入报文配置：'+path)
        except Exception as error:
            messagebox.showerror('导入失败',str(error))

    def refresh_adapters(self):
        self.work(lambda:runner.adapters(log=lambda message:self.messages.put(('log','',message))),'adapters')

    def verify_pki(self):
        try:
            data = self.data()
        except Exception as error:
            messagebox.showerror('参数错误',str(error)); return
        def verify():
            from .protocol import Publisher
            from .trust import verify_certificate
            Publisher(*(data[name] for name in ('cert','key','ca','crl')),verifier=verify_certificate)
            return '本端证书为 P-256，私钥匹配，证书链与 CRL 校验通过。'
        self.work(verify,'verify')

    def start(self):
        try:
            index = self.adapter_box.current()
            if index < 0:
                raise ValueError('请先选择本机网卡')
            adapter = self.adapters[index]
            data = self.data()
            runner.validate(data)
        except Exception as error:
            messagebox.showerror('参数错误',str(error)); return
        if not messagebox.askyesno('确认发送测试数据','目标：'+data['target']+'\n网卡：'+adapter.label+'\nAPPID：'+data['appid']+'\ngoCbRef：'+data['reference']+'\n目的 MAC：'+data['destination']+'\n报文数：'+str(len(runner.frame_plan(data)))+'\n合法数据可能触发设备 Modbus 写入，确认在测试环境发送？'):
            return
        self.work(lambda:runner.run(data,adapter,self.stop_event,lambda message:self.messages.put(('log','',message))),'run')

    def stop(self):
        self.stop_event.set()
        self.status.set('正在停止…')

    def save_log(self):
        path = filedialog.asksaveasfilename(defaultextension='.log',initialfile='goose-publisher.log')
        if path:
            try:
                Path(path).write_text(self.output.get('1.0','end-1c'),encoding='utf-8')
            except OSError as error:
                messagebox.showerror('保存失败',str(error))

    def poll(self):
        try:
            for _ in range(100):
                event,kind,result = self.messages.get_nowait()
                if event == 'log':
                    self.log(result)
                    continue
                self.set_busy(False)
                if event == 'error':
                    if kind == 'adapters':
                        self.adapters = []
                        self.adapter_box.configure(values=[])
                        self.adapter_box.set('')
                    self.status.set('失败')
                    self.log('失败：'+result)
                    if not self.closing:
                        messagebox.showerror('操作失败',result)
                elif kind == 'adapters':
                    self.adapters = result
                    self.adapter_box.configure(values=[item.label for item in result])
                    if result:
                        self.adapter_box.current(0)
                    else:
                        self.adapter_box.set('')
                    self.status.set('发现 %d 个 IPv4 网卡地址' % len(result))
                else:
                    self.status.set({'stopped':'已停止','finished':'发送完成','negative-unconfirmed':'待设备日志确认'}.get(result,'完成'))
                    self.log(result if kind == 'verify' else self.status.get()+'；请对照设备认证、拒绝和 Modbus 日志。')
        except queue.Empty:
            pass
        if self.closing and not self.busy:
            self.root.destroy()
            return
        self.root.after(100,self.poll)

    def close(self):
        if self.busy:
            if messagebox.askyesno('停止后退出','正在测试，是否停止并等待当前操作结束后退出？'):
                self.closing = True
                self.stop()
        else:
            self.root.destroy()


def main():
    root = tk.Tk()
    Application(root)
    root.mainloop()


if __name__ == '__main__':
    main()
