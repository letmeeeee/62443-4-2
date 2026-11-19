#!/usr/bin/env python3
"""独立 CA 服务器：管理员初始化与 Web 管理界面。"""
import argparse
import getpass
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', default=str(Path.home() / '.lc400-ca-server'), help='独立 CA 数据目录')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('init', help='交互设置管理员口令，不覆盖已有管理员或 CA')
    serve = commands.add_parser('serve', help='启动 Web 服务')
    serve.add_argument('--host', default='127.0.0.1')
    serve.add_argument('--port', default=8443, type=int)
    serve.add_argument('--secure-cookie', action='store_true', help='HTTPS 反向代理部署时启用安全 Cookie')
    args = parser.parse_args()
    from tools.ca_server.app import create_app, initialize_admin
    if args.command == 'init':
        password = getpass.getpass('设置管理员登录口令（至少12位）：')
        if password != getpass.getpass('再次输入：'):
            parser.error('两次口令不一致')
        initialize_admin(args.data_dir, password)
        print('管理员已初始化。执行 serve 后在 Web 页面生成 CA。')
        return
    from waitress import serve
    # Linux deployment: prevent multiple writers with independent unlock/session state.
    import fcntl
    directory = Path(args.data_dir).resolve()
    if not directory.is_dir():
        parser.error('请先执行 init')
    lock_path = directory / '.server.lock'
    import os
    lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, 'w') as server_lock:
        try:
            fcntl.flock(server_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error('该数据目录已经有 CA 服务运行')
        app = create_app(directory, secure_cookie=args.secure_cookie)
        print('CA Web: http://%s:%s（外部访问请通过 HTTPS 反向代理）' % (args.host, args.port))
        serve(app, host=args.host, port=args.port, threads=4)


if __name__ == '__main__':
    main()
