"""升级包及按类别独立的当前版本标记的 MySQL 单表仓储；不导入设备初始化模块。

生产环境传入 config.engine。SQLite 仅用于隔离数据库测试。
"""
import json
import stat
import threading
import weakref
from datetime import datetime
from pathlib import Path

from sqlalchemy import MetaData, Table, Column, String, Text, DateTime, Boolean, select, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.mysql import LONGTEXT

schema = MetaData()
json_text = Text().with_variant(LONGTEXT(), 'mysql')
packages = Table('upgrade_packages', schema,
    Column('sha256', String(64), primary_key=True),
    Column('firmware', String(32), nullable=False, index=True),
    Column('version', String(255), nullable=False),
    Column('path', Text, nullable=False),
    Column('record', json_text, nullable=False),
    Column('uploaded_at', DateTime, nullable=False),
    Column('is_current', Boolean, nullable=False, server_default='0'),
    mysql_engine='InnoDB', mysql_charset='utf8mb4')


class UpgradePackageIndex:
    _ready_engines = weakref.WeakSet()
    _schema_lock = threading.Lock()

    def __init__(self, root, public_key, inspect_package, engine):
        self.root = Path(root).absolute()
        self.public_key = Path(public_key)
        self.inspect_package = inspect_package
        self.engine = engine

    def ensure_schema(self):
        with self._schema_lock:
            if self.engine not in self._ready_engines:
                schema.create_all(self.engine)
                self._ready_engines.add(self.engine)

    @staticmethod
    def normalize_sha256(value):
        if not isinstance(value, str):
            raise ValueError('sha256 must be a 64-character hexadecimal string')
        value = value.strip().lower()
        if len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('sha256 must be a 64-character hexadecimal string')
        return value

    @staticmethod
    def fingerprint(path):
        stat = path.stat()
        return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]

    def _archive_path(self, path, allow_missing=False):
        path = Path(path).absolute()
        parts = path.relative_to(self.root).parts
        if (len(parts) != 3 or any(p.startswith('.') or p == '..' for p in parts)
                or not path.name.endswith('.tar.gz')
                or any(p.is_symlink() for p in (path, path.parent, path.parent.parent))):
            raise ValueError('不是正式归档升级包文件')
        try:
            if not stat.S_ISREG(path.lstat().st_mode):
                raise ValueError('不是正式归档升级包文件')
        except FileNotFoundError:
            if not allow_missing:
                raise
        return path

    def register(self, path):
        """仅上传/显式迁移时验签、读 info、计算摘要并入库；查询不读文件。"""
        path = self._archive_path(path)
        before = self.fingerprint(path)
        record = self.inspect_package(path)
        if before != self.fingerprint(path):
            raise RuntimeError('升级包在入库期间发生变化，请重试')
        record['fingerprint'] = before
        digest = self.normalize_sha256(record['package']['sha256'])
        values = dict(firmware=record['metadata']['firmware'].lower(),
                      version=record['metadata']['version'], path=str(path),
                      record=json.dumps(record, ensure_ascii=False), uploaded_at=datetime.now())
        with self.engine.begin() as conn:
            try:
                with conn.begin_nested():
                    conn.execute(packages.insert().values(sha256=digest, **values))
            except IntegrityError:
                conn.execute(packages.update().where(packages.c.sha256 == digest).values(**values))
        return record

    @staticmethod
    def _record(row):
        return json.loads(row['record'])

    def get_by_version(self, firmware, version):
        with self.engine.connect() as conn:
            rows = conn.execute(select(packages).where(and_(
                packages.c.firmware == firmware.lower(), packages.c.version == version,
            ))).mappings().all()
        if len(rows) != 1:
            raise LookupError('该 firmware/version 的升级包数量应为 1，实际 %d；请使用 sha256' % len(rows))
        return self._record(rows[0])

    def list_packages(self):
        with self.engine.connect() as conn:
            rows = conn.execute(select(packages).order_by(
                packages.c.firmware, packages.c.version, packages.c.sha256)).mappings().all()
        result = []
        for row in rows:
            record = self._record(row)
            item = dict(record['package'])
            item['is_current'] = bool(row['is_current'])
            result.append(item)
        return result, []

    def find_by_sha256(self, sha256):
        digest = self.normalize_sha256(sha256)
        with self.engine.connect() as conn:
            row = conn.execute(select(packages).where(packages.c.sha256 == digest)).mappings().first()
        if row is None:
            raise LookupError('未找到对应 sha256 的升级包，请先上传或迁移入库')
        # 兼容此前已入库的相对路径，新上传/重新导入统一保存绝对路径。
        path = self._archive_path(self.root / row['path'])
        return path, self._record(row)

    def current(self, firmware='lc'):
        with self.engine.connect() as conn:
            row = conn.execute(select(packages).where(
                and_(packages.c.is_current.is_(True),
                     packages.c.firmware == firmware.lower()))).mappings().first()
        return dict(package=(dict(self._record(row)['package'],
                    info=self._record(row)['metadata']) if row else None))

    def delete(self, sha256):
        """删除指定归档和记录；文件缺失可清理记录，共用路径不误删其他包。"""
        digest = self.normalize_sha256(sha256)
        with self.engine.begin() as conn:
            # 与当前标记切换采用相同顺序加锁，避免删除过程中修改当前标记。
            rows = conn.execute(select(packages).order_by(
                packages.c.sha256).with_for_update()).mappings().all()
            row = next((item for item in rows if item['sha256'] == digest), None)
            if row is None:
                raise LookupError('未找到对应 sha256 的升级包')
            path = self._archive_path(self.root / row['path'], allow_missing=True)
            shared = any(item['sha256'] != digest and
                         (self.root / item['path']).absolute() == path for item in rows)
            # 先执行SQL，再删文件：SQL执行失败不会删除缓存；文件删除失败会回滚SQL。
            conn.execute(packages.delete().where(packages.c.sha256 == digest))
            file_deleted = False
            if not shared:
                try:
                    path.unlink()
                    file_deleted = True
                except FileNotFoundError:
                    pass
            result = dict(sha256=digest, file_deleted=file_deleted, file_retained=shared,
                          was_current=bool(row['is_current']))
        # 数据库提交失败时本地文件可能已删除；下次重试允许文件缺失，继续清理记录。
        return result
