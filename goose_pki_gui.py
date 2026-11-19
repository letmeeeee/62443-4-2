#!/usr/bin/env python3
"""GOOSE P-256 私钥、CSR 与证书离线签发 GUI。"""
import argparse
from pathlib import Path

from tools.goose_pki import crypto


def gui():
    from provisioning.ui import Window, filedialog, messagebox, simpledialog, ttk
    w = Window('GOOSE PKI — P-256 密钥 / CSR / 证书签发')
    w.root.geometry('1100x800')
    w.field('cn', '设备身份 CN', 'LC400-001-goose')
    w.field('days', '设备证书有效期（天，1–825）', '365')
    w.field('ca_cert', '签发 CA 证书（单张 PEM）', '', file=True)
    w.field('ca_key', '签发 CA 私钥（PEM）', '', file=True)
    ttk.Label(w.form, text='设备密钥固定为 EC prime256v1（P-256）；私钥导出为设备可导入的未加密 PKCS#8 PEM。').grid(
        row=4, column=0, columnspan=3, sticky='w', pady=8)
    state = dict(key=None, csr=None, cert=None, ca=None, ca_key=None)

    def guard(action):
        def execute():
            if w.busy:
                return
            try:
                action()
            except Exception as exc:
                messagebox.showerror('操作失败', str(exc), parent=w.root)
        return execute

    def replace_identity():
        if state['csr'] is None:
            return True
        return messagebox.askyesno('替换当前身份', '将替换内存中的私钥、CSR 和证书。请先导出需要保留的文件。继续？', parent=w.root)

    def generate():
        if not replace_identity():
            return
        cn = w.values()['cn']
        def complete(result):
            state.update(key=result[0], csr=result[1], cert=None)
            return '已生成 P-256 私钥和 CSR：' + cn + '。请导出保存；关闭窗口后内存中的身份不会保留。'
        w.task(lambda: crypto.generate_identity(cn), complete)

    def import_csr():
        path = filedialog.askopenfilename(title='选择 PEM CSR')
        if not path or not replace_identity():
            return
        csr = crypto.load_csr(Path(path).read_bytes())
        state.update(key=None, csr=csr, cert=None)
        from cryptography.x509.oid import NameOID
        w.fields['cn'].set(csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value)
        w.output.insert('end', '\n已导入 CSR；私钥由 CSR 生成方保管。\n')

    def load_ca():
        values = w.values()
        password = w.password()
        if password is None:
            return
        def work():
            return crypto.load_ca(Path(values['ca_cert']).read_bytes(), Path(values['ca_key']).read_bytes(), password)
        def complete(result):
            state.update(ca=result[0], ca_key=result[1])
            return 'CA 已加载：' + result[0].subject.rfc4514_string()
        # Drop previously loaded CA before attempting to switch credentials.
        state.update(ca=None, ca_key=None)
        w.task(work, complete)

    def create_ca():
        cn = simpledialog.askstring('新建 GOOSE 根 CA', 'CA 名称：', initialvalue='GOOSE Root CA', parent=w.root)
        if not cn:
            return
        password = w.password(confirm=True)
        if password is None:
            return
        parent = filedialog.askdirectory(title='选择 CA 保存位置（会在其中新建独立目录）')
        if not parent:
            return
        def work():
            import tempfile
            cert, key, encrypted, crl = crypto.create_ca(cn, password)
            folder = Path(tempfile.mkdtemp(prefix='goose-ca-', dir=parent))
            folder.chmod(0o700)
            crypto.export_new(folder / 'ca-roots.crt', crypto.pem(cert))
            crypto.export_new(folder / 'ca-private.key', encrypted, private=True)
            crypto.export_new(folder / 'crls.pem', crypto.pem(crl))
            return cert, key, folder
        def complete(result):
            cert, key, folder = result
            state.update(ca=cert, ca_key=key)
            w.fields['ca_cert'].set(str(folder / 'ca-roots.crt'))
            w.fields['ca_key'].set(str(folder / 'ca-private.key'))
            return ('新 CA 已创建并加载：' + str(folder) + '\n含加密 CA 私钥、根证书和有效期 30 天的初始 CRL。'
                    '\n请离线保存 CA 私钥和口令；已有 SCADA 信任体系请选择加载现有 CA。')
        w.task(work, complete)

    def sign():
        if state['csr'] is None or state['ca'] is None:
            raise ValueError('请先生成或导入 CSR，并加载或新建 CA')
        days = int(w.values()['days'])
        csr, ca, key = state['csr'], state['ca'], state['ca_key']
        if not messagebox.askyesno('确认签发', '设备：' + csr.subject.rfc4514_string() + '\n签发 CA：' + ca.subject.rfc4514_string()
                                  + '\n有效天数：' + str(days) + '\n确认签发？', parent=w.root):
            return
        def complete(cert):
            state['cert'] = cert
            return crypto.describe(cert)
        w.task(lambda: crypto.issue(csr, ca, key, days), complete)

    def export(kind, filename):
        value = state[kind]
        if value is None:
            raise ValueError('当前没有可导出的文件，请先完成对应的生成、导入或签发操作')
        path = filedialog.asksaveasfilename(title='导出文件（请选择新文件名）', initialfile=filename, defaultextension='.pem')
        if not path:
            return
        data = crypto.private_pem(value) if kind == 'key' else crypto.pem(value)
        crypto.export_new(path, data, private=kind == 'key')
        w.output.insert('end', '\n已导出：' + path + '\n')

    rows = [
        [('生成私钥和 CSR', generate), ('导入已有 CSR', import_csr),
         ('导出设备私钥', lambda: export('key', 'enc.key')), ('导出 CSR', lambda: export('csr', 'goose.csr.pem'))],
        [('新建根 CA', create_ca), ('加载现有 CA', load_ca), ('签发证书', sign),
         ('导出设备证书', lambda: export('cert', 'enc.crt')), ('导出签发 CA 证书', lambda: export('ca', 'issuer-ca.crt'))]]
    for index, actions in enumerate(rows):
        for column, (label, action) in enumerate(actions):
            ttk.Button(w.buttons, text=label, command=guard(action)).grid(row=index, column=column, padx=4, pady=5, sticky='ew')
    w.output.insert('end', '操作顺序：生成私钥和 CSR → 加载或新建 CA → 签发证书 → 导出私钥、CSR、证书。\n'
                    '加载 CA 时，未加密私钥的口令留空。CA 证书与私钥须匹配。\n'
                    '已有 CA 的 CRL 请从原 CA 管理系统导出；本工具不会替已有 CA 创建空 CRL。\n'
                    '若签发 CA 是中间 CA，导入设备的 enc.crt 需追加中间证书链，信任根与完整 CRL 另行导入。\n')
    original_close = w.close
    def close():
        if w.busy:
            original_close()
        elif state['key'] is None or messagebox.askyesno('关闭工具', '请确认设备私钥和证书已经导出。关闭后无法恢复未保存的密钥。继续？', parent=w.root):
            original_close()
    w.root.protocol('WM_DELETE_WINDOW', close)
    w.run()


if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    gui()
