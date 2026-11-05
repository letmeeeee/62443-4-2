"""Authenticated system monitoring endpoints."""
import os
import shutil

from flask import Blueprint, current_app, jsonify, request
from utils.system_usage import cpu_usage as measure_cpu_usage


system_bp = Blueprint("system", __name__)


@system_bp.route('/api/system/memory-usage', methods=['GET'])
def memory_usage():
    from routes.route_security import memory_usage as measure_memory
    try:
        return jsonify(measure_memory())
    except (OSError, ValueError, KeyError):
        current_app.logger.exception('Failed to read memory usage')
        return jsonify(ok=False, code='MEMORY_UNAVAILABLE'), 503


@system_bp.route('/api/system/cpu-usage', methods=['GET'])
def cpu_usage():
    """Return Linux host CPU utilization across all cores (0 to 100%)."""
    try:
        return jsonify(measure_cpu_usage())
    except (OSError, ValueError):
        current_app.logger.exception('Failed to read CPU usage')
        return jsonify(ok=False, error='CPU usage unavailable'), 503


@system_bp.route('/api/system/disk-usage', methods=['GET'])
def disk_usage():
    """Return filesystem capacity and aggregate CPU utilization in one request."""
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
        return jsonify(ok=False, error="Disk usage unavailable"), 500
    try:
        cpu = measure_cpu_usage()
    except (OSError, ValueError):
        current_app.logger.exception('Failed to read CPU usage')
        return jsonify(ok=False, error='CPU usage unavailable'), 503
    disk_percent = round(usage.used / usage.total * 100, 2) if usage.total else 0.0
    return jsonify(
        path=path, total=usage.total, used=usage.used, free=usage.free,
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
