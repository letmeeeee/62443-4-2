"""Bounded cleanup of explicitly authorized NVMe log files."""
import os
import stat
import re
from datetime import datetime, date
from pathlib import Path
from threading import Event, Thread

# Cleanup threshold and interval.
CLEANUP_THRESHOLD_PERCENT = 95
CLEANUP_CHECK_INTERVAL_SECONDS = 300
HISTORY_TYPES = ('bms', 'fault', 'meter', 'mv', 'pcsgroup', 'pcsmodel', 'rack', 'system')
HISTORY_DATES_PER_TYPE = 10

def filesystem_used_percent(path):
    # Match df semantics: available space excludes reserved blocks.
    info = os.statvfs(str(path))
    used = info.f_blocks - info.f_bfree
    denominator = used + info.f_bavail
    return used * 100 / denominator if denominator else 0.0


def open_file_ids():
    """Fail closed if we cannot inspect process descriptors."""
    identities = set()
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            for fd in (process / 'fd').iterdir():
                try:
                    info = fd.stat()
                    identities.add((info.st_dev, info.st_ino))
                except FileNotFoundError:
                    pass
        except FileNotFoundError:
            pass
    return identities


def actual_mount_points():
    """Read actual Linux mounts, avoiding st_dev-based overlay heuristics."""
    if os.name != 'posix':
        return set()
    mounts = set()
    with open('/proc/self/mountinfo', encoding='utf-8') as stream:
        for line in stream:
            fields = line.split()
            if len(fields) < 6:
                raise ValueError('Invalid /proc/self/mountinfo entry')
            path = re.sub(r'\\([0-7]{3})', lambda match: chr(int(match.group(1), 8)), fields[4])
            mounts.add(path)
    return mounts


def cleanup_files(log, directory, suffix, limit=None, keep_latest=False):
    directory = Path(directory)
    log(f'[Disk Cleanup] 文件清理开始: directory={directory}, suffix={suffix}, limit={limit}')
    if directory.is_symlink():
        raise ValueError('Refusing symlink log directory')
    root = directory.resolve(strict=True)
    mounts = actual_mount_points()
    try:
        opened = open_file_ids()
    except OSError as exc:
        log(f'[Disk Cleanup] 无法检查文件占用，停止本轮清理: directory={root}, error={exc}', level='ERROR')
        raise
    candidates = []
    entries = list(root.iterdir())  # Unlike glob, surface directory permission errors.
    matching = [path for path in entries if path.name.endswith(suffix)]
    log(f'[Disk Cleanup] 目录扫描: directory={root}, entries={len(entries)}, matching={len(matching)}, '
        f'sample={[path.name for path in entries[:10]]}')
    for path in matching:
        try:
            info = path.lstat()
            # Overlay regular files may report a different st_dev than their directory.
            # Inspect actual entry type/mount status instead of rejecting device mismatch.
            if not stat.S_ISREG(info.st_mode) or str(path) in mounts:
                log(f'[Disk Cleanup] 跳过文件（非普通文件或独立挂载点）: {path}, mode={oct(info.st_mode)}')
                continue
            candidates.append((info.st_mtime_ns, path.name, path, info))
        except FileNotFoundError:
            continue
    removed = 0
    def retention_key(item):
        match = re.fullmatch(r'operation_([0-9]{8})\.csv', item[1])
        if match:
            try:
                return (datetime.strptime(match.group(1), '%Y%m%d').date(), item[1])
            except ValueError:
                pass
        return (datetime.fromtimestamp(item[3].st_mtime).date(), item[1])

    ordered = sorted(candidates, key=retention_key) if keep_latest and suffix == '.csv' else sorted(candidates)
    log(f'[Disk Cleanup] 扫描匹配文件: directory={root}, count={len(ordered)}')
    if keep_latest and ordered:
        newest = ordered.pop()
        log(f'[Disk Cleanup] 保留最新文件: {newest[2]}')
    for item in ordered:
        if (item[3].st_dev, item[3].st_ino) in opened:
            log(f'[Disk Cleanup] 跳过文件（正在使用）: {item[2]}')
    selected = [item for item in ordered
                if item[2].name != 'USB.log'
                and (item[3].st_dev, item[3].st_ino) not in opened
                and (keep_latest or datetime.fromtimestamp(item[3].st_mtime).date() < date.today())][:limit]
    log(f'[Disk Cleanup] 待删除文件数量: directory={root}, count={len(selected)}')
    for _, _, path, original in selected:
        try:
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or
                    (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_size) !=
                    (original.st_dev, original.st_ino, original.st_mtime_ns, original.st_size)):
                log(f'[Disk Cleanup] 跳过文件（清理期间发生变化）: {path}')
                continue
            if (info.st_dev, info.st_ino) in open_file_ids():
                log(f'[Disk Cleanup] 跳过文件（正在使用）: {path}')
                continue
            if str(path) in actual_mount_points():
                log(f'[Disk Cleanup] 跳过文件（真实挂载点）: {path}')
                continue
            log(f'[Disk Cleanup] 正在删除文件: {path}, bytes={info.st_size}')
            path.unlink()
            removed += 1
            log(f'[Disk Cleanup] 文件删除成功: {path}, bytes={info.st_size}')
        except FileNotFoundError:
            log(f'[Disk Cleanup] 跳过文件（已不存在）: {path}')
            continue
        except OSError as exc:
            log(f'[Disk Cleanup] 文件删除失败: {path}, error={exc}', level='ERROR')
            raise
    log(f'[Disk Cleanup] 文件清理完成: directory={root}, deleted={removed}, selected={len(selected)}')
    return removed


def cleanup_nvme_logs(log, directory=Path('/mnt/nvme/zlog')):
    return cleanup_files(log, directory, '.log', 5)


def cleanup_app_logs(log):
    return cleanup_files(log, '/mnt/nvme/applog', '.log', keep_latest=True)


def oldest_history_tables(names, today=None):
    today = today or date.today()
    eligible = {prefix: [] for prefix in HISTORY_TYPES}
    for name in set(names):
        match = re.fullmatch(r'(bms|fault|meter|mv|pcsgroup|pcsmodel|rack|system)([0-9]{8})', name)
        if not match:
            continue
        try:
            day = datetime.strptime(match.group(2), '%Y%m%d').date()
        except ValueError:
            continue
        if day < today:
            eligible[match.group(1)].append((day, name))
    return [name for prefix in HISTORY_TYPES
            for _, name in sorted(eligible[prefix])[:HISTORY_DATES_PER_TYPE]]


def cleanup_mysql_history(log):
    import config
    from sqlalchemy import text

    if config.engine is None:
        raise RuntimeError('MySQL engine unavailable')
    count = 0
    with config.engine.connect() as connection:
        # Serialize this cleanup across backend workers; DDL commits implicitly in MySQL.
        if connection.execute(text("SELECT GET_LOCK('lc_history_cleanup', 0)")).scalar() != 1:
            raise RuntimeError('Another worker is cleaning history tables')
        previous_timeout = None
        try:
            previous_timeout = connection.execute(text('SELECT @@SESSION.lock_wait_timeout')).scalar()
            connection.execute(text('SET SESSION lock_wait_timeout = 5'))
            rows = connection.execute(text(
                "SELECT TABLE_NAME FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE'"))
            names = oldest_history_tables([row[0] for row in rows])
            for prefix in HISTORY_TYPES:
                selected = [name for name in names if name[:-8] == prefix]
                log(f'[Disk Cleanup] 历史表分组: type={prefix}, selected={len(selected)}, tables={selected}')
            log(f'[Disk Cleanup] 历史表清理开始: selected={len(names)}')
            for name in names:
                # Identifiers come only from the strict allowlist/date parser above.
                log(f'[Disk Cleanup] 正在删除历史表: {name}')
                try:
                    connection.execute(text(f'DROP TABLE `{name}`'))
                except Exception as exc:
                    log(f'[Disk Cleanup] 历史表删除失败: {name}, deleted={count}, error={exc}', level='ERROR')
                    raise
                count += 1
                log(f'[Disk Cleanup] 历史表删除成功: {name}')
            log(f'[Disk Cleanup] 历史表清理完成: deleted={count}, selected={len(names)}')
        finally:
            try:
                if previous_timeout is not None:
                    connection.execute(text(f'SET SESSION lock_wait_timeout = {int(previous_timeout)}'))
                connection.execute(text("SELECT RELEASE_LOCK('lc_history_cleanup')"))
            except Exception:
                connection.invalidate()
                raise
    return count


def monitor_disk_cleanup(stop, log):
    while not stop.is_set():
        try:
            root_usage = filesystem_used_percent('/')
            log(f'[Disk Cleanup] 根分区检查: usage={root_usage:.2f}%, '
                f'threshold={CLEANUP_THRESHOLD_PERCENT}%')
            if root_usage > CLEANUP_THRESHOLD_PERCENT:
                log(f'[Disk Cleanup] 触发清理: mount=/, usage={root_usage:.2f}%, threshold={CLEANUP_THRESHOLD_PERCENT}%')
                for directory, suffix in (('/home/zlgmcu/zlog', '.csv'),):
                    try:
                        if directory.startswith('/mnt/nvme/') and not os.path.ismount('/mnt/nvme'):
                            raise OSError('NVMe not mounted')
                        count = cleanup_files(log, directory, suffix, keep_latest=True)
                        log(f'[Disk Cleanup] Root pressure: removed={count}, directory={directory}')
                    except Exception as exc:
                        log(f'[Disk Cleanup] {directory}: {exc}', level='ERROR')
            if not os.path.ismount('/mnt/nvme'):
                raise OSError('/mnt/nvme is not mounted; cleanup skipped')
            usage = filesystem_used_percent('/mnt/nvme')
            if usage > CLEANUP_THRESHOLD_PERCENT:
                log(f'[Disk Cleanup] 触发清理: mount=/mnt/nvme, usage={usage:.2f}%, threshold={CLEANUP_THRESHOLD_PERCENT}%')
                for label, cleanup in (('Application logs', cleanup_app_logs),
                                       ('NVMe logs', cleanup_nvme_logs),
                                       ('MySQL tables', cleanup_mysql_history)):
                    try:
                        count = cleanup(log)
                        log(f'[Disk Cleanup] NVMe usage={usage:.2f}%; {label} removed={count}', level='WARNING')
                    except Exception as exc:
                        log(f'[Disk Cleanup] {label}: {exc}', level='ERROR')
        except Exception as exc:
            log(f'[Disk Cleanup] Failed: {exc}', level='ERROR')
        stop.wait(CLEANUP_CHECK_INTERVAL_SECONDS)


def start_disk_cleanup_monitor(log):
    stop = Event()
    Thread(target=monitor_disk_cleanup, args=(stop, log),
           name='disk-cleanup', daemon=True).start()
    return stop
