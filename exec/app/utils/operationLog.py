from datetime import datetime
from sqlalchemy import text
import config
from utils.utils import DPrint
from enum import Enum
import atexit
import queue
import threading


# 日志枚举
class OperationType(str, Enum):
    CONTROL = "system.control"      # 控制操作
    USER = "systemMg.user.title"    # 用户管理
    PARAM = "menu.parameterSetting" # 参数配置
    UPGRADE = "menu.device_upgrade"  # 固件升级
    ROLLBACK = "menu.device_rollback"  # 固件回退
    TESTMODE = "testMode"           # 测试模式

OP_NUM_MAP = {
    1: OperationType.CONTROL,
    2: OperationType.USER,
    3: OperationType.PARAM,
    4: OperationType.UPGRADE,
    5: OperationType.ROLLBACK,
    6: OperationType.TESTMODE,
}

_LOG_QUEUE_MAX_SIZE = 1000
_LOG_QUEUE_STOP = object()
_log_queue = queue.Queue(maxsize=_LOG_QUEUE_MAX_SIZE)
_log_worker = None
_log_worker_lock = threading.Lock()


class OperationResult(Enum):
    FAIL = 0
    SUCCESS = 1

def _enum_value(value):
    if isinstance(value, Enum):
        return value.value
    return value


def _operation_result_value(success) -> int:
    if isinstance(success, OperationResult):
        return success.value
    return 1 if success else 0


def start_operation_log_worker() -> None:
    """启动操作日志后台线程。重复调用是安全的。"""
    global _log_worker
    with _log_worker_lock:
        if _log_worker and _log_worker.is_alive():
            return
        _log_worker = threading.Thread(
            target=_operation_log_worker_loop,
            name="operation-log-worker",
            daemon=True,
        )
        _log_worker.start()
        DPrint("operation_log 后台线程已启动")


def stop_operation_log_worker(timeout: float = 2.0) -> None:
    """停止操作日志后台线程，主要用于进程退出时尽量落盘。"""
    worker = _log_worker
    if not worker or not worker.is_alive():
        return
    try:
        _log_queue.put_nowait(_LOG_QUEUE_STOP)
    except queue.Full:
        return
    worker.join(timeout=timeout)


def _operation_log_worker_loop() -> None:
    while True:
        item = _log_queue.get()
        try:
            if item is _LOG_QUEUE_STOP:
                return
            record_operation_log(**item)
        except Exception as e:
            DPrint(f"操作日志后台线程异常：{e}")
        finally:
            _log_queue.task_done()


def enqueue_operation_log(
    operator: str,
    operation_type: str,
    operation_target: str,
    sort: int = 1,
    success: bool = None,
    remark: str = "",
) -> bool:
    """提交操作日志到后台线程。队列满时丢弃日志，不影响业务。"""
    start_operation_log_worker()
    try:
        _log_queue.put_nowait({
            "operator": operator,
            "operation_type": operation_type,
            "operation_target": operation_target,
            "sort": sort,
            "success": success,
            "remark": remark,
        })
        return True
    except queue.Full:
        DPrint("操作日志队列已满，丢弃本次日志")
        return False


atexit.register(stop_operation_log_worker)


# 创建日志表
def create_operation_log_table():
    """创建操作日志表（不存在时创建）"""

    sql = text("""
        CREATE TABLE IF NOT EXISTS operation_log (
            log_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '日志ID',
            operation_time   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '操作时间',
            operator         VARCHAR(64)  NOT NULL COMMENT '操作员',
            operation_type   VARCHAR(64)  NOT NULL COMMENT '操作类型',
            operation_target VARCHAR(64) NOT NULL COMMENT '操作对象',
            sort           TINYINT      NOT NULL COMMENT '设备序号,从1开始',
            result           TINYINT      NOT NULL COMMENT '0-失败 1-成功',
            remark           VARCHAR(255)  NOT NULL COMMENT '备注',

            INDEX idx_time (operation_time),
            INDEX idx_operator (operator),
            INDEX idx_type (operation_type),
            INDEX idx_target (operation_target)
        )
        ENGINE=InnoDB
        DEFAULT CHARSET=utf8mb4
        COMMENT='操作日志';
    """)

    try:
        with config.engine.begin() as conn:
            conn.execute(sql)
        DPrint("operation_log 表已就绪")
    except Exception as e:
        DPrint(f"创建 operation_log 表失败：{e}")
        raise

# 追加记录日志
def record_operation_log(
    operator: str,
    operation_type: str,
    operation_target: str,
    sort: int = 1,
    success: bool = None,
    remark: str = ""
) -> None:
    """记录操作日志（日志写入失败不影响业务）。"""
    try:
        sql = text("""
            INSERT INTO operation_log (
                operation_time,
                operator,
                operation_type,
                operation_target,
                sort,
                result,
                remark
            )
            VALUES (
                :operation_time,
                :operator,
                :operation_type,
                :operation_target,
                :sort,
                :result,
                :remark
            )
        """)

        with config.engine.begin() as conn:
            conn.execute(sql, {
                "operator": operator,
                "operation_type": _enum_value(operation_type),
                "operation_target": _enum_value(operation_target),
                "sort": sort,
                "result": _operation_result_value(success),
                "remark": remark,
                "operation_time": datetime.now(),
            })

    except Exception as e:
        DPrint(f"记录操作日志失败：{e}")

# 查询操作日志
def query_operation_log(
    begin_dt: datetime,
    end_dt: datetime,
    offset: int,
    page_size: int,
    operator: str = None,
    operation_type: str = None,
    operation_target: str = None,
    sort: int = None,
    result: int = None,
):
    """查询操作日志，返回匹配总数和分页日志列表。"""
    where_sql = [
        "operation_time >= :begin_dt",
        "operation_time <= :end_dt",
    ]
    params = {
        "begin_dt": begin_dt,
        "end_dt": end_dt,
        "offset": offset,
        "page_size": page_size,
    }

    if operator:
        where_sql.append("operator = :operator")
        params["operator"] = operator
    if operation_type:
        where_sql.append("operation_type = :operation_type")
        params["operation_type"] = _enum_value(operation_type)
    if operation_target:
        where_sql.append("operation_target = :operation_target")
        params["operation_target"] = _enum_value(operation_target)
    if result is not None:
        where_sql.append("result = :result")
        params["result"] = _operation_result_value(result)
    if sort is not None:
        where_sql.append("sort = :sort")
        params["sort"] = sort

    where_clause = " AND ".join(where_sql)
    count_sql = text(f"""
        SELECT COUNT(*) AS total
        FROM operation_log
        WHERE {where_clause}
    """)
    data_sql = text(f"""
        SELECT
            log_id,
            operation_time,
            operator,
            operation_type,
            operation_target,
            sort,
            result,
            remark
        FROM operation_log
        WHERE {where_clause}
        ORDER BY operation_time DESC, log_id DESC
        LIMIT :offset, :page_size
    """)

    with config.engine.connect() as conn:
        total = conn.execute(count_sql, params).scalar() or 0
        rows = conn.execute(data_sql, params).fetchall()

    logs = []
    for row in rows:
        item = dict(row._mapping)
        operation_time = item.get("operation_time")
        if isinstance(operation_time, datetime):
            item["operation_time"] = operation_time.strftime("%Y-%m-%d %H:%M:%S")
        logs.append(item)

    return total, logs
