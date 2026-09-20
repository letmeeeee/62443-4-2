#!/usr/bin/env python3
import os, json, time, sys
from datetime import datetime
import glob
from datetime import datetime, timedelta
import threading
from pathlib import Path
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


# def DPrint(*args, sep=' ', end='\n'):
#     # 每次打印前先清理过期日志（也可改成定时/启动时清理）
#     from config import SAVE_LOG
#     clean_old_logs()

#     # 获取调用行号
#     try:
#         frame = sys._getframe(1)
#         line_no = frame.f_lineno
#     except (ValueError, AttributeError):
#         line_no = "?"
#     time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
#     log_head = f"[{time_str} LINE:{line_no}]"
#     content = sep.join(map(str, args))
#     full_line = f"{log_head} {content}{end}"

#     # 控制台输出
#     print(log_head, *args, sep=sep, end=end)

#     # 写入当日日志文件
#     if SAVE_LOG:
#         log_file = get_daily_log_file()
#         with open(log_file, "a", encoding="utf-8") as f:
#             f.write(full_line)


# ==========================================================
# 日志全局锁
#
# 防止多个线程同时：
#   1. 清理日志
#   2. 获取当天日志文件
#   3. 写入日志文件
#
# 导致日志内容交错或者日志清理冲突
# ==========================================================
_log_lock = threading.Lock()


# ==========================================================
# 记录上一次执行日志清理的日期
#
# 例如：
# 2026-09-17 第一次 DPrint() -> 执行 clean_old_logs()
# 后面当天的 DPrint() -> 不再重复清理
#
# 第二天：
# 2026-09-18 第一次 DPrint() -> 再执行一次清理
# ==========================================================
_last_clean_date = None


def DPrint(*args, sep=' ', end='\n', level='INFO'):
    """
    统一日志输出函数

    日志格式：

    [2026-09-17 13:19:23.123456] [upgrade.py:125] [process_upgrade] [INFO] 开始升级 device_id= 3

    参数：
        *args   : 日志内容
        sep     : 多个日志参数之间的分隔符
        end     : 日志结尾，默认换行
        level   : DEBUG / INFO / WARNING / ERROR
    """

    global _last_clean_date

    from config import SAVE_LOG

    # ==========================================================
    # 1. 获取调用者信息
    #
    # sys._getframe(1) 表示获取调用 DPrint() 的上一层函数
    # ==========================================================
    try:
        frame = sys._getframe(1)

        file_path = frame.f_code.co_filename
        file_name = Path(file_path).name

        line_no = frame.f_lineno

        func_name = frame.f_code.co_name

    except (ValueError, AttributeError):
        file_name = "?"
        line_no = "?"
        func_name = "?"

    # ==========================================================
    # 2. 获取当前时间
    # ==========================================================
    time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

    # ==========================================================
    # 3. 日志级别
    # ==========================================================
    level = str(level).upper()

    valid_levels = ("DEBUG", "INFO", "WARNING", "ERROR")

    if level not in valid_levels:
        level = "INFO"

    # ==========================================================
    # 4. 拼接日志内容
    # ==========================================================
    content = sep.join(map(str, args))

    # ==========================================================
    # 5. 生成完整日志
    # ==========================================================
    full_line = (
        f"[{time_str}] "
        f"[{file_name}:{line_no}] "
        f"[{func_name}] "
        f"[{level}] "
        f"{content}{end}"
    )

    # ==========================================================
    # 6. 控制台输出
    #
    # 控制台输出也加锁，避免多个线程同时 print 导致内容交错。
    # ==========================================================
    with _log_lock:
        print(full_line, end='')

        # ======================================================
        # 7. 日志文件处理
        # ======================================================
        if SAVE_LOG:

            today = datetime.now().date()

            # --------------------------------------------------
            # 每天只清理一次旧日志
            # --------------------------------------------------
            if _last_clean_date != today:
                try:
                    clean_old_logs()
                    _last_clean_date = today

                except Exception as e:
                    # 清理失败不能影响正常业务
                    print(
                        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}] "
                        f"[DPrint] [WARNING] "
                        f"clean_old_logs failed: {e}"
                    )

            # --------------------------------------------------
            # 获取当天日志文件
            # --------------------------------------------------
            try:
                log_file = get_daily_log_file()

                # ------------------------------------------------
                # 追加写入
                # ------------------------------------------------
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(full_line)

            except Exception as e:
                # 日志写入失败不能影响业务
                print(
                    f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}] "
                    f"[DPrint] [ERROR] "
                    f"write log failed: {e}"
                )

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
