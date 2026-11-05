#!/usr/bin/env python3
"""LC400 企业内部离线 CA；无参数启动 GUI，--help 查看 CLI。"""
import argparse
import getpass
import json
import os
from pathlib import Path

from provisioning.ca import CertificateAuthority
from provisioning.common import atomic_write, read_file
from provisioning.passwords import generate_password, load_for_ca, save_password


def gui():
    from provisioning.ui import Window, filedialog, messagebox
    w = Window('LC400 企业内部 CA — 离线签发管理')
    w.field('ca', 'CA 数据目录（含加密私钥）', str(Path.home() / 'lc400-ca'), True)
    w.field('organization', '企业/CA 名称', 'LC400 Enterprise')
    w.field('request', '设备 CSR 交接目录', '', True)
    w.field('output', '证书包输出目录（必须不存在）', '')
    w.field('days', '设备证书有效期（天，1–825）', '365')
    w.field('serial', '待吊销的证书序列号（十六进制）', '')
    from provisioning.password_ui import PasswordPanel
    password_panel = PasswordPanel(w)
    def action(kind):
        if w.busy: return
        v = w.values(); ca = CertificateAuthority(v['ca'])
        if kind == 'inspect':
            w.task(lambda: ca.inspect_request(v['request'])); return
        if kind == 'list':
            w.task(ca.records); return
        if kind == 'roots':
            destination = filedialog.askdirectory(title='选择公开根证书导出目录')
            if destination:
                def export():
                    atomic_write(Path(destination) / 'roots.pem', read_file(ca.directory / 'roots.pem'), 0o644)
                    return dict(root_fingerprint=ca.fingerprint(), file=str(Path(destination)/'roots.pem'))
                w.task(export)
            return
        if kind == 'sign':
            try: review = ca.inspect_request(v['request'])
            except Exception as exc: messagebox.showerror('CSR 检查失败', str(exc)); return
            if not messagebox.askyesno('确认设备归属与身份', json.dumps(review, ensure_ascii=False, indent=2) + '\n确认这些 CN/IP 属于待部署设备，并批准签发？'):
                return
        if kind == 'revoke' and not messagebox.askyesno('确认吊销', '吊销序列号 ' + v['serial'] + '？吊销不可撤回。'):
            return
        destination = filedialog.asksaveasfilename(defaultextension='.pem', initialfile='issuer-crl.pem') if kind == 'crl' else None
        if kind == 'crl' and not destination: return
        password = password_panel.get(confirm=kind == 'init')
        if password is None: return
        def execute():
            if kind == 'init':
                created = CertificateAuthority.initialize(v['ca'], password, v['organization'])
                return dict(message='根 CA 与签发 CA 初始化完成；请离线备份整个 CA 目录', root_fingerprint=created.fingerprint())
            if kind == 'sign': return ca.issue_package(v['request'], v['output'], password, int(v['days']), expected_review=review)
            if kind == 'revoke':
                ca.revoke(v['serial'], password); return '已记录吊销；请导出并分发最新 CRL。设备当前尚不自动检查 CRL。'
            ca.export_crl(destination, password); return 'CRL 已导出：' + destination
        w.task(execute)
    for label, kind in [('初始化 CA','init'),('预览 CSR','inspect'),('签发三证书包','sign'),('签发记录','list'),('导出根 CA','roots'),('吊销证书','revoke'),('导出 CRL','crl')]:
        w.button(label, lambda k=kind: action(k))
    w.run()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ca-dir', default=str(Path.home() / 'lc400-ca'))
    parser.add_argument('--vault-file', help='读取加密口令文件，交互输入独立保护口令')
    sub = parser.add_subparsers(dest='command')
    sub.add_parser('gui')
    init = sub.add_parser('init'); init.add_argument('--name', default='LC400 Enterprise')
    review = sub.add_parser('inspect'); review.add_argument('request')
    sign = sub.add_parser('sign'); sign.add_argument('request'); sign.add_argument('output'); sign.add_argument('--days', type=int, default=365)
    sub.add_parser('list'); sub.add_parser('fingerprint')
    revoke = sub.add_parser('revoke'); revoke.add_argument('serial'); revoke.add_argument('--reason', default='cessation_of_operation', choices=['cessation_of_operation','key_compromise','superseded','affiliation_changed'])
    crl = sub.add_parser('crl'); crl.add_argument('output')
    for operation in ('password-generate','password-save'):
        item = sub.add_parser(operation); item.add_argument('--out', required=True, help='新的 .lcvault 文件，必须在 CA 数据目录之外')
    sub.add_parser('password-check', help='验证 --vault-file 可解密，并验证当前已初始化 CA 的私钥口令')
    args = parser.parse_args()
    if args.command in (None, 'gui'): return gui()
    ca = CertificateAuthority(args.ca_dir)
    if args.command in ('password-generate', 'password-save'):
        if args.command == 'password-generate':
            if ca.database.exists(): raise ValueError('已有 CA 请使用 password-save；生成新口令不会修改已有私钥')
            password = generate_password()
        else:
            password = getpass.getpass('现有 CA 口令: ')
            if password != getpass.getpass('再次输入 CA 口令: '): raise ValueError('口令不一致')
            if ca.database.exists(): ca.unlock(password)
        protection = getpass.getpass('独立文件保护口令（至少12位）: ')
        if protection != getpass.getpass('再次输入保护口令: '): raise ValueError('保护口令不一致')
        result = save_password(args.out, password, protection, ca.directory)
    elif args.command == 'password-check':
        if not args.vault_file: parser.error('password-check requires --vault-file')
        load_for_ca(args.vault_file, getpass.getpass('文件保护口令: '), ca)
        result = dict(loaded=True, ca_verified=ca.database.is_file())
    elif args.command == 'inspect': result = ca.inspect_request(args.request)
    elif args.command == 'list': result = ca.records()
    elif args.command == 'fingerprint': result = dict(root_fingerprint=ca.fingerprint())
    else:
        password = load_for_ca(args.vault_file, getpass.getpass('文件保护口令: '), ca) if args.vault_file else getpass.getpass('CA 加密口令: ')
        if args.command == 'init':
            if not args.vault_file and password != getpass.getpass('再次输入: '): raise ValueError('口令不一致')
            ca = CertificateAuthority.initialize(args.ca_dir, password, args.name)
            result = dict(root_fingerprint=ca.fingerprint())
        elif args.command == 'sign': result = ca.issue_package(args.request, args.output, password, args.days)
        elif args.command == 'revoke':
            ca.revoke(args.serial, password, args.reason); result = dict(revoked=args.serial)
        else:
            ca.export_crl(args.output, password); result = dict(crl=args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    os.umask(0o077)
    try: main()
    except Exception as exc:
        raise SystemExit('CA 操作失败: ' + str(exc))
