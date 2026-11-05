"""CA GUI password controls. Secret task results are consumed before output rendering."""
from pathlib import Path

from .ca import CertificateAuthority
from .passwords import generate_password, load_for_ca, save_password
from .ui import tk, ttk, filedialog, messagebox, simpledialog


class PasswordPanel:
    def __init__(self, window):
        self.window = window
        self.secret = None
        self.directory = None
        frame = ttk.Frame(window.root, padding=8)
        frame.pack(before=window.buttons, fill='x')
        self.status = tk.StringVar(value='CA 口令：未载入；操作时可手动输入')
        for title, operation in [('生成并加密保存','generate'),('保存现有 CA 口令','save'),('读取口令文件','load'),('查看已载入口令','show'),('清除会话口令','clear')]:
            ttk.Button(frame, text=title, command=lambda k=operation:self.action(k)).pack(side='left', padx=3)
        ttk.Label(window.form, textvariable=self.status).grid(row=len(window.fields),column=0,columnspan=3,sticky='w',pady=5)
        window.fields['ca'].trace_add('write',lambda *_:self.clear())

    def clear(self):
        self.secret = self.directory = None
        self.status.set('CA 口令：未载入；操作时可手动输入')

    def get(self, confirm=False):
        directory = str(Path(self.window.values()['ca']).resolve())
        if self.directory == directory and self.secret is not None:
            return self.secret
        return self.window.password(confirm=confirm)

    def protection(self, confirm=False):
        value = simpledialog.askstring('口令文件保护', '输入独立的文件保护口令（至少12位，与CA口令不同）：',show='*',parent=self.window.root)
        if value is None: return None
        if confirm and value != simpledialog.askstring('确认保护口令','再次输入文件保护口令：',show='*',parent=self.window.root):
            messagebox.showerror('口令不一致','两次保护口令不一致'); return None
        return value

    def action(self, kind):
        w = self.window
        if w.busy: return
        ca = CertificateAuthority(w.values()['ca'])
        directory = str(ca.directory.resolve())
        if kind == 'clear': self.clear(); return
        if kind == 'show':
            if self.directory != directory or self.secret is None:
                messagebox.showinfo('未载入口令','请先生成并保存，或读取已有口令文件。'); return
            dialog = tk.Toplevel(w.root); dialog.title('CA 口令（请妥善保管）')
            dialog.transient(w.root); dialog.grab_set()
            ttk.Label(dialog,text='口令仅在此窗口查看，不写入操作日志。').pack(padx=16,pady=8)
            entry = ttk.Entry(dialog, width=65, show='*'); entry.insert(0,self.secret)
            entry.configure(state='readonly'); entry.pack(padx=16,pady=8)
            visible = tk.BooleanVar(value=False)
            ttk.Checkbutton(dialog,text='显示口令',variable=visible,command=lambda:entry.configure(show='' if visible.get() else '*')).pack()
            ttk.Button(dialog,text='关闭',command=dialog.destroy).pack(pady=12)
            return
        if kind == 'generate' and ca.database.exists():
            messagebox.showerror('已有 CA','随机生成用于新建 CA，不会更改已有 CA 私钥口令。请使用“保存现有 CA 口令”。'); return
        if kind == 'load':
            path = filedialog.askopenfilename(title='读取加密 CA 口令文件',filetypes=[('CA 口令文件','*.lcvault'),('全部文件','*')])
            if not path: return
            protection = self.protection()
            if protection is None: return
            def work(): return load_for_ca(path, protection, ca)
        else:
            password = generate_password() if kind == 'generate' else self.get(confirm=True)
            if password is None: return
            path = filedialog.asksaveasfilename(title='保存加密 CA 口令（请选择 CA 数据目录之外的新文件）',
                defaultextension='.lcvault',initialfile=ca.directory.name+'-password.lcvault',
                filetypes=[('CA 口令文件','*.lcvault')])
            if not path: return
            protection = self.protection(confirm=True)
            if protection is None: return
            def work():
                if ca.database.exists(): ca.unlock(password)
                save_password(path,password,protection,ca.directory)
                return password
        # Do not display a raw secret returned by the background thread.
        def loaded(password):
            if str(Path(w.values()['ca']).resolve()) != directory:
                self.clear()
                return '口令文件操作成功，但 CA 目录已变化；请重新选择目录并读取。'
            self.secret, self.directory = password, directory
            self.status.set('CA 口令：已载入当前会话；文件保护口令不保存')
            return 'CA 口令已加密保存并载入。' if kind != 'load' else 'CA 口令已解密并载入；现有 CA 已验证私钥口令。' if ca.database.exists() else 'CA 口令已载入，可初始化当前目录的新 CA。'
        w.task(work,on_success=loaded)
