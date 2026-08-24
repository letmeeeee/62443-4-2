#!/usr/bin/env python3
import os, json, time, sys
from datetime import datetime
import glob
from datetime import datetime, timedelta

# ================== 工具函数 ==================

def _to_signed_16(value: int) -> int:
    """
    uint16 转 int16。
    """
    value = int(value) & 0xFFFF
    if value >= 0x8000:
        value -= 0x10000
    return value

def _to_signed_32(value: int) -> int:
    """
    uint32 转 int32。
    """
    value = int(value) & 0xFFFFFFFF
    if value >= 0x80000000:
        value -= 0x100000000
    return value

def _combine_uint32_big_endian(registers) -> int:
    """
    按大端模式组合 2 个 16 位寄存器。

    示例:
      registers = [0x1234, 0x5678]
      raw = 0x12345678
    """
    regs = [int(x) & 0xFFFF for x in registers]

    if len(regs) != 2:
        raise ValueError(f"uint32/int32 需要 2 个寄存器，实际读取到 {len(regs)} 个")

    return (regs[0] << 16) | regs[1]

def now_str():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def clean_old_logs():
    """清理超过 RETENTION_DAYS 天的日志文件"""
    from config import LOG_FILE, RETENTION_DAYS
    if not os.path.exists(LOG_FILE):
        return
    # 计算7天前的时间戳
    cutoff_time = datetime.now() - timedelta(days=RETENTION_DAYS)
    # 匹配所有日志文件（假设日志后缀 .log）
    log_files = glob.glob(os.path.join(LOG_FILE, "*.log"))

    for file_path in log_files:
        try:
            file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
            if file_mtime < cutoff_time:
                os.remove(file_path)
        except Exception:
            pass

def get_daily_log_file():
    """获取当日日志文件路径（按天命名）"""
    from config import LOG_FILE
    date_str = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(LOG_FILE, f"{date_str}.log")


def DPrint(*args, sep=' ', end='\n'):
    # 每次打印前先清理过期日志（也可改成定时/启动时清理）
    from config import SAVE_LOG
    clean_old_logs()

    # 获取调用行号
    try:
        frame = sys._getframe(1)
        line_no = frame.f_lineno
    except (ValueError, AttributeError):
        line_no = "?"
    time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    log_head = f"[{time_str} LINE:{line_no}]"
    content = sep.join(map(str, args))
    full_line = f"{log_head} {content}{end}"

    # 控制台输出
    print(log_head, *args, sep=sep, end=end)

    # 写入当日日志文件
    if SAVE_LOG:
        log_file = get_daily_log_file()
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(full_line)

def jdump(obj):
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception as e:
        return f"<json-dump-error: {e}>"

def debug_log(hypothesis_id: str, location: str, message: str, data: dict = None, run_id: str = "initial"):
    # region agent log
    try:
        payload = {
            "sessionId": "6bd2f3",
            "runId": run_id,
            "hypothesisId": hypothesis_id,
            "id": f"log_{int(time.time() * 1000)}_{os.getpid()}",
            "location": location,
            "message": message,
            "data": data or {},
            "timestamp": int(time.time() * 1000),
        }
        with open("debug-6bd2f3.log", "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # endregion
