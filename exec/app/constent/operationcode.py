#  ========================= 操作日志状态码 ========================
OPERATION_LOG_STATUS_FORM = {
    "0": "Initializing",        # 初始化
    "1": "Already Stopped",     # 已经停机
    "2": "Starting",            # 已经在启动中
    "3": "Running",             # 已经在运行中
    "4": "Standby",             # 待机
    "5": "Fault",               # 故障
    "6": "Alarm",               # 告警
    "7": "Warning",             # 预警
    "11": "Stopping",           # 已经在停止中
    "13": "PCS Stop",           # PCS停机
    "14": "Subsystem Stop",     # 子系统停机
    "15": "Subsystem Startup",  # 子系统启动
    "16": "PCS Startup",        # PCS启动
    "20": "Configuring",        # 配置中
    "21": "Starting PQ mode",   # 启动PQ模式中
    "22": "PQ Mode Running",    # PQ模式运行中
    "23": "Stopping PQ Mode",   # 关闭PQ模式
    "24": "PQ Node Stopping",   # 关闭PQ模式中
    "25": "Set 0 Power",        # 下发0功率
    "27": "Partial Fault Stop"  # 一般故障停机
}
