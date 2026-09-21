#!/usr/bin/env python3
import sys
from pathlib import Path
root_path = Path(__file__).parent.parent
sys.path.insert(0, str(root_path))
from flask import request, jsonify, Flask
from werkzeug.utils import secure_filename
from config import FIXED_DEVICE_ID, READ_INPUT_REGISTER, UPGRADE_STATE_MAP, HTTPS_ENABLE
from config import STATUS_DIR, STATE_ERROR, remote_client_lock, HOST_IP
from utils.utils import DPrint, now_str
import constent.common as common
import utils.method as method
from flask import Blueprint
from flask_socketio import SocketIO
import os, json
from utils.auth import init_auth, authenticate_session
from script.session_config import configure_session

upgrade = Blueprint("upgrade", __name__)


def _parse_status_request():
    """解析升级状态查询请求参数。

    返回:
        {
            'task_name': str,
            'firmware': str,
            'target': str,
            'device_ids': list
        }

    如果参数错误:
        返回 (response, http_status)
    """

    task_name = (request.args.get('taskName') or '').strip()
    firmware_category = (request.args.get('firmwareCategory') or '').strip()
    firmware = (request.args.get('firmware') or '').strip()

    device_id_args = request.args.getlist('deviceId')
    device_ip_args = request.args.getlist('deviceIP')

    # ============================================================
    # 1. 记录收到的请求参数
    # ============================================================
    DPrint(
        f"[STATUS] 请求参数: "
        f"taskName={task_name or 'N/A'}, "
        f"firmwareCategory={firmware_category or 'N/A'}, "
        f"firmware={firmware or 'N/A'}, "
        f"deviceId={device_id_args or 'N/A'}, "
        f"deviceIP={device_ip_args or 'N/A'}"
    )

    # ============================================================
    # 2. taskName 校验
    # ============================================================
    if not task_name:
        DPrint("[STATUS] 参数错误: taskName is required")

        return jsonify({
            'taskName': 'N/A',
            'status': STATE_ERROR,
            'error': 'taskName is required'
        }), 400

    # 防止 taskName 路径穿越
    if secure_filename(task_name) != task_name:
        DPrint(
            f"[STATUS] 参数错误: taskName 包含非法字符: "
            f"{task_name}"
        )

        return jsonify({
            'taskName': task_name,
            'status': STATE_ERROR,
            'error': 'taskName contains unsupported characters'
        }), 400

    # ============================================================
    # 3. 根据 firmware / firmwareCategory 判断 target
    #
    # 保持原有优先级:
    # firmware > firmwareCategory
    # ============================================================
    target = None
    firmware_upper = firmware.upper()

    if firmware_upper.startswith('LC'):
        target = 'lc'

    elif firmware_upper.startswith('PCS'):
        target = 'pcs'

    elif firmware_category:
        target = method.parse_targets(firmware_category)

    # ============================================================
    # 4. 解析设备信息
    # ============================================================
    device_ids = []

    # ------------------------------------------------------------
    # 4.1 deviceIP
    # ------------------------------------------------------------
    if any(device_ip_args):
        device_ids = method.parse_device_ids_from_ips(
            device_ip_args
        )

        DPrint(
            f"[STATUS] deviceIP解析: "
            f"{device_ip_args} -> deviceIds={device_ids}"
        )

        ip_target = None

        for device_id in device_ids:
            if device_id < 0:
                DPrint(
                    f"[STATUS] 参数错误: "
                    f"设备编号异常 {device_id} < 0"
                )

                return jsonify({
                    'taskName': task_name,
                    'status': STATE_ERROR,
                    'error': f'设备编号异常: {device_id} < 0'
                }), 400

            elif device_id == 0:
                ip_target = "2"

                DPrint(
                    "[STATUS] deviceIP检测到LC设备，"
                    "忽略PCS升级任务"
                )
                break

            else:
                ip_target = "4"

        if ip_target is None:
            DPrint(
                "[STATUS] 参数错误: deviceIP未解析到有效设备"
            )

            return jsonify({
                'taskName': task_name,
                'status': STATE_ERROR,
                'error': 'deviceIP is required'
            }), 400

        # deviceIP 判断结果覆盖原 target
        target = method.parse_targets(ip_target)

    # ------------------------------------------------------------
    # 4.2 deviceId
    # ------------------------------------------------------------
    elif device_id_args:
        for item in device_id_args:
            device_ids.extend(item.split(","))

        try:
            device_ids = [
                int(device_id)
                for device_id in device_ids
            ]

        except ValueError:
            DPrint(
                f"[STATUS] 参数错误: "
                f"deviceId不是有效整数: {device_id_args}"
            )

            return jsonify({
                'taskName': task_name,
                'status': STATE_ERROR,
                'error': 'deviceId must be integer'
            }), 400

    # ============================================================
    # 5. 未指定 target 时默认 LC
    # ============================================================
    if target is None:
        target = 'lc'

    # ============================================================
    # 6. 输出最终解析结果
    # ============================================================
    DPrint(
        f"[STATUS] 参数解析完成: "
        f"taskName={task_name}, "
        f"target={target}, "
        f"deviceIds={device_ids}"
    )

    return {
        'task_name': task_name,
        'firmware': firmware,
        'target': target,
        'device_ids': device_ids
    }, None

def _get_pcs_upgrade_status(task_name, device_ids):
    """读取 PCS 升级进度和状态。

    返回:
        processes
        states
        messages

    注意:
        保持原有逻辑。
        单个 PCS 读取失败不会影响其他 PCS，
        读取失败的设备直接跳过。
    """

    if not device_ids:
        return None, None, None, jsonify({
            'taskName': task_name,
            'status': STATE_ERROR,
            'error': 'deviceId/deviceIP is required for PCS status'
        }), 400

    processes = []
    states = []
    messages = []

    for device_id in device_ids:

        # --------------------------------------------------------
        # 保持原有逻辑:
        # device_id < 1 时跳过
        # --------------------------------------------------------
        if device_id < 1:
            DPrint(f"设备编号异常: {device_id} < 1")
            continue

        # --------------------------------------------------------
        # 计算寄存器地址
        # --------------------------------------------------------
        register_offset = (
            common.PCS_FAULT_STEP
            * (device_id - 1)
        )

        process_address = (
            common.PCS_BASE_UPGRADE_PROCESS_ADDR
            + register_offset
        )

        state_address = (
            common.PCS_BASE_UPGRADE_STATE_ADDR
            + register_offset
        )

        try:
            # ----------------------------------------------------
            # 读取升级进度
            # ----------------------------------------------------
            process_registers = method.query_register_data(
                FIXED_DEVICE_ID,
                READ_INPUT_REGISTER,
                process_address,
                1
            )

            # ----------------------------------------------------
            # 读取升级状态
            # ----------------------------------------------------
            state_registers = method.query_register_data(
                FIXED_DEVICE_ID,
                READ_INPUT_REGISTER,
                state_address,
                1
            )

            process = int(process_registers[0]) & 0xFFFF
            state = int(state_registers[0]) & 0xFFFF

            processes.append(process)
            states.append(state)
            messages.append("")

        except Exception as exc:
            DPrint(
                f"地址 {process_address} / "
                f"{state_address} 读取异常: {exc}"
            )

            # 保持原逻辑:
            # 当前 PCS 失败，继续读取后面的 PCS
            continue

    return processes, states, messages, None, None

def _get_lc_upgrade_status(task_name):
    """读取 LC 升级任务状态。

    LC 新升级流程只依赖:
        STATUS_DIR / <taskName>.json
    """

    status_path = STATUS_DIR / f'{task_name}.json'

    # ============================================================
    # 状态文件不存在
    # ============================================================
    if not status_path.is_file():
        DPrint(
            f"[STATUS] 升级任务不存在或尚未创建: "
            f"{task_name}"
        )

        return None, None, None, jsonify({
            'taskName': task_name,
            'process': [],
            'status': [STATE_ERROR],
            'msg': ['升级任务不存在或尚未创建'],
        }), 404

    # ============================================================
    # 读取任务状态
    # ============================================================
    process, state, remark = method.get_job_upgrade_status(
        task_name,
        STATUS_DIR,
        UPGRADE_STATE_MAP
    )

    return (
        [process],
        [state],
        [remark],
        None,
        None
    )


@upgrade.route('/api/upgrade/process', methods=['GET'])
def status_get():
    """查询升级进度。

    LC:
        通过 taskName 对应的状态文件查询。

    PCS:
        通过 deviceId/deviceIP 对应的 PCS 升级寄存器查询。

    返回结构保持历史兼容格式。
    """

    try:
        # ========================================================
        # 1. 解析请求参数
        # ========================================================
        request_data, error_code = _parse_status_request()

        if error_code is not None:
            return request_data

        task_name = request_data['task_name']
        target = request_data['target']
        device_ids = request_data['device_ids']

        # ========================================================
        # 2. 查询升级状态
        # ========================================================
        if target in ('pcs', 'pcs-g2', 'pcs-g3'):

            (
                processes,
                states,
                messages,
                error_response,
                error_status
            ) = _get_pcs_upgrade_status(
                task_name,
                device_ids
            )

        else:
            (
                processes,
                states,
                messages,
                error_response,
                error_status
            ) = _get_lc_upgrade_status(
                task_name
            )

        # ========================================================
        # 3. 查询过程中出现 HTTP 错误
        # ========================================================
        if error_response is not None:
            return error_response, error_status

        # ========================================================
        # 4. 统一返回
        # ========================================================
        DPrint(
            f"[STATUS] 查询结果: "
            f"taskName={task_name}, "
            f"process={processes}, "
            f"status={states}, "
            f"msg={messages}"
        )
        return jsonify({
            'taskName': task_name,
            'process': processes,
            'status': states,
            'msg': messages
        }), 200

    except Exception as exc:
        DPrint(f"[STATUS] 获取状态异常: {exc}")

        return jsonify({
            'error': str(exc)
        }), 500

# 状态回读
# @upgrade.route('/api/upgrade/process', methods=['GET'])
# def status_get():
#     """查询升级进度。

#     新 LC 升级流程只依赖 taskName 对应的状态文件；PCS 仍需指定设备，
#     状态由各 PCS 的升级寄存器提供。响应结构保持历史的数组格式。
#     """
#     try:
#         job = (request.args.get('taskName') or '').strip()
#         raw_target = (request.args.get('firmwareCategory') or '').strip()
#         firmware = (request.args.get('firmware') or '').strip()
#         id_str_list = request.args.getlist("deviceId")
#         ip_str_list = request.args.getlist("deviceIP")
#         if not job:
#             return jsonify({'taskName': 'N/A', 'status': STATE_ERROR, 'error': 'taskName is required'}), 400

#         # 与 /api/upgrade/start 保持一致，防止 taskName 路径穿越到 STATUS_DIR 外。
#         if secure_filename(job) != job:
#             return jsonify({'taskName': job, 'status': STATE_ERROR,
#                             'error': 'taskName contains unsupported characters'}), 400

#         device_ids = []
#         target = None
#         firmware_upper = firmware.upper()
#         if firmware_upper.startswith('LC'):
#             target = 'lc'
#         elif firmware_upper.startswith('PCS'):
#             target = 'pcs'
#         elif raw_target:
#             target = method.parse_targets(raw_target)

#         # 保持历史 IP / deviceId 调用的兼容性；新 LC 查询不再要求设备参数。
#         if any(ip_str_list):
#             DPrint(f"Received device IP list: {ip_str_list}")
#             device_ids = method.parse_device_ids_from_ips(ip_str_list)
#             ip_target = None
#             for _id in device_ids:
#                 if _id < 0:
#                     DPrint(f"设备编号异常: {_id} < 0")
#                     return jsonify({'taskName': job, 'status': STATE_ERROR, 'error': f'设备编号异常: {_id} < 0'}), 400
#                 elif _id == 0:
#                     ip_target = "2"
#                     DPrint(f"设备编号检测到LC设备,当前查询LC升级状态,忽略PCS升级任务")
#                     break
#                 else:
#                     ip_target = "4"
#             if ip_target is None:
#                 return jsonify({'taskName': job, 'status': STATE_ERROR,
#                                 'error': 'deviceIP is required'}), 400
#             if ip_target == "4":
#                 DPrint(f"设备编号检测到PCS设备,当前查询PCS升级状态")
#             target = method.parse_targets(ip_target)
#         elif id_str_list:
#             DPrint(f"Received device ID list: {id_str_list}")
#             for item in id_str_list:
#                 device_ids.extend(item.split(","))
#             try:
#                 device_ids = [int(x) for x in device_ids]
#             except ValueError:
#                 return jsonify({'taskName': job, 'status': STATE_ERROR,
#                                 'error': 'deviceId must be integer'}), 400

#         # 未指定固件类型时，默认按照新 LC 本地升级流程读取状态文件。
#         if target is None:
#             target = 'lc'

#         DPrint(
#             f"[STATUS] 查询升级状态: taskName={job}, firmware={firmware or 'N/A'}, "
#             f"target={target}, deviceIds={device_ids}"
#         )
#         _processes = []
#         _states = []
#         _msgs = []
#         if target in ["pcs", "pcs-g2", "pcs-g3"]:
#             if not device_ids:
#                 return jsonify({'taskName': job, 'status': STATE_ERROR,
#                                 'error': 'deviceId/deviceIP is required for PCS status'}), 400
#             # 读取寄存器
#             for device_id in device_ids:
#                 if device_id < 1:
#                     DPrint(f"设备编号异常: {device_id} < 1")
#                     continue
#                 process_address = common.PCS_BASE_UPGRADE_PROCESS_ADDR + common.PCS_FAULT_STEP * (device_id - 1)
#                 state_address =  common.PCS_BASE_UPGRADE_STATE_ADDR + common.PCS_FAULT_STEP * (device_id - 1)
#                 try:
#                     process_registers = method.query_register_data(FIXED_DEVICE_ID, READ_INPUT_REGISTER, process_address, 1)
#                     state_registers = method.query_register_data(FIXED_DEVICE_ID, READ_INPUT_REGISTER, state_address, 1)
#                     _process = int(process_registers[0]) & 0xFFFF
#                     _state = int(state_registers[0]) & 0xFFFF
#                     _processes.append(_process)
#                     _states.append(_state)
#                     _msgs.append("")

#                 except Exception as e:
#                     DPrint(f"地址 {process_address} / {state_address} 读取异常: {e}")
#                     continue
#         else:
#             status_path = STATUS_DIR / f'{job}.json'
#             if not status_path.is_file():
#                 DPrint(f"[STATUS] 升级任务不存在或尚未创建: {job}")
#                 return jsonify({
#                     'taskName': job,
#                     'process': [],
#                     'status': [STATE_ERROR],
#                     'msg': ['升级任务不存在或尚未创建'],
#                 }), 404
#             _process, _state, _remark = method.get_job_upgrade_status(job, STATUS_DIR, UPGRADE_STATE_MAP)
#             _processes.append(_process)
#             _states.append(_state)
#             _msgs.append(_remark)
#         return jsonify({'taskName': job,
#                         'process': _processes,
#                         'status': _states,
#                         'msg': _msgs
#                         }), 200

#     except Exception as e:
#         DPrint(f"[STATUS] 获取状态异常: {e}")
#         return jsonify({'error': str(e)}), 500

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
    # 与主应用共享持久化密钥和数据库会话，认证不依赖 8000 服务存活。
    configure_session(app)
    init_auth(app)
    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def serve_spa(path):
        if path.startswith("api"):
            return jsonify({"error": "not found"}), 404
        return app.send_static_file("index.html")
    app.register_blueprint(upgrade)
    return app

app = create_app()
socketio = SocketIO(app)

def main():
    if HTTPS_ENABLE:
        # 仅监听回环地址，由 Nginx 提供 HTTPS 入口。
        socketio.run(app, host='127.0.0.1', port=9000, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)
        DPrint(f"[{now_str()}] [MAIN] 启动 Flask SocketIO 服务器 (127.0.0.1:9000)")
    else:
        socketio.run(app, host='0.0.0.0', port=9000, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)
        DPrint(f"[{now_str()}] [MAIN] 启动 Flask SocketIO 服务器 (0.0.0.0:9000)")

@socketio.on('connect')
def on_connect(auth=None):
    try:
        if not authenticate_session():
            return False
    except Exception:
        app.logger.exception("SocketIO authentication failed")
        return False
    DPrint(f"[{now_str()}] [SocketIO] 新客户端连接: {request.remote_addr}")

if __name__ == '__main__':
    main()
