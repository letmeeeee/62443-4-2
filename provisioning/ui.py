"""Small Tk task runner: long key generation and device operations run off the UI thread."""
import json
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk


class Window:
    def __init__(self, title):
        self.root = tk.Tk()
        self.root.title(title)
        self.root.geometry('1040x760')
        self.form = ttk.Frame(self.root, padding=12); self.form.pack(fill='x')
        self.buttons = ttk.Frame(self.root, padding=8); self.buttons.pack(fill='x')
        self.output = tk.Text(self.root, wrap='word'); self.output.pack(fill='both', expand=True, padx=12, pady=8)
        self.fields = {}
        self.secret_fields = set()
        self.form_rows = {}
        self.queue = queue.Queue()
        self.busy = False
        self.on_success = None
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.after(100, self.poll)

    def close(self):
        if self.busy:
            messagebox.showinfo('操作进行中', '请等待当前操作完成，避免中断签发或部署。')
        else:
            self.root.destroy()

    def field(self, key, label, default='', directory=False, file=False, secret=False, parent=None):
        parent = parent or self.form
        row = self.form_rows.get(parent, 0)
        self.form_rows[parent] = row + 1
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky='w', pady=4)
        value = tk.StringVar(value=default)
        ttk.Entry(parent, textvariable=value, width=90, show='*' if secret else '').grid(row=row, column=1, sticky='ew')
        if directory or file:
            def select():
                result = filedialog.askdirectory() if directory else filedialog.askopenfilename()
                if result: value.set(result)
            ttk.Button(parent, text='选择', command=select).grid(row=row, column=2)
        parent.columnconfigure(1, weight=1)
        self.fields[key] = value
        if secret: self.secret_fields.add(key)

    def values(self):
        return {k:v.get() if k in self.secret_fields else v.get().strip() for k,v in self.fields.items()}

    def button(self, label, command):
        ttk.Button(self.buttons, text=label, command=command).pack(side='left', padx=3, pady=4)

    def password(self, confirm=False):
        value = simpledialog.askstring('CA 口令', '输入 CA 私钥加密口令：', show='*', parent=self.root)
        if value is None: return None
        if confirm and value != simpledialog.askstring('确认口令', '再次输入口令：', show='*', parent=self.root):
            messagebox.showerror('错误', '两次口令不一致'); return None
        return value

    def task(self, function, on_success=None):
        if self.busy:
            messagebox.showinfo('请稍候', '已有操作正在执行。'); return
        self.busy = True
        self.on_success = on_success
        self.output.insert('end', '\n操作开始……\n'); self.output.see('end')
        def work():
            try: self.queue.put((True, function()))
            except Exception as exc: self.queue.put((False, str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            success, result = self.queue.get_nowait()
            self.busy = False
            callback, self.on_success = self.on_success, None
            if success and callback is not None:
                try: result = callback(result)
                except Exception as exc: success, result = False, str(exc)
            rendered = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2)
            self.output.insert('end', ('成功：\n' if success else '失败：\n') + rendered + '\n')
            self.output.see('end')
            if not success: messagebox.showerror('操作失败', rendered)
        except queue.Empty: pass
        self.root.after(100, self.poll)

    def run(self):
        self.root.mainloop()
