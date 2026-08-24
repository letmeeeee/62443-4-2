#!/usr/bin/env python3
import sys
from pathlib import Path
root_path = Path(__file__).parent.parent
sys.path.insert(0, str(root_path))
from flask import request, jsonify, Flask
from config import FIXED_DEVICE_ID, READ_INPUT_REGISTER, UPGRADE_STATE_MAP
from config import STATUS_DIR, STATE_ERROR, remote_client_lock, HOST_IP
from utils.utils import DPrint, now_str
import constent.common as common
import utils.method as method
from flask import Blueprint
from flask_socketio import SocketIO
import os, json

upgrade = Blueprint("upgrade", __name__)

# 状态回读
@upgrade.route('/api/upgrade/process', methods=['GET'])
def status_get():
    try:
        job = (request.args.get('taskName') or '').strip()
        raw_target = (request.args.get('firmwareCategory') or '').strip()
        # getlist 直接拿到列表字符串
        id_str_list = request.args.getlist("deviceId")
        if not job:
            return jsonify({'taskName': 'N/A', 'status': STATE_ERROR, 'error': 'taskName is required'}), 400
        if not id_str_list:
            return jsonify({'taskName': job, 'status': STATE_ERROR, 'error': 'deviceId is required'}), 400
        # 转int列表
        deviceId = [int(x) for x in id_str_list]
        target = method.parse_targets(raw_target)
        _processes = []
        _states = []
        _msgs = []
        if not job:
            return jsonify({'error': 'Missing taskName parameter'}), 400
        if target in ["pcs-g2", "pcs-g3"]:
            # 读取寄存器
            for id in deviceId:
                if id < 1:
                    DPrint(f"设备编号异常: {id} < 1")
                    continue
                process_address = common.PCS_BASE_UPGRADE_PROCESS_ADDR + common.PCS_ADDR_STEP * (id - 1)
                state_address =  common.PCS_BASE_UPGRADE_STATE_ADDR + common.PCS_ADDR_STEP * (id - 1)
                try:
                    process_registers = method.query_register_data(FIXED_DEVICE_ID, READ_INPUT_REGISTER, process_address, 1)
                    state_registers = method.query_register_data(FIXED_DEVICE_ID, READ_INPUT_REGISTER, state_address, 1)
                    _process = int(process_registers[0]) & 0xFFFF
                    _state = int(state_registers[0]) & 0xFFFF
                    _processes.append(_process)
                    _states.append(_state)
                    _msgs.append("")

                except Exception as e:
                    DPrint(f"地址 {process_address} / {state_address} 读取异常: {e}")
                    continue
        else:
            _process, _state, _remark = method.get_job_upgrade_status(job, STATUS_DIR, UPGRADE_STATE_MAP)
            _processes.append(_process)
            _states.append(_state)
            _msgs.append(_remark)
        return jsonify({'taskName': job,
                        'process': _processes,
                        'status': _states,
                        'msg': _msgs
                        }), 200

    except Exception as e:
        DPrint(f"[STATUS] 获取状态异常: {e}")
        return jsonify({'error': str(e)}), 500

def create_app():
    # 在这里统一导入并注册
    # 获取当前 main.py 所在目录
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    # 往上跳一级，就是dist所在目录
    parent_dir = os.path.dirname(current_file_dir)
    static_folder_path = os.path.join(parent_dir, "dist")

    DPrint(f"静态前端目录: {static_folder_path}")
    DPrint(f"index.html 是否存在: {os.path.exists(os.path.join(static_folder_path, 'index.html'))}")
    app = Flask(__name__, static_folder=static_folder_path, static_url_path="/")
    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def serve_spa(path):
        if path.startswith("api"):
            return jsonify({"error": "not found"}), 404
        return app.send_static_file("index.html")
    app.register_blueprint(upgrade)
    return app

app = create_app()
socketio = SocketIO(app, cors_allowed_origins="*")

def main():
    DPrint(f"[{now_str()}] [MAIN] 启动 Flask SocketIO 升级监听程序 (127.0.0.1:9000)")
    socketio.run(app, host='127.0.0.1', port=9000, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)

@socketio.on('connect')
def on_connect():
    DPrint(f"[{now_str()}] [SocketIO] 新客户端连接: {request.remote_addr}")

if __name__ == '__main__':
    main()
