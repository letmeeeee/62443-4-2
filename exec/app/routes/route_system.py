"""系统资源监控接口：内存、CPU 与磁盘使用情况。"""
import os
import shutil
import traceback

from flask import Blueprint, current_app, jsonify, request
from utils.system_usage import cpu_usage as measure_cpu_usage
from utils.utils import DPrint


system_bp = Blueprint("system", __name__)


@system_bp.route('/api/system/memory-usage', methods=['GET'])
def memory_usage():
    """查询本机内存使用情况，无入参。

    请求示例：
      GET /api/system/memory-usage

    返回：{total, available, used, usedPercent}，容量单位为字节。
    采集失败返回 503 MEMORY_UNAVAILABLE。
    """
    from routes.route_security import memory_usage as measure_memory

    try:
        return jsonify(measure_memory())
    except (OSError, ValueError, KeyError):
        current_app.logger.exception('Failed to read memory usage')
        DPrint(f'Failed to read memory usage\n{traceback.format_exc()}', level='ERROR')
        return jsonify(ok=False, code='MEMORY_UNAVAILABLE'), 503


@system_bp.route('/api/system/cpu-usage', methods=['GET'])
def cpu_usage():
    """查询本机所有 CPU 核心的综合使用率，无入参。

    请求示例：
      GET /api/system/cpu-usage

    返回 CPU 采集模块提供的结构，usedPercent 范围为 0～100。
    采集失败返回 503。
    """
    try:
        return jsonify(measure_cpu_usage())
    except (OSError, ValueError):
        current_app.logger.exception('Failed to read CPU usage')
        DPrint(f'Failed to read CPU usage\n{traceback.format_exc()}', level='ERROR')
        return jsonify(ok=False, error='CPU usage unavailable'), 503


@system_bp.route('/api/system/disk-usage', methods=['GET'])
def disk_usage():
    """查询指定路径所在文件系统的容量，同时返回 CPU 使用情况。

    请求示例：
      GET /api/system/disk-usage?path=/

    参数：path 可选，默认 /，必须是非空、不含空字符的绝对路径。
    返回：path、total、used、free、usedPercent、cpu，以及 display 展示字段。
    原始容量单位为字节，display 中容量使用 GiB，使用率使用百分比字符串。
    """
    # 校验路径后采集文件系统容量，保留各类文件系统错误对应的状态码。
    path = request.args.get('path', '/')
    if not path or '\x00' in path or not os.path.isabs(path):
        return jsonify(ok=False, error="path must be an absolute path"), 400
    try:
        usage = shutil.disk_usage(path)
    except (FileNotFoundError, NotADirectoryError):
        return jsonify(ok=False, error="Path does not exist"), 404
    except PermissionError:
        return jsonify(ok=False, error="Permission denied"), 403
    except OSError:
        current_app.logger.exception("Failed to read disk usage")
        DPrint(f'Failed to read disk usage\n{traceback.format_exc()}', level='ERROR')
        return jsonify(ok=False, error="Disk usage unavailable"), 500
    # 同一次请求附带 CPU 使用情况，供资源监控页面组合展示。
    try:
        cpu = measure_cpu_usage()
    except (OSError, ValueError):
        current_app.logger.exception('Failed to read CPU usage')
        DPrint(f'Failed to read CPU usage\n{traceback.format_exc()}', level='ERROR')
        return jsonify(ok=False, error='CPU usage unavailable'), 503
    disk_percent = round(usage.used / usage.total * 100, 2) if usage.total else 0.0
    return jsonify(
        path=path,
        total=usage.total,
        used=usage.used,
        free=usage.free,
        usedPercent=disk_percent,
        cpu=cpu,
        display={
            'diskTotal': f'{usage.total / 1024 ** 3:.2f} GiB',
            'diskUsed': f'{usage.used / 1024 ** 3:.2f} GiB',
            'diskFree': f'{usage.free / 1024 ** 3:.2f} GiB',
            'diskUsage': f'{disk_percent:.2f}%',
            'cpuUsage': f'{cpu["usedPercent"]:.2f}%',
        },
    )
