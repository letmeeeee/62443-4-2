#!/usr/bin/env python3
import time
from config import remote_client_lock, remote_client
from utils.utils import DPrint, now_str

# ================== 后台轮询线程 ==================
def read_remote_modbus():
    try:
        if not remote_client.is_socket_open():
            DPrint(f"[{now_str()}] [REMOTE] socket 未开启，跳过读取")
            return
        with remote_client_lock:
            result = remote_client.read_input_registers(address=30000, count=10, slave=1)
        if result.isError():
            DPrint(f"[{now_str()}] [REMOTE] 读取失败: {result}")
        else:
            values = getattr(result, "registers", [])[:5]
            # 如需使用 values，可在此处处理
    except Exception as e:
        DPrint(f"[{now_str()}] [REMOTE] Modbus 异常: {e}")
        with remote_client_lock:
            remote_client.close()

def background_thread():
    DPrint(f"[{now_str()}] [BACKGROUND THREAD] 启动后台线程")
    from main import socketio
    while True:
        read_remote_modbus()
        socketio.emit('refreshData', [])
        DPrint(f"[{now_str()}] [SocketIO] emit refreshData []")
        time.sleep(1)
