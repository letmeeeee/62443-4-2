#!/usr/bin/env python3
"""升级包单表管理：建表、导入已有包、按类别切换当前包。"""
import argparse
import os
import sys
import socket
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]) if '__file__' in globals() else '/home/zlg/app')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--import-existing', action='store_true', help='扫描已有归档包，逐个验签入库')
    current = parser.add_mutually_exclusive_group()
    current.add_argument('--set-current', metavar='SHA256', help='本机升级成功后标记当前包')
    current.add_argument('--clear-current', action='store_true', help='清除本机当前包标记')
    parser.add_argument('--firmware', choices=['lc', 'config-file'],
                        help='清除指定类别的当前标记；默认lc。设置时默认从包记录推断类别')
    args = parser.parse_args()
    # 与 utils.ini.ini_param 使用相同数据库配置；不导入业务路由或启动设备线程。
    from sqlalchemy import create_engine
    from sqlalchemy.engine import URL
    host = os.environ.get('DB_HOST', '').strip() or os.environ.get('APP_HOST', '').strip()
    if not host:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(('8.8.8.8', 80))
                host = sock.getsockname()[0]
        except OSError:
            host = '127.0.0.1'
    engine = create_engine(URL.create('mysql+pymysql',
        username=os.environ.get('DB_USER', 'root'),
        password=os.environ.get('DB_PASSWORD', 'qwer1234'),
        host=host, port=int(os.environ.get('DB_PORT', '3306')),
        database=os.environ.get('DB_NAME', 'log_db')), pool_pre_ping=True)
    root = Path('/home/zlg/upgrade/packages')
    key = Path('/home/zlg/app/keys/ota_public_key.pem')
    failures = 0
    try:
        if args.set_current or args.clear_current:
            # 仅反射已有单表，不导入 app 模块；回退到旧 app 后仍可运行。
            from sqlalchemy import MetaData, Table, select
            digest = args.set_current
            if digest:
                digest = digest.strip().lower()
                if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                    parser.error('SHA256 must contain 64 hexadecimal characters')
            with engine.begin() as conn:
                table = Table('upgrade_packages', MetaData(), autoload_with=conn)
                rows = conn.execute(select(table.c.sha256, table.c.firmware).order_by(
                    table.c.sha256).with_for_update()).mappings().all()
                category = args.firmware or 'lc'
                if digest is not None:
                    selected = next((row for row in rows if row['sha256'] == digest), None)
                    if selected is None:
                        raise LookupError('升级包尚未入库')
                    category = selected['firmware'].lower()
                    if category not in ('lc', 'config-file'):
                        raise ValueError('不支持的升级包类别')
                    if args.firmware and args.firmware != category:
                        raise ValueError('firmware与升级包类别不匹配')
                conn.execute(table.update().where(table.c.firmware == category).values(is_current=False))
                if digest is not None:
                    conn.execute(table.update().where(table.c.sha256 == digest).values(is_current=True))
            return 0
        from utils.upgrade_index import UpgradePackageIndex
        store = UpgradePackageIndex(root, key, None, engine)
        store.ensure_schema()
        if args.import_existing:
            from routes.route_g3 import _catalog_upgrade_package
            store.inspect_package = _catalog_upgrade_package
            for path in sorted(root.glob('*/*/*.tar.gz')):
                try:
                    store.register(path)
                    print('已入库: %s' % path)
                except Exception as exc:
                    failures += 1
                    print('入库失败: %s: %s' % (path, exc), file=sys.stderr)
        print('升级包表已就绪；失败数量: %d' % failures)
        return 1 if failures else 0
    finally:
        engine.dispose()


if __name__ == '__main__':
    sys.exit(main())
