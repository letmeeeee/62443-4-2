#!/usr/bin/env python3
"""持续读取本地升级状态文件，不依赖 Flask、数据库或设备连接。"""

import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import time


STATE_NAMES = {-1: '发生错误', 0: '空闲', 1: '升级中', 2: '升级失败', 3: '升级成功'}


def positive_interval(value):
    interval = float(value)
    if not math.isfinite(interval) or interval <= 0:
        raise argparse.ArgumentTypeError('查询间隔必须是大于 0 的有限秒数')
    return interval


def read_status(path):
    with path.open('r', encoding='utf-8') as stream:
        data = json.load(stream)
    if not isinstance(data, dict):
        raise ValueError('状态文件内容必须是 JSON 对象')
    try:
        progress = int(data['progress'])
        state = int(data['state'])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError('状态文件缺少有效的 progress/state 字段') from exc
    message = json.dumps(data.get('msg', ''), ensure_ascii=False)
    return f'progress={progress}% state={state}({STATE_NAMES.get(state, "未知状态")}) msg={message}'


def main():
    parser = argparse.ArgumentParser(
        description='持续读取 <状态目录>/<任务名>.json，每次查询都打印结果，按 Ctrl+C 停止。',
    )
    parser.add_argument('task_name', help='升级任务名 taskName，不含 .json 后缀')
    parser.add_argument('--status-dir', type=Path, default=Path('/home/zlg/upgrade/status'),
                        help='状态文件目录，默认 /home/zlg/upgrade/status')
    parser.add_argument('--interval', type=positive_interval, default=1.0,
                        help='查询间隔，单位秒，默认 1，可使用 0.1 等小数')
    parser.add_argument('--once', action='store_true', help='只查询一次；读取失败时退出码为 1')
    args = parser.parse_args()
    if not args.task_name or args.task_name in ('.', '..') or any(
        char in args.task_name for char in ('/', '\\', '\x00', '\n', '\r')
    ):
        parser.error('任务名不能包含路径分隔符、换行或空字符')

    path = args.status_dir / f'{args.task_name}.json'
    print(f'查询任务: {args.task_name}，状态文件: {path}，间隔: {args.interval}s', flush=True)
    started = time.monotonic()
    count = 0
    try:
        while True:
            count += 1
            failed = False
            try:
                result = read_status(path)
            except FileNotFoundError as exc:
                failed = True
                result = f'文件尚不存在或链接目标不存在: {exc!r}'
            except (OSError, ValueError, UnicodeError) as exc:
                failed = True
                result = f'读取失败（持续查询时会重试）: {exc!r}'
            timestamp = datetime.now().isoformat(sep=' ', timespec='milliseconds')
            print(f'[{timestamp}] #{count} elapsed={time.monotonic() - started:.3f}s {result}',
                  flush=True)
            if args.once:
                return 1 if failed else 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print('\n已停止查询。', flush=True)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
