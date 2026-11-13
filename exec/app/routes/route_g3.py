#!/usr/bin/env python3
import json, threading, shutil, subprocess, hashlib
from flask import request, jsonify, g
from werkzeug.utils import secure_filename
import traceback
import zipfile, tarfile, time
from datetime import datetime
from pathlib import Path
from config import DEFINE_16BIT, READ_HOLD_REGISTER, FIXED_DEVICE_ID, READ_INPUT_REGISTER, UPGRADE_STATE_MAP, PCS_REMOTE_DEST, PCS_REMOTE_DEST_TEST, REMOTE_PASSWORD_TEST,UPLOAD_DIR, SQL_TABLE_NAME, REMOTE_IPS, REMOTE_PORTS, REMOTE_USERNAME, REMOTE_PASSWORD, REMOTE_DB_FILE, LOCAL_SAVE_PATH
from constent.param_config import CONFIG_PARAMS_BY_DATA_TYPE, PCS_REACTIVE_POWER_MODE_ADDR, PCS_CONFIG_PARAM_GAP, PCS_UPGRADE_SIGNAL_ADDR
from config import HOST_IP, STATUS_DIR, STATE_ERROR, STATE_IDLE, STATE_IN_PROGRESS, STATE_DONE, PERMISSION_MAPPING_TABLE, PERMISSION_TABLE
from utils.utils import DPrint, now_str
from utils.ini import find_device, read_ini_all, _ini_get_int, _get_pcs_device_type_by_brand, _ini_get_str
from utils.method import _record_upgrade_operation, get_spc_num, load_release_note, read_status, get_folder_dict, _getlevel_permission_table, write_register_with_retry, get_addr_config, _write_ini_value, _trans_to_modbus_value, _read_ini_value, _public_config_param, query_register_data, safe_extract_tar, extract_inner_tar, parse_pcs_ip_mapping_from_ini, verify_upgrade_package, read_upgrade_package_info, _write_status, upload_ini_file_async, parse_targets, _getFaultCodeList, _getFaultDataList, query_device_sqlitedata, _apply_precision, fill_simudata2mysql, query_device_mysqldata, query_fault_list, makeFaultListFromMysqlHistoryReg, CheckFaultFromRows, query_fault_poschange, query_device_alarm_data, _public_param, _read_param_value, _build_params_list_for_data_type
from utils.systemctl import start_rollback, run_upgrade_async, scp_send_async, check_network, scp_download, query_pcs_upgrade_status, clear_remote_upgrade_folder
from constent.dataset import TABLE_PREFIX_MAP, mysql_mapping
from constent.device_info import DEVICE_TYPE, PCS_BRAND
from constent.common import BMS_FAULT_STEP, PCS_FAULT_STEP, MV_FAULT_STEP
from constent.paramType_list import PARAMS_BY_DATA_TYPE
import constent.device_config_param  as device_config_param
from constent.device_pcs_param import DEVICE_PCS_ALL_REGS
from constent.device_bms_param import DEVICE_BMS_ALL_REGS
from constent.device_all_param import ALL_REG_LIST
from constent.bms_fault import BMS_CHECK_ADDR_LIST, BMS_FAULT_ADDR_LIST, BMS_WARNING_ADDR_LIST
from constent.pcs_fault import PCS_CHECK_ADDR_LIST, PCS_FAULT_ADDR_LIST, PCS_WARNING_ADDR_LIST
from constent.mv_fault import MV_FAULT_ADDR_LIST
from constent.device_info import SYSTEM_CONSISTENCY_CHECK_LIST
from utils.upgrade_index import UpgradePackageIndex
import constent.fault_all as fault_all
import constent.common as common
import utils.systemctl as systemctl
import utils.method as method
import config
from flask import Blueprint, Response
import utils.operationLog as operationLog

g3_bp = Blueprint("g3", __name__)
PUBLIC_KEY_PATH = Path("/home/zlg/app/keys/ota_public_key.pem")
UPGRADE_PACKAGE_DIR = UPLOAD_DIR / "packages"
# SSH 通道仅控制本机当前运行状态，不修改开机自启设置。
SSH_SERVICE_UNITS = ("ssh.service", "sshd.service", "dropbear.service")
SSH_CONTROL_LOCK = threading.Lock()


def _ssh_systemctl(*args, allow_missing=False):
    result = subprocess.run(
        ["systemctl", "--no-ask-password", *args],
        capture_output=True, text=True, timeout=15,
    )
    missing = allow_missing and "LoadState=not-found" in result.stdout.splitlines()
    if result.returncode != 0 and not missing:
        raise RuntimeError(result.stderr.strip() or "systemctl command failed")
    return result.stdout.strip()


def _ssh_unit_state(unit):
    output = _ssh_systemctl("show", unit, "--property=LoadState,ActiveState", allow_missing=True)
    properties = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
    if properties.get("LoadState") == "not-found":
        return None
    if properties.get("LoadState") not in ("loaded", "masked"):
        raise RuntimeError("Cannot load SSH unit: " + unit)
    state = properties.get("ActiveState")
    if not state:
        raise RuntimeError("Cannot query SSH unit state: " + unit)
    return state


def _ssh_status():
    for service in SSH_SERVICE_UNITS:
        state = _ssh_unit_state(service)
        if state is not None:
            # 停止服务时同时停止 socket，避免新连接重新激活服务。
            socket_unit = service.replace(".service", ".socket")
            socket_state = _ssh_unit_state(socket_unit)
            return {
                "service": service,
                "state": state,
                "socket": socket_unit if socket_state is not None else None,
                "socketState": socket_state,
                "enabled": state == "active" or socket_state == "active",
            }
    raise RuntimeError("No supported SSH service found")


@g3_bp.route('/api/system/ssh/status', methods=['GET'])
def get_ssh_status():
    """查询本机 SSH 服务及 socket 当前状态；需要登录。"""
    if not getattr(g, "current_user", None):
        return jsonify(success=False, error="Authentication required"), 401
    try:
        with SSH_CONTROL_LOCK:
            status = _ssh_status()
        return jsonify(success=True, **status), 200
    except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
        DPrint(f"[SSH] status query failed: {exc}")
        return jsonify(success=False, error="Unable to query SSH status"), 503


@g3_bp.route('/api/system/ssh', methods=['POST'])
def set_ssh_enabled():
    """管理员设置本机 SSH 开关，请求 JSON: {"enabled": true/false}。"""
    user = getattr(g, "current_user", None)
    if not user:
        return jsonify(success=False, error="Authentication required"), 401
    body = request.get_json(silent=True)
    success = False
    remark = "SSH control rejected"
    try:
        if user.get("permission") not in config.PERMISSION_TABLE.get("usermanage", []):
            remark = "Administrator permission required"
            return jsonify(success=False, error=remark), 403
        if not isinstance(body, dict) or type(body.get("enabled")) is not bool:
            remark = "enabled must be boolean"
            return jsonify(success=False, error=remark), 400
        enabled = body["enabled"]
        remark = "Enable SSH" if enabled else "Disable SSH"
        with SSH_CONTROL_LOCK:
            status = _ssh_status()
            if not enabled and status["socket"]:
                _ssh_systemctl("stop", status["socket"])
            _ssh_systemctl("start" if enabled else "stop", status["service"])
            status = _ssh_status()
            settled_states = ("inactive", "failed")
            success = (status["state"] == "active" if enabled else
                       status["state"] in settled_states and
                       status["socketState"] in (*settled_states, None))
            if not success:
                raise RuntimeError("SSH did not reach requested state")
        return jsonify(success=True, **status), 200
    except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
        DPrint(f"[SSH] control failed: {exc}")
        remark += ": failed"
        return jsonify(success=False, error="Unable to change SSH status"), 503
    finally:
        operationLog.enqueue_operation_log(
            user["username"], operationLog.OperationType.CONTROL, "SSH", 1,
            operationLog.OperationResult.SUCCESS if success else operationLog.OperationResult.FAIL,
            remark=remark,
        )


# ================================= api/接口定义 ===========================================
# 设备列表查询
@g3_bp.route('/api/device/list', methods=['GET'])
def GetList():
    """
    设备列表接口。

    返回结构:
    {
      "deviceList": [
        { "id": 1, "deviceType": 2, "sort": 1 },
        { "id": 2, "deviceType": 3, "sort": 1 },
        { "id": 3, "deviceType": 4, "sort": 1 },
        { "id": 4, "deviceType": 4, "sort": 2 }
      ]
    }

    生成规则:
    - PCS SKID：固定 1 个，deviceType = 2
    - PCS GROUP：数量从 [SYSTEM] sysNum 获取
    - PCS：数量从 [SYSTEM] pcsNum 获取
    - MV：固定 1 个，deviceType = 7
    - METER：固定 1 个，deviceType = 8
    - BMS BANK：数量从 [SYSTEM] bmsNum 获取

    注意:
    - id 全局递增，保证唯一。
    - sort 只在同类 deviceType 内部计数。
    """
    try:
        ini_data = read_ini_all()

        sys_num = _ini_get_int(ini_data, "SYSTEM", "sysNum", 1)
        pcs_num = _ini_get_int(ini_data, "SYSTEM", "pcsNum", 0)
        bms_num = _ini_get_int(ini_data, "SYSTEM", "bmsNum", 0)

        if sys_num < 0 or pcs_num < 0 or bms_num < 0:
            return jsonify({
                "deviceList": [],
                "error": "sysNum/pcsNum/bmsNum cannot be negative"
            }), 400

        device_list = []
        next_id = 1

        DEVICE_TYPE_REVERSE = {v: k for k, v in DEVICE_TYPE.items()}

        def add_device(device_type: int, sort_no: int):
            nonlocal next_id
            device_list.append({
                "id": next_id,
                "name": f"{DEVICE_TYPE_REVERSE.get(device_type, 'Unknown')}",
                "deviceType": device_type,
                "sort": sort_no
            })
            next_id += 1

        # 1. PCS SKID：固定 1 个，同类 sort 从 1 开始
        add_device(DEVICE_TYPE["PCS_SKID"], 1)

        # 2. PCS GROUP：数量从 sysNum 获取
        # sort 在 GROUP 类型内部计数
        for i in range(1, sys_num + 1):
            brand = _ini_get_int(
                ini_data,
                "PCS_NETWORK",
                f"pcs{i}_brand",
                PCS_BRAND["G2_DELTA"]
            )

            group_type, _pcs_type = _get_pcs_device_type_by_brand(brand)
            add_device(group_type, i)

        # 3. PCS：数量从 pcsNum 获取
        # sort 在 PCS 类型内部计数
        DPrint(PCS_BRAND)
        for i in range(1, pcs_num + 1):
            brand = _ini_get_int(
                ini_data,
                "PCS_NETWORK",
                f"pcs{i}_brand",
                PCS_BRAND["G3_SELF"]
            )
            DPrint(f"pcs{i}_brand: {brand}")

            _group_type, pcs_type = _get_pcs_device_type_by_brand(brand)
            add_device(pcs_type, i)

        # 4. MV：固定 1 个，同类 sort 为 1
        add_device(DEVICE_TYPE["MV"], 1)

        # 5. METER：固定 1 个，同类 sort 为 1
        add_device(DEVICE_TYPE["METER"], 1)

        # 6. BMS BANK：数量从 bmsNum 获取
        # sort 在 BMS BANK 类型内部计数
        for i in range(1, bms_num + 1):
            add_device(DEVICE_TYPE["BMS_BANK"], i)

        return jsonify({
            "deviceList": device_list
        }), 200

    except FileNotFoundError as e:
        DPrint(f"[{now_str()}] [/api/device/list] ini 文件不存在: {e}")
        return jsonify({
            "deviceList": [],
            "error": str(e)
        }), 404

    except Exception as e:
        DPrint(f"[{now_str()}] [/api/device/list] 服务器异常: {e}")
        return jsonify({
            "deviceList": [],
            "error": f"服务器异常: {e}"
        }), 500

# ============ PCS 具名查询与系统时间设置 ============
# PCS/系统组编号均从 1 开始，每个块偏移 300；保持旧 POST /api 兼容接口不变。
SYSTEM_TIME_WRITE_LOCK = threading.Lock()


class NamedDeviceError(Exception):
    """具名设备接口的可预期错误，携带对外错误码及 HTTP 状态。"""
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code = code
        self.status = status


def _named_device_permission(permissions, write=False):
    """使用会话身份检查权限；时间写入额外校验 CSRF，包括同源请求。"""
    user = getattr(g, 'current_user', None)
    if not isinstance(user, dict):
        raise NamedDeviceError('SESSION_INVALID', 'Authentication required', 401)
    if user.get('permission') not in permissions:
        raise NamedDeviceError('FORBIDDEN', 'Permission denied', 403)
    if write:
        import hmac
        supplied = request.headers.get('X-CSRF-Token', '')
        expected = getattr(g, 'csrf_token', '')
        if not supplied or not expected or not hmac.compare_digest(
            supplied.encode('utf-8'), expected.encode('utf-8')
        ):
            raise NamedDeviceError('CSRF_INVALID', 'CSRF token is invalid', 403)


def _named_device_counts():
    """读取配置容量，避免请求越过实际设备数量或协议支持的范围。"""
    ini_data = read_ini_all()
    pcs_num = _ini_get_int(ini_data, 'SYSTEM', 'pcsNum', -1)
    sys_num = _ini_get_int(ini_data, 'SYSTEM', 'sysNum', -1)
    if not 0 <= pcs_num <= 4 or not 0 <= sys_num <= 2:
        raise NamedDeviceError('DEVICE_UNAVAILABLE', 'Invalid device count configuration', 503)
    return pcs_num, sys_num


def _named_device_indices(name, configured, maximum):
    """解析逗号分隔序号；空字符串表示空列表，缺参、重复、越界返回 400。"""
    import re
    values = request.args.getlist(name)
    if len(values) != 1:
        raise NamedDeviceError('INVALID_DEVICE_INDEX', f'{name} is required exactly once')
    if values[0] == '':
        return []
    parts = values[0].split(',')
    if len(parts) > maximum or any(not re.fullmatch(r'[0-9]{1,2}', part) for part in parts):
        raise NamedDeviceError('INVALID_DEVICE_INDEX', f'Invalid {name} indices')
    indices = [int(part) for part in parts]
    if len(indices) != len(set(indices)) or any(
        index < 1 or index > min(configured, maximum) for index in indices
    ):
        raise NamedDeviceError('INVALID_DEVICE_INDEX', f'{name} indices are duplicate or out of range')
    return indices


def _named_device_read(address, quantity, functioncode=READ_INPUT_REGISTER):
    """用现有共享内存读取，不将缺失、短读或非法值填充成 0。"""
    from operator import index
    try:
        model = method.registers_model
        size = model.HOLD_SIZE if functioncode == READ_HOLD_REGISTER else model.INPUT_SIZE
        if address < 0 or address + quantity > size:
            raise NamedDeviceError('DEVICE_UNAVAILABLE', 'Register range is unavailable', 503)
        values = query_register_data(
            deviceid=FIXED_DEVICE_ID,
            functioncode=functioncode,
            address=address,
            quantity=quantity,
        )
        if values is None or len(values) != quantity:
            raise NamedDeviceError('DEVICE_UNAVAILABLE', 'Register data is incomplete', 503)
        words = []
        for value in values:
            if isinstance(value, bool):
                raise ValueError('Invalid boolean register value')
            word = index(value)  # 同时支持普通整数与共享内存返回的 numpy.uint16。
            if not 0 <= word <= 65535:
                raise ValueError('Register value is out of range')
            words.append(word)
        return words
    except NamedDeviceError:
        raise
    except TimeoutError:
        raise NamedDeviceError('MODBUS_TIMEOUT', 'Register read timed out', 503) from None
    except Exception:
        DPrint(f'[DEVICE] register read failed: fc={functioncode}, address={address}, '
               f'quantity={quantity}\n{traceback.format_exc()}', level='ERROR')
        raise NamedDeviceError('DEVICE_UNAVAILABLE', 'Register data is unavailable', 503) from None


def _named_device_success(data, started):
    """读取成功返回统一结构，采样时间带设备本地时区。"""
    sampled_at = datetime.now().astimezone().isoformat()
    DPrint(f'[DEVICE] {request.path} elapsed_ms={(time.monotonic() - started) * 1000:.1f}', level='DEBUG')
    return jsonify(ok=True, sampledAt=sampled_at, data=data), 200


def _named_device_failure(exc):
    """可预期错误返回业务码，未预期错误仅在服务端记录完整堆栈。"""
    if isinstance(exc, NamedDeviceError):
        if exc.status >= 500:
            DPrint(f'[DEVICE] {request.path} {exc.code}: {exc}', level='ERROR')
        return _query_error(exc.code, str(exc), exc.status)
    DPrint(f'[DEVICE] {request.path} failed\n{traceback.format_exc()}', level='ERROR')
    if isinstance(exc, (OSError, RuntimeError)):
        return _query_error('DEVICE_UNAVAILABLE', 'Device operation is unavailable', 503)
    return _query_error('INTERNAL_ERROR', 'Device operation failed', 500)


# PCS 安规码、关键配置与主从角色查询
@g3_bp.route('/api/device/pcs/verify', methods=['GET'])
def get_pcs_verify():
    """查询 PCS 校验信息。

    示例：GET /api/device/pcs/verify?pcs=1,2,3,4&groups=1,2
    pcs/groups 必填，序号不重复且不超过配置容量；空字符串表示空列表。
    返回：{ok, sampledAt, data: {standards, groups, masterSlave}}。

    安规码：FC3，12100 + (n-1)*700。
    组状态：FC3，12000 + (n-1)*700 + 0~4。
    主从机：FC3，12009 + (n-1)*700。
    每组两台 PCS，+60 bit9 对应组内第一台，+62 bit14 对应第二台。
    任一读取失败时整体失败，不返回部分成功数据。
    """
    started = time.monotonic()
    try:
        _named_device_permission(PERMISSION_TABLE.get('data', []))
        pcs_num, sys_num = _named_device_counts()
        pcs = _named_device_indices('pcs', pcs_num, 4)
        groups = _named_device_indices('groups', sys_num, 2)
        standards = []
        master_slave = []
        group_data = []

        # 0. 检查 PCS 与组数量是否匹配，避免后续读取越界。
        if not pcs and not groups:
            return _named_device_success({'standards': [], 'groups': [], 'masterSlave': []}, started)
        if sys_num <= 0 or pcs_num % sys_num != 0:
            DPrint(f"[DEVICE] Invalid PCS to group ratio: pcs_num={pcs_num}, sys_num={sys_num}", level='ERROR')
            raise NamedDeviceError(
                'DEVICE_UNAVAILABLE', 'Invalid PCS to group ratio', 503
            )
        # 1. 按选定 PCS 读取安规码和主从机角色。
        for number in pcs:
            code = _named_device_read(
                common.PCS_VERIFY_STANDARD_ADDR + (number - 1) * common.PCS_VERIFY_PARAM_STEP,
                1, READ_HOLD_REGISTER,
            )[0]
            role = _named_device_read(
                common.PCS_VERIFY_ROLE_ADDR + (number - 1) * common.PCS_VERIFY_PARAM_STEP,
                1, READ_HOLD_REGISTER,
            )[0]
            standards.append({
                'pcs': number,
                'code': code,
                'name': (common.PCS_VERIFY_STANDARD_NAMES[code]
                         if code < len(common.PCS_VERIFY_STANDARD_NAMES) else None),
            })
            master_slave.append({
                'pcs': number,
                'role': common.PCS_VERIFY_ROLE_NAMES.get(role, common.PCS_VERIFY_UNKNOWN_ROLE),
            })

        # 2. 合并读取每组状态区，在后端解析位域。
        if (pcs_num//sys_num) == 2:
            pcs_hold_step = common.PCS_GROUP_HOLD_STEP
        elif (pcs_num//sys_num) == 1:
            pcs_hold_step = common.PCS_HOLD_STEP
        else:
            DPrint(f"[DEVICE] Invalid PCS to group ratio: pcs_num={pcs_num}, sys_num={sys_num}", level='ERROR')
            raise NamedDeviceError('DEVICE_UNAVAILABLE', 'Invalid PCS to group ratio', 503)
        for group in groups:
            parallelMode = _named_device_read(common.PCS_BASE_HOLD_ADDRESS + (group - 1) * pcs_hold_step, 1, READ_HOLD_REGISTER)
            gridMode = _named_device_read(common.PCS_BASE_HOLD_ADDRESS + (group - 1) * pcs_hold_step + 2, 1, READ_HOLD_REGISTER)
            runMode = _named_device_read(common.PCS_BASE_HOLD_ADDRESS + (group - 1) * pcs_hold_step + 3, 1, READ_HOLD_REGISTER)
            parallel = []
            for position in range(pcs_num//sys_num):
                number = position + 1 + (group - 1) * (pcs_num//sys_num)
                if number > pcs_num:
                    DPrint(f"[DEVICE] PCS group {group} has no PCS at position {position + 1}", level='WARNING')
                    break
                parallel.append({
                    'pcs': number,
                    'mode': common.PCS_VERIFY_PARALLEL_MODE_NAMES.get(parallelMode[0],None),
                })
            group_data.append({
                'group': group,
                'parallelMode': parallel,
                'gridMode': common.PCS_VERIFY_GRID_MODE_NAMES.get(gridMode[0],None),
                'runMode': common.PCS_VERIFY_RUN_MODE_NAMES.get(runMode[0],None),
            })
        return _named_device_success({
            'standards': standards, 'groups': group_data, 'masterSlave': master_slave,
        }, started)
    except Exception as exc:
        return _named_device_failure(exc)


def _format_pcs_firmware_version(word):
    """按 PCS 单字位域格式化为 V主版本-子版本-功能标识。"""
    main_version = word & common.PCS_FIRMWARE_MAIN_VERSION_MASK
    sub_version = (
        word >> common.PCS_FIRMWARE_SUB_VERSION_SHIFT
    ) & common.PCS_FIRMWARE_FIELD_MASK
    function_code = (
        word >> common.PCS_FIRMWARE_FUNCTION_SHIFT
    ) & common.PCS_FIRMWARE_FIELD_MASK
    function_name = common.PCS_FIRMWARE_FUNCTION_NAMES.get(
        function_code, f'RESERVED_{function_code}'
    )
    return (f'V{main_version // 100}.{main_version % 100:02d}'
            f'-{sub_version}-{function_name}')


# PCS 固件完整版本查询
@g3_bp.route('/api/device/pcs/versions', methods=['GET'])
def get_pcs_firmware_versions():
    """读取 PCS 各固件组件版本；仅角色 3、4 可访问。

    示例：GET /api/device/pcs/versions?pcs=1,2,3,4
    返回：{ok, sampledAt, data: [{pcs, components: [{name, version}]}]}。
    FC4 从 2600 + (n-1)*300 + 4 连续读取 8 字，每个组件一个 16 位字。
    bit0～9：主版本值 /100；bit10～12：子版本；bit13～15：功能码。
    例如 100 返回 V1.00-0-M；功能码 0/1/2 为 M/P/V，3～7 显示 RESERVED_n。
    """
    started = time.monotonic()
    try:
        _named_device_permission((3, 4))
        pcs_num, _ = _named_device_counts()
        pcs = _named_device_indices('pcs', pcs_num, 4)
        data = []
        for number in pcs:
            words = _named_device_read(
                common.PCS_BASE_ADDRESS + (number - 1) * common.PCS_FAULT_STEP
                + common.PCS_FIRMWARE_VERSION_OFFSET,
                len(common.PCS_FIRMWARE_COMPONENT_NAMES),
            )
            components = []
            for name, word in zip(common.PCS_FIRMWARE_COMPONENT_NAMES, words):
                components.append({
                    'name': name,
                    'version': _format_pcs_firmware_version(word),
                })
            data.append({'pcs': number, 'components': components})
        return _named_device_success(data, started)
    except Exception as exc:
        return _named_device_failure(exc)


# LC 与 PCS 短版本查询
@g3_bp.route('/api/system/versions', methods=['GET'])
def get_system_versions():
    """查询系统版本，无入参，所有已登录角色可访问。
    PCS控制程序版本号返回的是MS CDSP 板版本号

    返回 data：{protocolVersion, softwareVersion, patchNumber, pcs: [{pcs, version}]}。
    FC4 的 1～5 为 LC 版本；每台 PCS 输入区 +5 为单字版本。
    PCS 版本沿用固件接口位域格式（如 V1.00-0-M），零值仍返回 null。
    """
    started = time.monotonic()
    try:
        _named_device_permission(PERMISSION_TABLE.get('data', []))
        pcs_num, _ = _named_device_counts()
        words = _named_device_read(1, 5)
        pcs = []
        for number in range(1, pcs_num + 1):
            version = _named_device_read(
                common.PCS_BASE_ADDRESS + (number - 1) * common.PCS_FAULT_STEP
                + common.PCS_FIRMWARE_VERSION_OFFSET,
                1,
            )
            pcs.append({
                'pcs': number,
                'version': _format_pcs_firmware_version(version[0]) if version[0] != 0 else None,
            })
        return _named_device_success({
            'protocolVersion': f'V{words[0] >> 8}.{words[0] & 0xff}',
            'softwareVersion': f'V{words[1]:02}R{words[2]:02}C{words[3]:02}',
            'patchNumber': f'SPC{words[4]:03}',
            'pcs': pcs,
        }, started)
    except Exception as exc:
        return _named_device_failure(exc)


# 重启前的系统组充放电状态查询
@g3_bp.route('/api/device/pcs/charge-state', methods=['GET'])
def get_pcs_charge_state():
    """查询各组充放电状态。

    示例：GET /api/device/pcs/charge-state?groups=1,2
    返回 data：{chargeDischarging, groups: [{group, state}]}。
    FC4，17000 + (g-1)*300 + 32～33：1 放电、2 充电，其它 idle。
    同组同时出现充电和放电时 state=unknown，但 chargeDischarging 仍为 true。
    """
    started = time.monotonic()
    try:
        _named_device_permission(PERMISSION_TABLE.get('data', []))
        _, sys_num = _named_device_counts()
        groups = _named_device_indices('groups', sys_num, 2)
        data = []
        active = False
        for group in groups:
            words = _named_device_read(17000 + (group - 1) * 300 + 32, 2)
            states = {word for word in words if word in (1, 2)}
            active = active or bool(states)
            state = 'unknown' if len(states) > 1 else 'discharge' if 1 in states else 'charge' if 2 in states else 'idle'
            data.append({'group': group, 'state': state})
        return _named_device_success({'chargeDischarging': active, 'groups': data}, started)
    except Exception as exc:
        return _named_device_failure(exc)


# 设置系统时间
@g3_bp.route('/api/system/time', methods=['POST'])
def set_system_time():
    """通过现有 FC6 写入流程设置系统时间，不直接调用 date 或重启命令。

    请求示例：POST /api/system/time
      {"datetime": "2026-11-10 12:34:56", "confirm": "SET_SYSTEM_TIME"}
    设备本地时间格式固定为 YYYY-MM-DD HH:mm:ss，年份范围 2000～2099。
    沿用参数写权限（角色 2/3/4），需会话 CSRF Token；维护模式下拒绝写入。
    成功返回 {ok: true, applied: true, reboot_scheduled_in: null}。
    1500～1505 按年/月/日/时/分/秒逐字下发；中途失败立即停止，并保留部分写入审计。
    """
    try:
        from utils import security_audit as audit
        from utils import security_store as store
        import re

        g.audit_event_type = 'system.time.set'
        g.audit_target = 'system'
        _named_device_permission(PERMISSION_TABLE.get('param', []), write=True)
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise NamedDeviceError('INVALID_QUERY', 'JSON object is required')
        if body.get('confirm') != 'SET_SYSTEM_TIME':
            raise NamedDeviceError('SET_TIME_CONFIRMATION_REQUIRED', 'confirm must be SET_SYSTEM_TIME')
        value = body.get('datetime')
        if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}', value):
            raise NamedDeviceError('SYSTEM_TIME_INVALID', 'datetime must use YYYY-MM-DD HH:mm:ss')
        try:
            target = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            raise NamedDeviceError('SYSTEM_TIME_INVALID', 'Invalid local datetime') from None
        if not 2000 <= target.year <= 2099:
            raise NamedDeviceError('SYSTEM_TIME_INVALID', 'Year must be between 2000 and 2099')

        # 1. 公共认证钩子也会检查维护模式；此处保留接口自身的写入前检查。
        with audit.engine().connect() as conn:
            if store.maintenance_state(conn)['active']:
                raise NamedDeviceError('MAINTENANCE_IN_PROGRESS', 'Maintenance mode is active', 409)

        # 2. 串行执行本接口的六次写入。审计由公共 after_request 按会话身份落库。
        with SYSTEM_TIME_WRITE_LOCK:
            g.audit_before = {'datetime': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            g.audit_after = {'datetime': value, 'applied': False, 'writtenRegisters': []}
            values = (target.year, target.month, target.day, target.hour, target.minute, target.second)
            for address, word in enumerate(values, start=1500):
                result, _ = write_register_with_retry(address, word, slave=FIXED_DEVICE_ID)
                if result is None or result.isError():
                    raise NamedDeviceError('DEVICE_UNAVAILABLE', 'System time register write failed', 503)
                g.audit_after['writtenRegisters'].append(address)
            g.audit_after['applied'] = True
        DPrint(f'[TIME] operator={g.current_user["username"]} system time set to {value}')
        return jsonify(ok=True, applied=True, reboot_scheduled_in=None), 200
    except Exception as exc:
        return _named_device_failure(exc)


# 数据参数查询
@g3_bp.route('/api/data/getParams', methods=['GET'])
def GetParams():
    """
    查询参数点表接口。

    示例:
      GET /api/data/getParams?dataType=homeView-diagram
      GET /api/data/getParams?dataType=homeView-information

    返回:
    {
      "paramsList": [
        {
          "name": "system.activePower",
          "address": 125,
          "offset": 2,
          "precision": "0.1",
          "unit": "kW"
        }
      ]
    }
    """
    try:
        data_type = str(request.args.get("dataType", "")).strip()

        if not data_type:
            return jsonify({
                "paramsList": [],
                "error": "Missing dataType",
            }), 400

        params_list = PARAMS_BY_DATA_TYPE.get(data_type)

        if params_list is None:
            return jsonify({
                "paramsList": [],
                "error": f"Unsupported dataType: {data_type}",
            }), 400

        return jsonify({
            "paramsList": [_public_param(param) for param in params_list],
        }), 200

    except Exception as e:
        DPrint(f"[{now_str()}] [/api/data/getParams] 服务器异常: {e}")
        return jsonify({
            "paramsList": [],
            "error": f"服务器异常: {e}",
        }), 500

# 测试模式,调用后续接口时,用模拟数据(value=地址)覆盖查询得到的寄存器数据,未改变寄存器值,便于前端联调
@g3_bp.route('/api/data/testMode', methods=['POST'])
def set_test_mode():
    """设置测试模式接口
    请求体:
    {
        "operatorName": str
        "testMode": true
    }
    """
    try:
        DPrint(f"[testMode] request in, current TEST_MODE={common.TEST_MODE}")

        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({
                "error": "invalid json body"
            }), 400

        if "testMode" not in body:
            return jsonify({
                "error": "missing field: testMode"
            }), 400

        operatorName = g.current_user["username"]
        test_mode = body["testMode"]

        if not isinstance(operatorName, str):
            return jsonify({
                "error": "testMode must be boolean"
            }), 400
        if not isinstance(test_mode, bool):
            return jsonify({
                "error": "testMode must be boolean"
            }), 400

        common.TEST_MODE = test_mode
        _target = "test"
        remark = ""
        operationLog.enqueue_operation_log(
            operatorName,
            operationLog.OperationType.TESTMODE,
            _target,
            1,
            operationLog.OperationResult.SUCCESS,
            remark = remark
            )
        DPrint(f"[testMode] updated -> {common.TEST_MODE}")

        return jsonify({
            "success": True,
            "testMode": common.TEST_MODE
        }), 200

    except Exception as e:
        DPrint(f"[testMode] server error: {e}")
        return jsonify({
            "success": False,
            "error": "internal server error"
        }), 500

# 数据查询
@g3_bp.route('/api/data/getData', methods=['GET'])
def GetDataByParams():
    """
    查询参数实时数据接口。

    示例:
      GET /api/data/getData?dataType=homeView-diagram
      GET /api/data/getData?dataType=homeView-information
      GET /api/data/getData?dataType=device-bms-info
    返回:
    {
      "dataList": [第1个参数的数值, 第2个参数的数值, ...]
    }

    说明:
    - dataList 顺序与 getParams 的 paramsList 顺序一致。
    - 设备地址固定为 1。
    - 字节序按大端模式处理。
    - 实际值 = 原始寄存器值 * precision。
    """
    try:
        DPrint("进入getData接口")
        data_type = str(request.args.get("dataType", "")).strip()
        DPrint("dataType:", data_type)
        if not data_type:
            return jsonify({
                "dataList": [],
                "error": "Missing dataType",
            }), 400

        # params_list = _build_params_list_for_data_type(data_type)
        params_list = PARAMS_BY_DATA_TYPE.get(data_type)

        if params_list is None:
            return jsonify({
                "dataList": [],
                "error": f"Unsupported dataType: {data_type}",
            }), 400

        data_list = []
        for param in params_list:
            # DPrint(f"[{now_str()}] [/api/data/getData]地址: {param['address']} /r")
            if param['address'] in device_config_param.COM_REG_LIST:
                value = _read_param_value(param)
                actual_value = device_config_param.SYSTEM_VIEW_COMSTATUS.get(value, "unknown status")
            elif param.get('pointMapping'):
                value = _read_param_value(param)
                if value is None:
                    actual_value = "unknown status"
                    # data_list.append(actual_value)
                elif value == 0:
                    actual_value = "status.Initialization"
                    # data_list.append(actual_value)
                else:
                    actual_value = ""
                    for bit in range(DEFINE_16BIT):
                        if (value) >> bit & 1:
                            _value = param['pointMapping'].get(bit, "unknown status")
                            if actual_value:
                                actual_value += f",{_value}"
                            else:
                                actual_value += f"{_value}"
            elif param.get('valueMapping'):
                value = _read_param_value(param)
                if value is None:
                    actual_value = "unknown status"
                else:
                    actual_value = param['valueMapping'].get(value, "unknown status")
            else:
                actual_value = _read_param_value(param)
            data_list.append(actual_value)

        return jsonify({
            "dataList": data_list,
        }), 200

    except ValueError as e:
        DPrint(f"[{now_str()}] [/api/data/getData] 参数配置错误: {e}")
        return jsonify({
            "dataList": [],
            "error": f"参数配置错误: {e}",
        }), 400

    except Exception as e:
        DPrint(f"[{now_str()}] [/api/data/getData] 服务器异常: {e}")
        traceback.print_exc()
        return jsonify({
            "dataList": [],
            "error": f"服务器异常: {e}",
        }), 500

# 多设备数据查询
@g3_bp.route('/api/data/muti/getData', methods=['GET'])
def MutiGetDataByParams():
    """
    查询多设备参数实时数据接口。

    示例:
      GET /api/data/muti/getData?dataType=device-bms-info

    返回:
      {
        "data1": [...],
        "data2": [...],
        ...
      }
    说明:
    - data1、data2 分别对应两组参数。
    - 每组 data 的顺序与 getParams 的 paramsList 顺序一致。
    - 当未检测到合法dataType默认返回两组空列表
    """
    try:
        DPrint("进入mutiGetData接口")
        data_type = str(request.args.get("dataType", "")).strip()
        DPrint("dataType:", data_type)
        ini_data = read_ini_all()
        pcs_num = _ini_get_int(ini_data, "SYSTEM", "pcsNum", 0)
        bms_num = _ini_get_int(ini_data, "SYSTEM", "bmsNum", 0)

        # Determine data_group based on data_type
        if data_type == "device-bms-info" or data_type == "systemView-bms":
            data_group = bms_num
            data_step = BMS_FAULT_STEP
        elif data_type == "device-pcs-master" or data_type == "device-pcs-slave":
            data_group = pcs_num // 2  # 主从设备地址间隔为 2
            data_step = PCS_FAULT_STEP * 2
        elif data_type == "systemView-pcs":
            data_group = pcs_num
            data_step = PCS_FAULT_STEP
        else:
            return jsonify({
                "dataList": [],
                "error": "unsupported dataType",
            }), 400

        if not data_type:
            return jsonify({
                "dataList": [],
                "error": "Missing dataType",
            }), 400

        if pcs_num < 0 or bms_num < 0:
            return jsonify({
                "deviceList": [],
                "error": "pcsNum/bmsNum cannot be negative"
            }), 400

        base_params_list = PARAMS_BY_DATA_TYPE.get(data_type)

        params_list = _build_params_list_for_data_type(base_params_list, data_type, data_group, data_step)

        if params_list is None:
            error_data = {f"data{i+1}": [] for i in range(data_group)}
            return jsonify({**error_data, "error": f"Unsupported dataType: {data_type}"}), 400

        data_list = []
        for param in params_list:
            # DPrint(f"[{now_str()}] [/api/data/getData]地址: {param['actual_address']} /r")
            # 通讯状态寄存器
            if param['address'] in device_config_param.COM_REG_LIST:
                value = _read_param_value(param)
                actual_value = device_config_param.SYSTEM_VIEW_COMSTATUS.get(value, "unknown status")
                # data_list.append(actual_value)
            # 模式状态寄存器
            elif param.get('pointMapping'):
                value = _read_param_value(param)
                if value is None:
                    actual_value = "unknown status"
                    # data_list.append(actual_value)
                elif value == 0:
                    actual_value = "status.Initialization"
                    # data_list.append(actual_value)
                else:
                    actual_value = ""
                    for bit in range(DEFINE_16BIT):
                        if (value) >> bit & 1:
                            if param['pointMapping'] is None:
                                _value = f"{param['address']}unknown status"
                            else:
                                _value = param['pointMapping'].get(bit, "unknown status")
                            if actual_value:
                                actual_value += f",{_value}"
                            else:
                                actual_value += f"{_value}"
                # data_list.append(actual_value)
            elif param.get('valueMapping'):
                value = _read_param_value(param)
                if value is None:
                    actual_value = "unknown status"
                else:
                    if param['valueMapping'] is None:
                        _value = f"{param['address']}unknown status"
                    else:
                        actual_value = param['valueMapping'].get(value, "unknown status")
            # 故障/告警寄存器
            elif param["address"] in BMS_FAULT_ADDR_LIST + BMS_WARNING_ADDR_LIST + PCS_FAULT_ADDR_LIST + PCS_WARNING_ADDR_LIST + MV_FAULT_ADDR_LIST:
                value = _read_param_value(param)
                if value is None:
                    actual_value = "unknown status"
                    # data_list.append(actual_value)
                elif value == 0:
                    actual_value = "status.Normal"
                    # data_list.append(actual_value)
                else:
                    actual_value = ""
                    for bit in range(DEFINE_16BIT):
                        if (value >> bit) & 1:
                            if fault_all.FAULT_TABLE_ALL.get(param["address"]) is None:
                                _value = f"{param['address']}unknown status"
                            else:
                                _value = fault_all.FAULT_TABLE_ALL.get(param["address"]).get(bit, "unknown status")
                            if actual_value:
                                actual_value += f",{_value}"
                            else:
                                actual_value += f"{_value}"
            # 普通寄存器
            else:
                actual_value = _read_param_value(param)
            data_list.append(actual_value)

        group_size = len(data_list) // data_group
        data_groups = {}
        for i in range(data_group):
            start = i * group_size
            end = (i + 1) * group_size
            data_groups[f"data{i+1}"] = data_list[start:end]
        
        return jsonify(data_groups), 200

    except ValueError as e:
        DPrint(f"[{now_str()}] [/api/data/muti/getData] 参数配置错误: {e}")
        error_data = {f"data{i+1}": [] for i in range(data_group)}
        return jsonify({**error_data, "error": f"参数配置错误: {e}"}), 400

    except Exception as e:
        DPrint(f"[{now_str()}] [/api/data/muti/getData] 服务器异常: {e}")
        traceback.print_exc()
        error_data = {f"data{i+1}": [] for i in range(data_group)}
        return jsonify({**error_data, "error": f"服务器异常: {e}"}), 500

# BMS预警查询
@g3_bp.route('/api/data/bms/getAlarm', methods=['GET'])
def GetBmsAlarm():
    """
    查询BMS告警数据接口。

    示例:
      GET /api/data/bms/getAlarm

    返回:
    {
        "alarmList": [
          {
            "time":  "xx",
            "dataName":  "xx",
            "alarmName":  "xx",
            "type":"xx",
            "area": "xx"
          },      
          {
            "time":  "xx",
            "dataName":  "xx",
            "alarmName":  "xx",
            "type":"xx",
            "area": "xx"
          },  
          ]
    }
    """
    try:
        ini_data = read_ini_all()
        bms_num = _ini_get_int(ini_data, "SYSTEM", "bmsNum", 0)
        alarmList = query_device_alarm_data(BMS_CHECK_ADDR_LIST, bms_num, BMS_FAULT_STEP, DEVICE_BMS_ALL_REGS)
        return jsonify({
            "alarmList": alarmList
        }), 200

    except Exception as e:
        DPrint(f"[{now_str()}] [/api/data/bms/getAlarm] 服务器异常: {e}")
        return jsonify({
            "paramsList": [],
            "error": f"服务器异常: {e}",
        }), 500

# PCS预警查询
@g3_bp.route('/api/data/pcs/getAlarm', methods=['GET'])
def GetPcsAlarm():
    """
    查询PCS告警数据接口。

    示例:
      GET /api/data/pcs/getAlarm

    返回:
    {
        "alarmList": [
          {
            "time":  "xx",
            "dataName":  "xx",
            "alarmName":  "xx",
            "type":"xx",
            "area": "xx"
          },      
          {
            "time":  "xx",
            "dataName":  "xx",
            "alarmName":  "xx",
            "type":"xx",
            "area": "xx"
          },  
          ]
    }
    """
    try:
        data_type = str(request.args.get("dataType", "")).strip()
        if not data_type:
            return jsonify({"dataList": [], "error": "Missing dataType",}), 400
        
        ini_data = read_ini_all()
        pcs_num = _ini_get_int(ini_data, "SYSTEM", "pcsNum", 0)
        alarmList = query_device_alarm_data(PCS_CHECK_ADDR_LIST, pcs_num // 2, PCS_FAULT_STEP * 2, DEVICE_PCS_ALL_REGS, data_type)
        return jsonify({
            "alarmList": alarmList
        }), 200

    except Exception as e:
        DPrint(f"[{now_str()}] [/api/data/pcs/getAlarm] 服务器异常: {e}")
        return jsonify({
            "paramsList": [],
            "error": f"服务器异常: {e}",
        }), 500

def _query_error(code, message, status=400):
    """为本轮修复的历史和录波接口提供可追踪的错误响应。"""
    from uuid import uuid4

    trace = getattr(g, 'trace_id', None) or str(uuid4())
    g.trace_id = trace
    response = jsonify(ok=False, code=code, message=message, trace_id=trace)
    response.headers['X-Trace-Id'] = trace
    return response, status


def _query_positive_integer(name, default=None):
    """校验查询中的正整数，避免缺参时泄露 int(None) 等内部异常。"""
    value = request.args.get(name, default)
    if value is None or value == '':
        raise ValueError(f'{name} is required')
    if not str(value).isascii() or not str(value).isdigit() or int(value) < 1:
        raise ValueError(f'{name} must be a positive integer')
    return int(value)


def _query_time_range(allow_date=False):
    """校验设备本地时间；历史数据用 T 分隔，录波额外允许仅日期。"""
    import re

    values = []
    parsed = []
    for name in ('beginDt', 'endDt'):
        value = request.args.get(name, '')
        fmt = '%Y-%m-%dT%H:%M:%S'
        pattern = r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}'
        if allow_date and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            fmt = '%Y-%m-%d'
            pattern = r'\d{4}-\d{2}-\d{2}'
        if not re.fullmatch(pattern, value):
            raise ValueError(f'{name} must use YYYY-MM-DDTHH:mm:ss (local time)')
        try:
            parsed.append(datetime.strptime(value, fmt))
        except ValueError:
            raise ValueError(f'{name} is not a valid local datetime') from None
        values.append(value)
    if parsed[0] > parsed[1]:
        raise ValueError('beginDt must not be after endDt')
    return values


# 故障日志查询
@g3_bp.route('/api/history/getFault', methods=['GET'])
def GetFault():
    """
    查询历史故障数据接口。

    请求示例:
      GET /api/history/getFault?beginDt=2026-06-23T00:00:00&endDt=2026-06-23T11:01:21&pageNum=1&pageSize=10

    参数:
    beginDt: 2026-05-08T00:00:00
    endDt: 2026-05-08T09:01:21
    pageNum: 1
    pageSize: 10

    MySQL查询指令:
    SELECT Time, pcsModel, Mv, bms FROM fault20260520
    WHERE Time >= '2026-05-20T00:00:00'
    AND Time <= '2026-05-20T11:01:21'
    LIMIT 0,10;

    返回示例:
    {
        "total": 100,
        "pageNum": 1,
        "pageSize": 10,
        "faultList": [
          {
            "deviceType": "PCS",
            "deviceNum": 1,
            "time": "2026-04-15 10:23:00",
            "content": "警告1"
          },
          ...
        ]
    }
    这个回复的意思就是,从第一页读取10条记录,主要是看pcsModel, Mv, bms这几个字段是否大于0
    如果是,则代表有pcsModel/Mv/bms发生了故障,此时需要去查看对应地址的几组寄存器,
    根据寄存器的值以及对应的故障信息list来判断是什么故障,
    并将故障内容填充到content内容中,将Time字段内容填充到time内容,
    以及根据pcsModel/Mv/bms和对应DEVICE_TYPE内容填充到deviceType内容,
    deviceNum内容则是根据发生了故障变位的寄存器的地址来计算
    total是指总计发生的故障数量,pageNum和pageSize是请求体的参数,
    最后,把这整个回复返回给前端
    """
    try:
        # 参数错误在访问配置及数据库前返回 400。
        try:
            begin_dt, end_dt = _query_time_range()
            page_num = _query_positive_integer('pageNum', 1)
            page_size = _query_positive_integer('pageSize', 10)
        except ValueError as exc:
            return _query_error('INVALID_QUERY', str(exc))

        ini_data = read_ini_all()
        pcs_num = _ini_get_int(ini_data, "SYSTEM", "pcsNum", 0)
        bms_num = _ini_get_int(ini_data, "SYSTEM", "bmsNum", 0)
        mv_num = 1

        if not begin_dt or not end_dt:
            return jsonify({"error": "Missing beginDt or endDt"}), 400

        if not page_num or not page_size:
            return jsonify({"error": "Missing page_num or page_size"}), 400

        if pcs_num < 0 or bms_num < 0:
            return jsonify({
                "deviceList": [],
                "error": "pcsNum/bmsNum cannot be negative"
            }), 400

        # 提取日期构造表名
        date_str = begin_dt.split('T')[0].replace('-', '')
        table_name = f"fault{date_str}"

        # 计算 offset
        offset = (page_num - 1) * page_size

        # TEST 强制进入故障查询逻辑
        if common.TEST_MODE:
            timestr = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            fill_simudata2mysql(table_name, timestr)
            DPrint("common.TEST_MODE is ON, inserted simulated fault data into MySQL")

        # 调用封装的查询函数
        rows = query_fault_list(table_name, begin_dt, end_dt, offset, page_size)
        DPrint("Get fault list succeed!")
        DPrint(f"query_fault_list returned {len(rows)} rows")

        # 按设备类型查询是否发生故障
        pcs_fault, mv_fault, bms_fault = CheckFaultFromRows(rows)

        # 某类设备发生了故障,查询其日志文件所有时间戳的故障字段,比分批查表效率更高
        DPrint(f"pcs_fault: {pcs_fault}, mv_fault: {mv_fault}, bms_fault: {bms_fault}")
        pcs_regs = None
        mv_regs = None
        bms_regs = None
        if pcs_fault:
            pcs_regs = query_fault_poschange(table_name, begin_dt, end_dt, offset, 
                                             page_size, PCS_FAULT_ADDR_LIST, 
                                             PCS_FAULT_STEP, pcs_num)
        if mv_fault:
            mv_regs = query_fault_poschange(table_name, begin_dt, end_dt, offset, 
                                            page_size, MV_FAULT_ADDR_LIST, 
                                            MV_FAULT_STEP, mv_num)
        if bms_fault:
            bms_regs = query_fault_poschange(table_name, begin_dt, end_dt, offset, 
                                             page_size, BMS_FAULT_ADDR_LIST, 
                                             BMS_FAULT_STEP, bms_num)

        if pcs_fault or mv_fault or bms_fault:
            DPrint(f"pcs:{pcs_regs},\nmv:{mv_regs},\nbms_regs:{bms_regs}")

        fault_list = []
        row_idx = 0
        total = 0

        # 按行检查故障标志位
        for row in rows:
            time_str = str(row.Time)
            DPrint(f"row.pcsModel:{row.pcsModel}, row.Mv:{row.Mv}, row.bms:{row.bms}")
            if (pcs_fault or 0) > 0:
                register_row = pcs_regs[row_idx] if row_idx < len(pcs_regs) else None
                total += row.pcsModel
                for i in range(len(PCS_FAULT_ADDR_LIST)):
                    fault_list.extend(makeFaultListFromMysqlHistoryReg(register_row, time_str, list(DEVICE_TYPE.keys())[4], PCS_FAULT_ADDR_LIST[i], PCS_FAULT_STEP, pcs_num))
            if (mv_fault or 0) > 0:
                register_row = mv_regs[row_idx] if row_idx < len(mv_regs) else None
                total += row.Mv
                for i in range(len(MV_FAULT_ADDR_LIST)):
                    fault_list.extend(makeFaultListFromMysqlHistoryReg(register_row, time_str, list(DEVICE_TYPE.keys())[5], MV_FAULT_ADDR_LIST[i], MV_FAULT_STEP, mv_num))
            if (bms_fault or 0) > 0:
                register_row = bms_regs[row_idx] if row_idx < len(bms_regs) else None
                total += row.bms
                for i in range(len(BMS_FAULT_ADDR_LIST)):
                    fault_list.extend(makeFaultListFromMysqlHistoryReg(register_row, time_str, list(DEVICE_TYPE.keys())[7], BMS_FAULT_ADDR_LIST[i], BMS_FAULT_STEP, bms_num))
            row_idx += 1

        return jsonify({
            "total": total,
            "pageNum": page_num,
            "pageSize": page_size,
            "faultList": fault_list
        }), 200

    except Exception as e:
        DPrint(f"[{now_str()}] [/api/history/getFault] 服务器异常: {e}")
        return _query_error('INTERNAL_ERROR', 'Fault history query failed', 500)

# 操作日志查询
@g3_bp.route('/api/history/getOperationlog', methods=['GET'])
def GetOperationlog():
    from utils.security_audit import query_records
    try:
        return jsonify(query_records(request.args, business=True))
    except (ValueError, TypeError):
        return jsonify(ok=False, code='INVALID_QUERY', message='Invalid business log query'), 400


@g3_bp.route('/api/history/getDeviceData', methods=['GET'])
def GetDeviceData():
    """
    查询设备历史数据接口,主要设备为pcsmodel、bms、mv

    请求示例:
      GET /api/history/getDeviceData?id=6&beginDt=2026-05-08T00:00:00&endDt=2026-05-08T09:01:21&pageNum=1&pageSize=10

    MySQL查询指令:
    SELECT * FROM pcsmodel20260508
    WHERE Time >= '2026-05-08T00:00:00'
    AND Time <= '2026-05-08T09:01:21'
    LIMIT 0,10;

    返回示例:
    {
        "id": 1,
        "total": 100,
        "pageNum": 1,
        "pageSize": 10,
        "DataList": [
          {
            "id": 1,
            "time": "2026-04-15 10:23:00",
            "字段1": 1,
            "字段1": 1,
            ...
          },
          ...
        ]
    }
    """
    try:
        # ----------------------------------
        # 1. 获取 GET 参数
        # ----------------------------------
        try:
            device_id = _query_positive_integer('id')
            begin_dt, end_dt = _query_time_range()
            page_num = _query_positive_integer('pageNum', 1)
            page_size = _query_positive_integer('pageSize', 10)
        except ValueError as exc:
            return _query_error('INVALID_QUERY', str(exc))

        ini_data = read_ini_all()
        pcs_num = _ini_get_int(ini_data, "SYSTEM", "pcsNum", 0)
        bms_num = _ini_get_int(ini_data, "SYSTEM", "bmsNum", 0)
        mv_num = 1
        if not begin_dt or not end_dt:
            return jsonify({"error": "Missing beginDt or endDt"}), 400

        if not page_num or not page_size:
            return jsonify({"error": "Missing page_num or page_size"}), 400
        if pcs_num < 0 or bms_num < 0:
            return jsonify({
                "deviceList": [],
                "error": "pcsNum/bmsNum cannot be negative"
            }), 400
        offset = (page_num - 1) * page_size
        device_info = None
        device_info = find_device(device_id)
        DPrint(device_info)
        # ----------------------------------
        # 2. 查设备信息
        # ----------------------------------
        if not device_info:
            return _query_error('DEVICE_NOT_FOUND', 'Device does not exist', 404)

        device_type = device_info.get("deviceType")
        sort = device_info.get("sort")
        DPrint(f"device_type:{device_type}")
        # ----------------------------------
        # 3. 提取日期构造表名
        # ----------------------------------
        date_str = begin_dt.split('T')[0].replace('-', '')
        table_prefix = TABLE_PREFIX_MAP.get(device_type)
        if not table_prefix:
            return _query_error('DEVICE_TYPE_UNSUPPORTED', 'Device type is not supported')
        if device_type == DEVICE_TYPE.get("G3_PCS"):
            device_num = pcs_num
        if device_type == DEVICE_TYPE.get("MV"):
            device_num = mv_num
        if device_type == DEVICE_TYPE.get("BMS_BANK"):
            device_num = bms_num
        if (sort > device_num) or (sort < 1):
            return _query_error('DEVICE_NOT_FOUND', 'Device index is not configured', 404)
        table_name = f"{table_prefix}{date_str}"
        # ----------------------------------
        # 4. 查表MySQL
        # ----------------------------------
        rows = query_device_mysqldata(table_name, begin_dt, end_dt, offset, page_size, sort - 1)
        # DPrint(f"rows:{rows}")
        if not rows and (common.TEST_MODE is False):
            return jsonify(total=0, pageNum=page_num, pageSize=page_size, dataList=[]), 200
        # ----------------------------------
        # 5. 解析 rows
        # ----------------------------------
        datalist = []
        total = 0
        reg_map = {}        
        reg_list = ALL_REG_LIST.get(device_type, [])
        # 相同设备类型的设备,在MySQL存储的字段不变,比如bms1和bms2都是用"Input2600、Input2601.."等字段存储的
        for reg in reg_list:
            addr = reg.get("address")
            # 适配lc_data字段规则,32位数据用第二个字的地址命名
            if reg.get("offset") == 2:
                addr += 1
            reg_map[addr] = reg

        for row in rows:
            # SQLAlchemy Row类型
            row_dict = mysql_mapping(row)
            item = {"id": device_id,
                    "time": str(row_dict["Time"])}
            total += 1
            # DPrint(row_dict)
            # 这里有一个大字典ALL_REG_LIST,囊括所有设备的点表参数
            for mysql_column, value in row_dict.items():
                # 只处理 InputXXX字段
                if not mysql_column.startswith("Input"):
                    continue
                # 去掉 Input
                address = int(mysql_column.replace("Input", ""))
                reg = reg_map.get(address)
                # 只处理本地有配置的参数
                if reg:
                    # TEST
                    if common.TEST_MODE is True:
                        value = address
                    actual_value = _apply_precision(value, reg.get("precision"))
                    field_name = reg.get("name")
                    item[field_name] = actual_value
                    # total += 1
                #     if address == 2623:
                #         DPrint(f"{field_name}:{value}-{actual_value}")
                #         DPrint(f"reg:{reg}")
                # elif not reg:
                #     DPrint(f"未找到地址 {address} 的参数配置,请检查ALL_REG_LIST")

            datalist.append(item)

        # ----------------------------------
        # 6. 返回
        # ----------------------------------
        return jsonify({
                "total": total,
                "pageNum": page_num,
                "pageSize": page_size,
                "dataList": datalist
        }), 200

    except Exception as e:
        DPrint(f"[/api/history/getDeviceData] 服务器异常: {e}")
        return _query_error('INTERNAL_ERROR', 'Device history query failed', 500)

# 录波查询
@g3_bp.route('/api/faultRecord/getRecordList', methods=['GET'])
def GetRecordList():
    """
    查询录波记录接口

    请求示例:
      GET /api/faultRecord/getRecordList?pcsId=6&beginDt=2026-05-08T00:00:00&endDt=2026-05-08T09:01:21

    pcsId:int
    beginDt: string
    endDt: string

    pcsId指的是前面devicelist中的设备ID,根据ID找设备编号,拿到对应的IP,发SCP指令取录波文件,
    取回后本地解析,组装返回报文 
    返回示例:
    {
         "recordList": [
         "record1", "record2", "record3"
        ]
    }
    record由数据库内的字段—faultCodeOccurDate+“_”+id组成
    """
    # ----------------------------------
    # 1. 获取 GET 参数
    # ----------------------------------
    try:
        try:
            pcsid = _query_positive_integer('pcsId')
            begin_dt, end_dt = _query_time_range(allow_date=True)
        except ValueError as exc:
            return _query_error('INVALID_QUERY', str(exc))

        begin_dt = begin_dt.replace("T"," ")
        end_dt = end_dt.replace("T"," ")
        device_info = None
        device_info = find_device(pcsid)
        # ----------------------------------
        # 2. 查设备信息
        # ----------------------------------
        if not device_info:
            return _query_error('DEVICE_NOT_FOUND', 'Device does not exist', 404)
        pcs_sort = int(device_info.get("sort"))
        # 执行下载
        if pcs_sort < 1 or pcs_sort > min(len(REMOTE_IPS), len(REMOTE_PORTS)):
            return _query_error('DEVICE_NOT_FOUND', 'Device does not exist', 404)
        if not check_network(REMOTE_IPS[pcs_sort - 1], 22):
            return _query_error('DEVICE_UNREACHABLE', 'Device network is unreachable', 503)
        DPrint(f"scp:{REMOTE_IPS[pcs_sort - 1]}")
        # scp拉取远端PCS录波到本地,覆盖旧文件
        try:
            scp_download(
                remote_ip=REMOTE_IPS[pcs_sort - 1], # PCS ip
                user=REMOTE_USERNAME,               # user name
                password = REMOTE_PASSWORD,         # user password
                remote_path=REMOTE_DB_FILE,         # PCS db file path
                local_path=LOCAL_SAVE_PATH,         # local db file path
                port = 22   # PCS port
            )
        except (OSError, RuntimeError, subprocess.SubprocessError):
            return _query_error('DEVICE_UNREACHABLE', 'Device recording download failed', 503)
        rows = query_device_sqlitedata(LOCAL_SAVE_PATH, SQL_TABLE_NAME, begin_dt, end_dt)
        recordList = []
        for row in rows:
            record = f"{row['faultCodeOccurDate']}_{row['id']}"
            recordList.append(record)
        return jsonify(ok=True, recordList=recordList, list=recordList, total=len(recordList)), 200

    except Exception as e:
        DPrint(f"[/api/faultRecord/getRecordList] 服务器异常: {e}")
        return _query_error('INTERNAL_ERROR', 'Fault recording query failed', 500)

@g3_bp.route('/api/faultRecord/getRecordDetails', methods=['GET'])
def GetRecordDetails():
    """
    查询指定录波内容接口

    请求示例:
      GET /api/faultRecord/getRecordDetails?recordId=int

    recordId:int

    recordId指的是getRecordList接口返回的sqlite列表的ID字段,根据入参recordId提取数据,并按规则解析
    返回示例:
    {
        "dateTime": "2026-04-15 10:23:00",
        "startPoint": 1295,
        "faultCodeList": [1,2,3,4,5,6,7,8],
        "dataList": [
          {
            "data1": [1,2,3,4,5,6],
          },
          {
            "data2": [1,2,3,4,5,6],
          },
          {
            "data3": [1,2,3,4,5,6],
          }
        ]
    }
    """
    try:
        # ----------------------------------
        # 1. 获取 GET 参数
        # ----------------------------------
        try:
            recordId = _query_positive_integer('recordId')
        except ValueError as exc:
            return _query_error('INVALID_QUERY', str(exc))

        rows = query_device_sqlitedata(LOCAL_SAVE_PATH, SQL_TABLE_NAME, record_id=recordId)
        if not rows:
            return _query_error('RECORD_NOT_FOUND', 'Fault recording does not exist', 404)
        # 解析封装录波
        fault_code_list = []
        data_list = []
        date_time = rows["faultCodeOccurDate"]
        start_point = rows["startPoint"]
        fault_code_list = _getFaultCodeList(rows)
        data_list = _getFaultDataList(rows)
        return jsonify({
                    "dateTime": date_time,
                    "startPoint": start_point,
                    "faultCodeList": fault_code_list,
                    "dataList": data_list
        }), 200

    except Exception as e:
        DPrint(f"[/api/faultRecord/getRecordDetails] 服务器异常: {e}")
        return _query_error('INTERNAL_ERROR', 'Fault recording detail query failed', 500)

# ============ 升级包存储、查询与执行 ============
def _upgrade_error(message, status_code=400):
    return jsonify({'status': STATE_ERROR, 'error': message, 'msg': message}), status_code

def _require_upgrade_permission(operator_name):
    if not operator_name:
        return "operatorName is required"
    permission_level = _getlevel_permission_table(operator_name)
    if permission_level is None:
        return "invalid user"
    if permission_level not in PERMISSION_TABLE.get("upgrade", []):
        return "No permission to upgrade"
    return None


def _safe_package_component(value, field_name):
    value = (value or "").strip()
    safe_value = secure_filename(value)
    if not value or not safe_value or safe_value != value:
        raise RuntimeError(f"{field_name} contains unsupported characters")
    return safe_value


def _saved_package_path(firmware, version):
    firmware = _safe_package_component(firmware, "firmware")
    version = _safe_package_component(version, "version")
    package_dir = UPGRADE_PACKAGE_DIR / firmware / version
    packages = sorted(path for path in package_dir.glob("*.tar.gz") if path.is_file())
    if len(packages) != 1:
        raise RuntimeError(
            f"firmware={firmware}, version={version} 的已保存升级包数量应为 1，实际 {len(packages)}"
        )
    return packages[0]


def _read_saved_package(firmware, version):
    package_path = _saved_package_path(firmware, version)
    inner_tar_name = verify_upgrade_package(package_path, PUBLIC_KEY_PATH)
    info = read_upgrade_package_info(package_path, inner_tar_name)
    return package_path, inner_tar_name, info


@g3_bp.route('/api/upgrade/file', methods=['POST'])
def upload_upgrade_file():
    """上传、验签、归档并入MySQL；upgradeEnable=1时复用统一启动流程。"""
    payload = request.get_json(silent=True) or request.form
    operator_name = (payload.get('operatorName') or '').strip()
    task_name = (payload.get('taskName') or '').strip()
    # raw_target = (payload.get('firmwareCategory') or '').strip()
    startup = (payload.get('upgradeEnable') or '').strip()
    startup_flag = 0
    if startup:
        try:
            startup_flag = int(startup)
        except ValueError:
            startup_flag = 1 if str(startup).lower() in {'true', 'yes', 'y', 'on'} else 0
    device_id_values = []
    device_ip_values = []

    if request.is_json:
        raw_device_ids = payload.get('deviceId', [])
        raw_device_ips = payload.get('deviceIP', [])
        if raw_device_ids is None:
            raw_device_ids = []
        if raw_device_ips is None:
            raw_device_ips = []
        if isinstance(raw_device_ids, (list, tuple)):
            device_id_values = [str(value) for value in raw_device_ids]
        elif raw_device_ids != '':
            device_id_values = [str(raw_device_ids)]
        if isinstance(raw_device_ips, (list, tuple)):
            device_ip_values = [str(value) for value in raw_device_ips]
        elif raw_device_ips != '':
            device_ip_values = [str(raw_device_ips)]
    else:
        device_id_values = request.form.getlist('deviceId')
        device_ip_values = request.form.getlist('deviceIP')

    operation_target = 'upgrade package upload'
    DPrint(
        f"[UPLOAD] 收到升级包上传请求: operator={operator_name or 'unknown'}, "
        f"filename={getattr(request.files.get('firmwareFile'), 'filename', '')}, "
        f"taskName={task_name or 'N/A'}"
        f"upgradeEnable={startup or 'N/A'}, deviceId={device_id_values}, deviceIP={device_ip_values}"
    )
    if task_name and ('/' in task_name or '\\' in task_name):
        _record_upgrade_operation(
            operator_name, operation_target, operationLog.OperationResult.FAIL,
            'taskName must not contain / or \\'
        )
        return _upgrade_error('taskName must not contain / or \\')
    if task_name and secure_filename(task_name) != task_name:
        _record_upgrade_operation(
            operator_name, operation_target, operationLog.OperationResult.FAIL,
            'taskName contains unsupported characters'
        )
        return _upgrade_error('taskName contains unsupported characters')
    if not task_name:
        _record_upgrade_operation(
            operator_name, operation_target, operationLog.OperationResult.FAIL,
            'taskName is required'
        )
        return _upgrade_error('taskName is required')
    if not operator_name:
        _record_upgrade_operation(
            operator_name, operation_target, operationLog.OperationResult.FAIL, 'operatorName is required'
        )
        return _upgrade_error('operatorName is required')

    permission_error = _require_upgrade_permission(operator_name)
    if permission_error:
        _record_upgrade_operation(
            operator_name, operation_target, operationLog.OperationResult.FAIL, permission_error
        )
        return _upgrade_error(permission_error, 403)

    firmware_file = request.files.get('firmwareFile')
    if firmware_file is None or not firmware_file.filename:
        _record_upgrade_operation(
            operator_name, operation_target, operationLog.OperationResult.FAIL, 'no upgrade file'
        )
        return _upgrade_error('no upgrade file')
    safe_name = secure_filename(firmware_file.filename)
    if not safe_name or not safe_name.lower().endswith('.tar.gz'):
        _record_upgrade_operation(
            operator_name, operation_target, operationLog.OperationResult.FAIL, 'invalid package extension'
        )
        return _upgrade_error('必须上传 .tar.gz 升级包')

    incoming_dir = UPGRADE_PACKAGE_DIR / f".incoming_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    incoming_dir.mkdir(parents=True, exist_ok=False)
    incoming_path = incoming_dir / safe_name
    try:
        invalid_device_ips = []
        parsed_device_ids = []
        # 必须在后台任务启动前解析，才能将无效 IP 返回给调用方。
        if startup_flag == 1 and device_ip_values:
            parsed_device_ids = method.parse_device_ids_from_ips(
                device_ip_values, invalid_ips=invalid_device_ips,
            )
            if not parsed_device_ids:
                raise ValueError(f"未找到对应 PCS 或 LC 设备: {', '.join(invalid_device_ips)}")
            parsed_device_ids = sorted(set(parsed_device_ids))
        firmware_file.save(incoming_path)
        DPrint(f"[UPLOAD] 临时文件已保存，开始验签: {incoming_path}")
        inner_tar_name = verify_upgrade_package(incoming_path, PUBLIC_KEY_PATH)
        info = read_upgrade_package_info(incoming_path, inner_tar_name)
        firmware = _safe_package_component(info['firmware'], 'firmware')
        version = _safe_package_component(info['version'], 'version')
        operation_target = firmware
        DPrint(
            f"[UPLOAD] 验签及元数据读取成功: firmware={firmware}, version={version}, "
            f"inner_tar={inner_tar_name}, scan_path={info['scan_path']}"
        )
        package_dir = UPGRADE_PACKAGE_DIR / firmware / version
        package_dir.mkdir(parents=True, exist_ok=True)
        saved_path = package_dir / safe_name
        # existing_packages = [
        #     path for path in package_dir.glob('*.tar.gz')
        #     if path.is_file() and path != saved_path
        # ]
        # if existing_packages:
        #     raise RuntimeError(
        #         f"firmware={firmware}, version={version} 已存在升级包: "
        #         f"{existing_packages[0].name}"
        #     )
        if saved_path.exists():
            saved_path.unlink()
        shutil.move(str(incoming_path), str(saved_path))
        DPrint(f"[UPLOAD] 已验签并保存升级包: {saved_path}")

        record = _upgrade_package_index().register(saved_path)
        if startup_flag == 1:
            result, http_status = _start_upgrade_payload({
                'operatorName': operator_name,
                'taskName': task_name,
                'sha256': record['package']['sha256'],
                'deviceId': device_id_values,
                'deviceIP': device_ip_values,
            })
            if http_status != 202:
                return result, http_status
            _remark = f"升级包上传并验签成功，已启动升级: version={version}, file={safe_name}"
        else:
            _write_status(task_name, STATE_DONE, 0, 'upgrade package uploaded, waiting for start command')
            _remark = f"升级包上传并验签成功，等待升级指令: version={version}, file={safe_name}"

        _record_upgrade_operation(
            operator_name,
            operation_target,
            operationLog.OperationResult.SUCCESS,
            _remark,
        )
        message = '升级包校验通过并已保存'
        if invalid_device_ips:
            ip_error = f"未找到对应 PCS 或 LC 设备: {', '.join(invalid_device_ips)}"
            message += f"；{ip_error}，已跳过这些 IP，其余有效目标设备继续升级"
            _record_upgrade_operation(
                operator_name, operation_target, operationLog.OperationResult.FAIL, ip_error,
            )
        return jsonify({
            'status': 0,
            'msg': message,
            'package': info,
            'sha256': record['package']['sha256'],
            'taskName': task_name,
            'startup': startup_flag,
        }), 200
    except Exception as exc:
        DPrint(f"[UPLOAD] 升级包校验或保存失败: {exc}")
        _record_upgrade_operation(
            operator_name,
            operation_target,
            operationLog.OperationResult.FAIL,
            f"升级包上传或验签失败: {exc}",
        )
        return _upgrade_error(str(exc))
    finally:
        shutil.rmtree(incoming_dir, ignore_errors=True)


def _catalog_upgrade_package(package_path):
    """上传或迁移时复验归档包，构建数据库记录。"""
    before = package_path.stat()
    inner_tar_name = verify_upgrade_package(package_path, PUBLIC_KEY_PATH)
    info = read_upgrade_package_info(package_path, inner_tar_name)
    if (info['firmware'], info['version']) != (
        package_path.parent.parent.name, package_path.parent.name,
    ):
        raise RuntimeError('升级包元数据与归档目录不一致')
    digest = hashlib.sha256()
    with package_path.open('rb') as package_file:
        for chunk in iter(lambda: package_file.read(1024 * 1024), b''):
            digest.update(chunk)
    after = package_path.stat()
    # 上传可能覆盖同名包，避免将不同文件的元数据、大小和摘要拼在一起。
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_ino, after.st_size, after.st_mtime_ns,
    ):
        raise RuntimeError('升级包在查询期间发生变化，请重试')
    package = {
        'firmware': info['firmware'],
        'version': info['version'],
        'file_name': package_path.name,
        'size': f'{after.st_size / (1024 * 1024):.2f}MB',
        'sha256': digest.hexdigest(),
        'creator': info['creator'],
        'created_at': datetime.fromtimestamp(after.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
        'description': info['description'],
    }
    return {'package': package, 'metadata': info, 'inner_tar_name': inner_tar_name}


def _upgrade_package_index():
    index = UpgradePackageIndex(UPGRADE_PACKAGE_DIR, PUBLIC_KEY_PATH, _catalog_upgrade_package, config.engine)
    index.ensure_schema()
    return index


def _read_package_by_sha256(sha256):
    index = _upgrade_package_index()
    package_path, record = index.find_by_sha256(sha256)
    before = index.fingerprint(package_path)
    # 数据库只用于定位；启动时重新验签并核对实际包摘要。
    inner_tar_name = verify_upgrade_package(package_path, PUBLIC_KEY_PATH)
    info = read_upgrade_package_info(package_path, inner_tar_name)
    digest = hashlib.sha256()
    with package_path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    if digest.hexdigest() != record['package']['sha256']:
        raise RuntimeError('升级包文件与数据库摘要不一致，请重新上传')
    if before != index.fingerprint(package_path):
        raise RuntimeError('升级包在启动期间发生变化，请重试')
    return package_path, inner_tar_name, info, before


@g3_bp.route('/api/upgrade/package-info', methods=['GET'])
def get_upgrade_package_info():
    """仅查询MySQL；支持firmware分类筛选，保留firmware/version单包查询。"""
    firmware = (request.args.get('firmware') or '').strip()
    version = (request.args.get('version') or '').strip()
    if version:
        if not firmware or not version:
            return _upgrade_error('firmware and version must be provided together')
        try:
            record = _upgrade_package_index().get_by_version(firmware, version)
            return jsonify({'status': STATE_DONE, 'package': record['metadata']}), 200
        except LookupError as exc:
            return _upgrade_error(str(exc), 404)
        except Exception as exc:
            return _upgrade_error(str(exc), 500)
    try:
        _upgrade_query_device_id(required=False)
        packages, errors = _upgrade_package_index().list_packages()
        if firmware:
            packages = [item for item in packages if item['firmware'].lower() == firmware.lower()]
        return jsonify({
            'status': STATE_DONE,
            'packages': packages,
            'total': len(packages),
            'errors': errors,
        }), 200
    except ValueError as exc:
        return _upgrade_error(str(exc))
    except Exception as exc:
        return _upgrade_error(str(exc), 500)



@g3_bp.route('/api/upgrade/package', methods=['DELETE'])
def delete_upgrade_package():
    """按SHA-256删除已归档升级包及MySQL记录，使用现有升级权限。"""
    payload = request.get_json(silent=True) or request.form
    operator_name = (payload.get('operatorName') or '').strip()
    permission_error = _require_upgrade_permission(operator_name)
    if permission_error:
        _record_upgrade_operation(
            operator_name, 'upgrade package delete', operationLog.OperationResult.FAIL, permission_error,
        )
        return _upgrade_error(permission_error, 403)
    try:
        digest = UpgradePackageIndex.normalize_sha256(payload.get('sha256'))
    except ValueError as exc:
        return _upgrade_error(str(exc))
    try:
        result = _upgrade_package_index().delete(digest)
    except LookupError as exc:
        _record_upgrade_operation(
            operator_name, 'upgrade package delete', operationLog.OperationResult.FAIL,
            f'sha256={digest}, error={exc}',
        )
        return _upgrade_error(str(exc), 404)
    except ValueError as exc:
        _record_upgrade_operation(
            operator_name, 'upgrade package delete', operationLog.OperationResult.FAIL,
            f'sha256={digest}, error={exc}',
        )
        return _upgrade_error(str(exc))
    except Exception as exc:
        _record_upgrade_operation(
            operator_name, 'upgrade package delete', operationLog.OperationResult.FAIL,
            f'sha256={digest}, error={exc}',
        )
        return _upgrade_error(str(exc), 500)
    message = '升级包缓存及数据库记录已删除'
    if result['file_retained']:
        message = '数据库记录已删除；缓存文件仍被其他升级包记录引用，已保留'
    elif not result['file_deleted']:
        message = '数据库记录已删除；本地缓存文件原本不存在'
    _record_upgrade_operation(
        operator_name, 'upgrade package delete', operationLog.OperationResult.SUCCESS,
        f'sha256={digest}, file_deleted={result["file_deleted"]}, '
        f'file_retained={result["file_retained"]}, was_current={result["was_current"]}',
    )
    return jsonify(dict(status=STATE_DONE, msg=message, **result)), 200


def _upgrade_query_device_id(required=False):
    # 当前包只描述本机，兼容旧调用中的 deviceId=0。
    value = request.args.get('deviceId')
    if value is not None and str(value) != '0':
        raise ValueError('current package only describes this device (deviceId=0)')
    return 0


@g3_bp.route('/api/upgrade/current', methods=['GET'])
def get_current_upgrade_package():
    try:
        _upgrade_query_device_id()
        firmware = (request.args.get('firmware') or 'lc').strip().lower()
        if firmware not in ('lc', 'config-file'):
            return _upgrade_error('current package firmware must be lc or config-file')
        return jsonify(dict(status=STATE_DONE, **_upgrade_package_index().current(firmware))), 200
    except ValueError as exc:
        return _upgrade_error(str(exc))
    except Exception as exc:
        return _upgrade_error(str(exc), 500)


def _payload_device_values(payload, field_name):
    """兼容 JSON 数组、表单重复字段及逗号分隔的设备参数。"""
    if isinstance(payload, dict) and not hasattr(payload, 'getlist'):
        raw_values = payload.get(field_name, [])
        if not isinstance(raw_values, (list, tuple)):
            raw_values = [raw_values]
    else:
        raw_values = payload.getlist(field_name)

    values = []
    for raw_value in raw_values:
        values.extend(str(raw_value).split(','))
    return [value.strip() for value in values if str(value).strip()]


def _select_upgrade_devices(payload, invalid_ips=None):
    """遵循旧接口策略：deviceIP 优先；包含 LC 时忽略 PCS；否则选择指定 PCS。"""
    device_ips = _payload_device_values(payload, 'deviceIP')
    device_id_values = _payload_device_values(payload, 'deviceId')

    if device_ips:
        device_ids = method.parse_device_ids_from_ips(device_ips, invalid_ips=invalid_ips)
        if not device_ids and invalid_ips:
            raise ValueError(f"未找到对应 PCS 或 LC 设备: {', '.join(invalid_ips)}")
        if any(device_id < 0 for device_id in device_ids):
            raise RuntimeError('deviceIP contains an invalid device')
        # 与旧接口一致：请求中一旦包含 LC IP，优先执行 LC 升级且忽略 PCS。
        if 0 in device_ids:
            return 'lc', []
        if not device_ids:
            raise RuntimeError('deviceIP does not map to an upgrade device')
        return 'pcs', sorted(set(device_ids))

    try:
        device_ids = [int(value) for value in device_id_values]
    except ValueError as exc:
        raise RuntimeError('deviceId must be integer') from exc

    # 直接传 LC 的设备编号 0 时，同样按 LC 处理。
    if 0 in device_ids:
        return 'lc', []
    if not device_ids:
        raise RuntimeError('deviceIP does not map to an upgrade device')
    return 'pcs', sorted(set(device_ids))


def _dispatch_pcs_upgrade(job_id, inner_tar_path, device_ids, operator_name, dispatched_device_ids):
    """同步完成PCS传输及指令下发；异常交调用方返回，临时目录由调用方清理。"""
    pcs_ip_mapping = parse_pcs_ip_mapping_from_ini()
    missing_ids = [
        device_id for device_id in device_ids
        if not pcs_ip_mapping.get(f'PCS{device_id}')
    ]
    if missing_ids:
        raise RuntimeError(f"PCS deviceId not configured: {missing_ids}")

    for device_id in device_ids:
        host = pcs_ip_mapping[f'PCS{device_id}']
        current_state = query_pcs_upgrade_status(device_id)
        DPrint(f"[UPGRADE]({job_id}) PCS{device_id} 当前升级状态: {current_state}")
        if current_state is None:
            raise RuntimeError(f"PCS{device_id} upgrade status unavailable")
        if current_state == STATE_IN_PROGRESS:
            raise RuntimeError(f"PCS{device_id} is already upgrading")
        if not clear_remote_upgrade_folder(
            REMOTE_USERNAME, host, PCS_REMOTE_DEST, REMOTE_PASSWORD
        ):
            raise RuntimeError(f"failed to clear PCS{device_id} upgrade directory")

    for index, device_id in enumerate(device_ids, start=1):
        host = pcs_ip_mapping[f'PCS{device_id}']
        DPrint(f"[UPGRADE]({job_id}) 分发升级包至 PCS{device_id}: {host}")
        ok, msg = systemctl.scp_send(
            inner_tar_path, REMOTE_USERNAME, host, PCS_REMOTE_DEST,
            password=REMOTE_PASSWORD_TEST, timeout_sec=120,
        )
        if not ok:
            raise RuntimeError(f"PCS{device_id} upgrade package transfer failed: {msg}")
        _record_upgrade_operation(
            operator_name, 'pcs', operationLog.OperationResult.SUCCESS,
            f'push pcs upgrade package {index}/{len(device_ids)}',
        )
        modbus_address = PCS_UPGRADE_SIGNAL_ADDR + (device_id - 1) * PCS_CONFIG_PARAM_GAP
        old_value = query_register_data(
            deviceid=FIXED_DEVICE_ID,
            functioncode=READ_HOLD_REGISTER,
            address=modbus_address,
            quantity=1,
        )
        if not old_value or old_value[0] == STATE_IN_PROGRESS:
            raise RuntimeError(f"PCS{device_id} upgrade signal register is busy")
        result, try_count = write_register_with_retry(modbus_address, 65535)
        if result is None or result.isError():
            raise RuntimeError(
                f"PCS{device_id} upgrade signal failed after {try_count} retries"
            )
        dispatched_device_ids.append(device_id)
        DPrint(f"[UPGRADE]({job_id}) PCS{device_id} 升级信号已下发")
        _record_upgrade_operation(
            operator_name, 'pcs', operationLog.OperationResult.SUCCESS, f'PCS{device_id} upgrade signal sent'
        )

    # 指令下发不代表升级完成；终态仍由 PCS 寄存器提供。


@g3_bp.route('/api/upgrade/start', methods=['POST'])
def start_upgrade():
    """按 sha256 唯一选择已归档包，按 file 接口的 PCS/LC 流程启动升级。"""
    return _start_upgrade_payload(request.get_json(silent=True) or request.form)


def _start_upgrade_payload(payload):
    operator_name = (payload.get('operatorName') or '').strip()
    package_sha256 = payload.get('sha256')
    version = ''
    job_id = (payload.get('taskName') or '').strip()
    operation_target = ''
    DPrint(
        f"[UPGRADE] 收到升级指令: operator={operator_name or 'unknown'}, "
        f"sha256={package_sha256}, job_id={job_id}"
    )
    permission_error = _require_upgrade_permission(operator_name)
    if permission_error:
        _record_upgrade_operation(
            operator_name, operation_target, operationLog.OperationResult.FAIL, permission_error
        )
        return _upgrade_error(permission_error, 403)

    if not package_sha256 or not job_id:
        _record_upgrade_operation(
            operator_name, operation_target, operationLog.OperationResult.FAIL,
            'sha256 and taskName are required',
        )
        return _upgrade_error('sha256 and taskName are required')
    try:
        package_sha256 = UpgradePackageIndex.normalize_sha256(package_sha256)
    except ValueError as exc:
        return _upgrade_error(str(exc))
    if secure_filename(job_id) != job_id:
        _record_upgrade_operation(
            operator_name, operation_target, operationLog.OperationResult.FAIL,
            'taskName contains unsupported characters',
        )
        return _upgrade_error('taskName contains unsupported characters')

    upgrade_target = ''
    invalid_device_ips = []
    try:
        upgrade_target, selected_device_ids = _select_upgrade_devices(payload, invalid_device_ips)
        if upgrade_target == 'pcs':
            pcs_ip_mapping = parse_pcs_ip_mapping_from_ini()
            missing_ids = [
                device_id for device_id in selected_device_ids
                if device_id < 1 or not pcs_ip_mapping.get(f'PCS{device_id}')
            ]
            if missing_ids:
                raise RuntimeError(f'PCS deviceId not configured: {missing_ids}')
        DPrint(
            f"[UPGRADE]({job_id}) 设备选择完成: target={upgrade_target}, "
            f"deviceIds={selected_device_ids}"
        )
    except Exception as exc:
        _record_upgrade_operation(
            operator_name, upgrade_target, operationLog.OperationResult.FAIL,
            f'设备选择失败: {exc}',
        )
        return _upgrade_error(str(exc))

    staging_dir = None
    started = False
    dispatched_device_ids = []
    try:
        package_path, inner_tar_name, info, package_fingerprint = _read_package_by_sha256(package_sha256)
        version = info['version']
        if info['firmware'].lower() != upgrade_target:
            if not (info['firmware'].lower() == 'config-file' and upgrade_target == 'lc'):
                raise RuntimeError('升级包 firmware 与目标设备类型不匹配')
        DPrint(
            f"[UPGRADE]({job_id}) 已定位并复验升级包: path={package_path}, "
            f"inner_tar={inner_tar_name}"
        )
        staging_dir = UPGRADE_PACKAGE_DIR / f".staging_{job_id}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        _innerpackage = method.extract_inner_tar_by_prefix(package_path, upgrade_target, staging_dir)
        if not _innerpackage:
            raise RuntimeError(f'未找到有效的 {upgrade_target.upper()} 升级包内容')
        if package_fingerprint != UpgradePackageIndex.fingerprint(package_path):
            raise RuntimeError('升级包在提取期间发生变化，请刷新升级包列表')

        if upgrade_target == 'lc':
            spc_registers = query_register_data(
                FIXED_DEVICE_ID, READ_INPUT_REGISTER, common.SYSTEM_SPC_VERSION_ADDR, 1,
            )
            if not spc_registers:
                raise RuntimeError('无法读取当前 LC SPC 版本')
            now_spc_version = int(spc_registers[0]) & 0xFFFF

            # 与 file 一致，直接使用业务 tar 的目录结构；scan_path 不作为解压根目录。
            extract_dir = staging_dir / 'content'
            extract_dir.mkdir(parents=True, exist_ok=True)
            with tarfile.open(_innerpackage, 'r') as tf:
                safe_extract_tar(tf, extract_dir)
            lc_upgrade_dir = UPLOAD_DIR / 'LC'
            lc_upgrade_dir.parent.mkdir(parents=True, exist_ok=True)
            if lc_upgrade_dir.exists():
                DPrint(f"[UPGRADE]({job_id}) 清理上一份 LC 升级内容: {lc_upgrade_dir}")
                shutil.rmtree(lc_upgrade_dir)
            extract_dir.replace(lc_upgrade_dir)

            _write_status(job_id, STATE_IN_PROGRESS, 0, f"start {upgrade_target} {version}")
            # 脚本以该参数标记旧版本备份，必须传升级前 SPC，不能传目标版本。
            started = True
            run_upgrade_async(job_id, str(now_spc_version), delay_sec=2, package_sha256=package_sha256)
            message = 'LC 升级指令已下发'
            DPrint(f"[UPGRADE]({job_id}) 已启动 {upgrade_target} {version}: {package_path}")
        else:
            started = True
            _write_status(job_id, STATE_IN_PROGRESS, 0, f"start {upgrade_target} {version}")
            _dispatch_pcs_upgrade(
                job_id, _innerpackage, selected_device_ids, operator_name, dispatched_device_ids,
            )
            message = f'PCS 升级指令已下发，目标设备: {dispatched_device_ids}'
            DPrint(
                f"[UPGRADE]({job_id}) 已完成 {upgrade_target} 升级指令下发: firmware={upgrade_target}, "
                f"version={version}, deviceIds={selected_device_ids}"
            )

        _record_upgrade_operation(
            operator_name,
            upgrade_target,
            operationLog.OperationResult.SUCCESS,
            f"升级任务已启动: sha256={package_sha256}, version={version}, taskName={job_id}, target={upgrade_target}, "
            f"deviceIds={selected_device_ids}",
        )
        if invalid_device_ips:
            ip_error = f"未找到对应 PCS 或 LC 设备: {', '.join(invalid_device_ips)}"
            message += f"；{ip_error}，已跳过这些 IP，其余有效目标设备继续升级"
            _record_upgrade_operation(
                operator_name, upgrade_target, operationLog.OperationResult.FAIL, ip_error,
            )
        return jsonify({
            'taskName': job_id,
            'sha256': package_sha256,
            'status': STATE_IN_PROGRESS,
            'package': info,
            'target': upgrade_target,
            'deviceId': selected_device_ids,
            'dispatchedDeviceId': dispatched_device_ids,
            'msg': message,
        }), 202
    except Exception as exc:
        if started:
            _write_status(job_id, STATE_ERROR, 0, str(exc))
        DPrint(f"[UPGRADE]({job_id}) 启动失败: {exc}")
        _record_upgrade_operation(
            operator_name,
            upgrade_target,
            operationLog.OperationResult.FAIL,
            f"升级指令下发失败: sha256={package_sha256}, version={version}, taskName={job_id}, error={exc}",
        )
        if upgrade_target == 'pcs' and started:
            return jsonify({
                'taskName': job_id,
                'sha256': package_sha256,
                'status': STATE_ERROR,
                'target': 'pcs',
                'deviceId': selected_device_ids,
                'dispatchedDeviceId': dispatched_device_ids,
                'undispatchedDeviceId': [i for i in selected_device_ids if i not in dispatched_device_ids],
                'error': str(exc),
                'msg': str(exc),
            }), 400
        return _upgrade_error(str(exc))
    finally:
        if staging_dir is not None:
            shutil.rmtree(staging_dir, ignore_errors=True)


# 历史单接口实现保留为未注册函数，避免上传成功后立即执行升级。
# @g3_bp.route('/api/upgrade/file', methods=['POST'])
def _legacy_upgrade_file():

    try:
        # —— 打印收到的表单键 ——
        f = request.files.get('firmwareFile')
        operatorName = (request.form.get('operatorName') or '').strip()
        job_name = (request.form.get('taskName') or '').strip()
        # releaseVersion = (request.form.get('releaseVersion') or '').strip()
        raw_target = (request.form.get('firmwareCategory') or '').strip()
        startup = (request.form.get('upgradeEnable') or '').strip()
        operationTarget = ""
        sort = []
        deviceId =[]
        _result = operationLog.OperationResult.FAIL
        remark = ""
        job_id = ""
        global releaseVersion
        releaseVersion = 0
        # getlist 直接拿到列表字符串
        id_str_list = request.form.getlist("deviceId")
        ip_str_list = request.form.getlist("deviceIP")

        if startup is None or startup.strip() == "":
            _startup = 0
        else:
            _startup = int(startup.strip())
        if not job_name:
            remark = f"'taskName': 'N/A', 'status': {STATE_ERROR}, 'error': 'taskName is required'"
            return jsonify({'taskName': 'N/A', 'status': STATE_ERROR, 'error': 'taskName is required'}), 400
        if not id_str_list and not ip_str_list:
            remark = f"'taskName': {job_name}, 'status': {STATE_ERROR}, 'error': 'deviceId/deviceIP is required'"
            return jsonify({'taskName': job_name, 'status': STATE_ERROR, 'error': 'deviceId/deviceIP is required'}), 400
        if any(ip_str_list):
            DPrint(f"Received device IP list: {ip_str_list}")
            deviceId = method.parse_device_ids_from_ips(ip_str_list)
            for _id in deviceId:
                if _id < 0:
                    DPrint(f"设备编号异常: {_id} < 0")
                    return jsonify({'taskName': job_name, 'status': STATE_ERROR, 'error': f'设备编号异常: {_id} < 0'}), 400
                elif _id == 0:
                    ip_target = "2"
                    DPrint(f"设备编号检测到LC设备,即将执行LC升级,忽略PCS升级任务")
                    break
                else:
                    ip_target = "4"
            if ip_target == "4":
                DPrint(f"设备编号检测到PCS设备,即将执行PCS升级")
            target = method.parse_targets(ip_target)
        else:
            DPrint(f"Received device ID list: {id_str_list}")
            deviceId = [int(x) for x in id_str_list]
            # 转int列表
            target = parse_targets(raw_target)
        # 目标为PCS或LC,其中LC为单一目标,不处理设备ID列表
        operationTarget = target
        ini_data = read_ini_all()
        pcs_num = _ini_get_int(ini_data, "SYSTEM", "pcsNum", 0)
        pcs_id = [int(x) for x in range(1, pcs_num + 1)]
        DPrint(f"Received upload request: job_name={job_name}, target={target}, deviceId={deviceId}")
        DPrint(f"PCS devices configured in ini: {pcs_id}")
        # 基础参数校验
        if not target:
            remark = f"'Invalid firmwareCategory format'"
            return jsonify({'taskName': job_name, 'status': STATE_ERROR, 'error': 'Invalid firmwareCategory format'}), 400
        if not deviceId and target in ["pcs-g2", "pcs-g3"]:
            remark = f"'deviceId is required'"
            return jsonify({'taskName': job_name, 'status': STATE_ERROR, 'error': 'deviceId is required'}), 400
        if not pcs_id and target in ["pcs-g2", "pcs-g3"]:
            remark = f"'No PCS devices configured in ini file'"
            return jsonify({'taskName': job_name, 'status': STATE_ERROR, 'error': 'No PCS devices configured in ini file'}), 400
        if not operatorName:
            remark = f"'operatorName is required'"
            return jsonify({'taskName': job_name, 'status': STATE_ERROR, 'error': 'operatorName is required'}), 400 
        # if not releaseVersion:
        #     remark = f"'releaseVersion is required'"
        #     return jsonify({'taskName': job_name, 'status': STATE_ERROR, 'error': 'releaseVersion is required'}), 400
        if target in ["pcs-g2", "pcs-g3"]:
            sort = deviceId
        else:
            sort = [1]
        # 权限校验
        permission_level = _getlevel_permission_table(operatorName)
        DPrint(f"operatorName: {operatorName}, permission_level: {permission_level}")
        if permission_level is None:
            remark = f'{PERMISSION_MAPPING_TABLE.get(permission_level)}: invalid user'
            return jsonify(
                {'taskName': job_name, 'status': STATE_ERROR, 
                 'error': f'{PERMISSION_MAPPING_TABLE.get(permission_level)}: invalid user'}), 400
        if permission_level not in PERMISSION_TABLE.get("upgrade"):
            remark = f'{PERMISSION_MAPPING_TABLE.get(permission_level)}: No permission to upgrade'
            return jsonify(
                {'taskName': job_name, 'status': STATE_ERROR, 
                 'error': f'{PERMISSION_MAPPING_TABLE.get(permission_level)}: No permission to upgrade'}), 400
        # 根据配置文件检查下发的PCS序号
        for dev_id in deviceId:
            if dev_id not in pcs_id and target in ["pcs-g2", "pcs-g3"]:
                remark = f'Device ID {dev_id} not found'
                return jsonify({'taskName': job_name, 'status': STATE_ERROR, 'error': f'Device ID {dev_id} not found'}), 400
        DPrint(f"Parsed device info list: {deviceId}")

        # —— 任务名作为 job_id 使用（禁止 / 和 \）——
        if not job_name:
            remark = 'job_name is required'
            return jsonify({'taskName': job_name, 'status': STATE_ERROR, 'error': 'job_name is required'}), 400

        if '/' in job_name or '\\' in job_name:
            remark = 'job_name must not contain / or \\'
            return jsonify({'taskName': job_name, 'status': STATE_ERROR, 'error': 'job_name must not contain / or \\'}) , 400

        job_id = job_name  # 任务ID = 任务名称

        if f is None or f.filename == '':
            remark = 'no upgrade file'
            return jsonify({'taskName': job_id, 'status': STATE_ERROR, 'error': 'no upgrade file'}), 400

        # 上传lc配置文件
        if target == "config-file":
            DPrint(f"[UPLOAD]({job_id}) 处理LC.ini配置升级包")
            return upload_ini_file_async(f, job_id=job_name)

        safe_name = secure_filename(f.filename) or 'upload.tar.gz'
        if not safe_name.lower().endswith('.tar.gz'):
            remark = '必须上传 .tar.gz 升级包'
            return jsonify({'taskName': job_id, 'status': STATE_ERROR, 'error': '必须上传 .tar.gz 升级包'}), 400

        #=============
        # 校验升级包
        #=============
        work_dir = UPLOAD_DIR / f"_incoming_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{job_id}"
        work_dir.mkdir(parents=True, exist_ok=True)
        outer_zip_path = work_dir / safe_name
        f.save(outer_zip_path)

        try:
            verify_upgrade_package(outer_zip_path, PUBLIC_KEY_PATH)
            DPrint(f"[UPLOAD]({job_id}) 升级包校验通过: {outer_zip_path}")

        except Exception as e:
            shutil.rmtree(work_dir, ignore_errors=True)
            _write_status(job_id, STATE_ERROR, 0, str(e))
            DPrint(f"[UPLOAD]({job_id}) 升级包异常: {str(e)}, 已删除：{outer_zip_path}")
            remark = f"[UPLOAD]({job_id}) 升级包异常: {str(e)}"
            return jsonify({
                'taskName': job_id,
                'status': STATE_ERROR,
                'error': str(e)
            }), 400

        DPrint(f"[UPLOAD]({job_id}) 总包已保存: {outer_zip_path}")


        def _bg_process():
            try:
                if target in ["pcs-g2", "pcs-g3"]:
                    # 支持 PCS.tar / PCS2026.tar ...
                    DPrint(f"[UPLOAD]({job_id}) 处理PCS升级包")
                    pcs_inner = method.extract_inner_tar_by_prefix(outer_zip_path, 'pcs', work_dir)
                    # ===== 处理 PCS 包 =====
                    if pcs_inner:
                        DPrint(f"[UPLOAD]({job_id}) {pcs_inner.name} 已解压到: {pcs_inner}")
                        # 解析配置文件,更新PCS IP映射表
                        pcs_ip_mapping_list = parse_pcs_ip_mapping_from_ini()
                        if not pcs_ip_mapping_list:
                            return _write_status(job_id, STATE_ERROR, 0, "Please check the IP of PCS")
                        DPrint(f"[UPLOAD]({job_id}) 解析到的PCS IP映射表: {pcs_ip_mapping_list}")
                        # # 下发升级包到每个目标
                        fault_host = []
                        for idx, pcs in enumerate(pcs_ip_mapping_list, start=1):
                            host = pcs_ip_mapping_list.get(pcs)
                            if idx not in deviceId:
                                DPrint(f"[UPLOAD]({job_id}) 跳过非目标设备: PCS {idx}, IP: {host}")
                                continue
                            # 1.检查PCS升级状态
                            ret0 = query_pcs_upgrade_status(idx)
                            DPrint(f"[UPLOAD]({job_id}) PCS {idx} 升级状态: {UPGRADE_STATE_MAP.get(ret0, 'unknow status')}")
                            # TEST
                            # ret0 = STATE_DONE
                            if ret0 == STATE_IN_PROGRESS:
                                DPrint(f"[UPLOAD]({job_id}) PCS {idx} 升级状态异常: {UPGRADE_STATE_MAP.get(ret0, 'unknow status')}")
                                _write_status(job_id, STATE_ERROR, 0, f"[UPLOAD]({job_id}) PCS {idx} 升级状态异常: {ret0}")
                                fault_host.append(host)
                                break
                            # 2.清理升级路径
                            ret1 = clear_remote_upgrade_folder(REMOTE_USERNAME, host, PCS_REMOTE_DEST, REMOTE_PASSWORD)
                            if ret1 != True:
                                DPrint(f"[UPLOAD]({job_id}) 清理远程升级目录失败: {host}")
                                _write_status(job_id, STATE_ERROR, 0, f"[UPLOAD]({job_id}) 清理远程升级目录失败: {host}")
                                fault_host.append(host)
                                break
                            DPrint(f"[UPLOAD]({job_id}) 清理远程升级目录成功: {host}")
                        # 3.分发升级包
                        # global pending_count
                        # pending_count = len(deviceId)
                        deviceNum = len(deviceId)
                        systemctl.inc_pending(deviceNum)
                        if len(fault_host) == 0:
                            for idx, pcs in enumerate(pcs_ip_mapping_list, start=1):
                                host = pcs_ip_mapping_list.get(pcs)
                                if idx not in deviceId:
                                    continue
                                DPrint(f"[UPLOAD]({job_id}) 正在分发PCS升级包: {pcs}")
                                scp_send_async(pcs_inner,REMOTE_USERNAME,host,PCS_REMOTE_DEST)
                                _write_status(job_id, STATE_IN_PROGRESS, 0, f"push pcs upgrade package {idx}/{deviceNum}")
                                time.sleep(5);
                                modbus_address = PCS_UPGRADE_SIGNAL_ADDR + (idx - 1) * PCS_CONFIG_PARAM_GAP
                                old_value = query_register_data(
                                deviceid=FIXED_DEVICE_ID,
                                functioncode = READ_HOLD_REGISTER,
                                address=modbus_address,
                                quantity=1)
                                if old_value[0] == STATE_IN_PROGRESS:
                                    DPrint(f"[UPLOAD]({job_id}) PCS {pcs} 升级信号寄存器地址 {modbus_address} 当前值为 {old_value[0]}, 需要先清零")
                                    _write_status(job_id, STATE_ERROR, 0, f"PCS {pcs} 升级信号寄存器地址 {modbus_address} 当前值为 {old_value[0]}, 需要先清零")
                                else:
                                    tem_val = 65535
                                    ret, try_count = write_register_with_retry(modbus_address, tem_val)
                                    DPrint(f"addr={modbus_address}, val={tem_val}")
                                    if ret.isError() == True:
                                        _result = operationLog.OperationResult.FAIL
                                        remark = f"Upgrade Modbus reg push down failed, try {try_count} failed"
                                        DPrint(f"[UPLOAD]({job_id}) PCS {pcs} 升级信号寄存器地址 {modbus_address} 当前值为 {old_value[0]}, 下发升级信号失败,请检查PCS网络或Modbus通信")
                                        _write_status(job_id, STATE_ERROR, 0, f"PCS {pcs} 升级信号寄存器地址 {modbus_address} 当前值为 {old_value[0]}, 下发升级信号失败,请检查PCS网络或Modbus通信")
                                        return jsonify({
                                        "success": False,
                                        "msg": f"Modbus push down failed, try {try_count} failed"
                                        })
                                    remark = f"Upgrade Modbus reg push down success, try {try_count} times"
                                    DPrint(f"[UPLOAD]({job_id}) PCS {pcs} 升级信号寄存器地址 {modbus_address} 当前值为 {old_value[0]}, 已下发升级信号")
                                    _write_status(job_id, STATE_DONE, 0, f"PCS {pcs} 升级信号寄存器地址 {modbus_address} 当前值为 {old_value[0]}, 已下发升级信号")
                        else:
                            DPrint(f"[UPLOAD]({job_id}) 由于清理远程升级目录失败或PCS升级状态异常, hosts: {fault_host},中止所有PCS升级")
                    else:
                        DPrint(f"[UPLOAD]({job_id}) 未找到有效的 PCS 升级包内容")
                        _write_status(job_id, STATE_ERROR, 0, "未找到有效的 PCS 升级包内容")

                # 支持 LC.tar / LC2026.tar / LCspc102.tar ...
                elif target == "lc":

                    DPrint(f"[UPLOAD]({job_id}) 处理LC升级包")
                    lc_inner = method.extract_inner_tar_by_prefix(outer_zip_path, 'LC', work_dir)
                    # ===== 处理 LC 包 =====
                    lc_out_path = UPLOAD_DIR / "LC"
                    lc_out_path.mkdir(parents=True, exist_ok=True)
                    if lc_inner:
                        with tarfile.open(lc_inner, 'r') as tf:
                            safe_extract_tar(tf, lc_out_path)

                        DPrint(f"[UPLOAD]({job_id}) {lc_inner.name} 已解压到: {lc_out_path}")
                        _write_status(job_id, STATE_IN_PROGRESS, 0, f"{lc_inner.name} unzipped")
                        _spc_addr = common.SYSTEM_SPC_VERSION_ADDR
                        _upgrade_release_dir = lc_out_path / "release_note.json"
                        try:
                            spc_registers = query_register_data(FIXED_DEVICE_ID, READ_INPUT_REGISTER, _spc_addr, 1)
                            now_spc_version = int(spc_registers[0]) & 0xFFFF
                            note_data = load_release_note(_upgrade_release_dir)
                            if not note_data:
                                _write_status(job_id, STATE_ERROR, 0, "not found release note")
                                return
                                # return jsonify("not found release note"), 500
                            basic = note_data.get("basicInfo", {})
                            if not basic:
                                _write_status(job_id, STATE_ERROR, 0, "invalid release note")
                                return
                                # return jsonify("invalid release note"), 500
                            _releaseVersion = basic.get('version', 0)
                            global releaseVersion
                            releaseVersion = get_spc_num(_releaseVersion)
                            DPrint(f"release note: {_releaseVersion}, SPC: {releaseVersion}")
                        except Exception as e:
                            DPrint(f"地址 {_spc_addr} 读取异常: {e}")
                            # return jsonify({'error': str(e)}), 500
                            _write_status(job_id, STATE_ERROR, 0, f"地址 {_spc_addr} 读取异常: {e}")

                        run_upgrade_async(job_id, str(now_spc_version), delay_sec=2)
                    else:
                        DPrint(f"[UPLOAD]({job_id}) 未找到有效的 LC 升级包内容")
                        _write_status(job_id, STATE_ERROR, 0, "未找到有效的 LC 升级包内容")

                # ===== 两种包都没有找到 =====
                else:
                    DPrint(f"[UPLOAD]({job_id}) 暂不支持该设备升级")
                    _write_status(job_id, STATE_ERROR, 0, "暂不支持该设备升级")

            except Exception as e:
                DPrint(f"[UPLOAD]({job_id}) 后台处理异常: {e}")
                _write_status(job_id, STATE_ERROR, 0, f"error:{e}")

            finally:
                try:
                    if target == "lc":
                        shutil.rmtree(work_dir)
                        DPrint(f"[CLEAN]({job_id}) 已清理LC升级临时目录: {work_dir}")
                except Exception as e:
                    DPrint(f"[CLEAN]({job_id}) 清理LC升级临时目录失败: {e}")

        if _startup == 1:
            DPrint(f"[UPLOAD]({job_id}) 启动升级任务")
            threading.Thread(target=_bg_process, daemon=True).start()
        else:
            DPrint(f"[UPLOAD]({job_id}) 升级包已上传,等待前端调用升级接口")
            _write_status(job_id, STATE_DONE, 0, "upgrade package uploaded, waiting for start command")
        max_wait_sec = 2
        start_time = time.time()
        while releaseVersion == 0:
            # 超时退出
            if time.time() - start_time >= max_wait_sec:
                break
            time.sleep(0.1)  # 每100ms查一次，不疯狂空转
        resp = jsonify({
            'taskName': job_id,
            'release_version': releaseVersion,
            'status': 0
        })
        return resp, 200

    except Exception as e:
        shutil.rmtree(work_dir, ignore_errors=True)
        _write_status(job_id, STATE_ERROR, 0, str(e))
        DPrint(f"[UPLOAD]({job_id}) 升级包异常: {str(e)}, 已删除：{outer_zip_path}")
        return jsonify({
            'taskName': job_id,
            'status': STATE_ERROR,
            'error': str(e)
        }), 400
    finally:
        f = read_status(job_id)
        if (f is None) or (f.get('state', STATE_ERROR) == STATE_ERROR):
            _result = operationLog.OperationResult.FAIL
        else:
            _result = operationLog.OperationResult.SUCCESS
        OperationType = operationLog.OperationType.UPGRADE
        for sort_idx in sort:
            operationLog.enqueue_operation_log(
                        operatorName,
                        OperationType,
                        operationTarget,
                        int(sort_idx),
                        _result,
                        remark
                    )

# 升级后版本校验,针对LC,PCS自行校验
@g3_bp.route('/api/upgrade/calibration', methods=['GET'])
def upgrade_calibration():
    try:
        releaseVersion = (request.args.get('releaseVersion') or '').strip()
        if not releaseVersion:
            return jsonify({'error': 'releaseVersion is required'}), 400
        release_version = int(releaseVersion)
        _spc_addr = common.SYSTEM_SPC_VERSION_ADDR
        try:
            spc_registers = query_register_data(FIXED_DEVICE_ID, READ_INPUT_REGISTER, _spc_addr, 1)
            spc_version = int(spc_registers[0]) & 0xFFFF
            if spc_version != release_version:
                _calibration = False
            else:
                _calibration = True
            return jsonify({'now_spc': spc_version,
                            'result': _calibration
                            }), 200
        except Exception as e:
            DPrint(f"地址 {_spc_addr} 读取异常: {e}")
            return jsonify({'error': str(e)}), 500

    except Exception as e:
        DPrint(f"[CALIBRATION] 校验结果获取异常: {e}")
        return jsonify({'error': str(e)}), 500

# 用于前端调用查询历史版本,返回文件夹名,为时间戳
@g3_bp.route('/api/upgrade/getRollbackVersion', methods=['GET'])
def upgrade_getRollbackVersion():
    try:
        _spc_addr = common.SYSTEM_SPC_VERSION_ADDR
        try:
            spc_registers = query_register_data(FIXED_DEVICE_ID, READ_INPUT_REGISTER, _spc_addr, 1)
            spc_version = int(spc_registers[0]) & 0xFFFF
            history_spc_dict = get_folder_dict(config.HISTORY_ROLL_PATH)
            return jsonify({'now_spc': spc_version,
                            'history_spc_dict': history_spc_dict
                            }), 200
        except Exception as e:
            DPrint(f"地址 {_spc_addr} 读取异常: {e}")
            return jsonify({'error': str(e)}), 500

    except Exception as e:
        DPrint(f"getRollbackVersion route error: {e}")
        return jsonify({'error': str(e)}), 500

# 用于前端调用回滚LC升级前版本,不支持PCS
@g3_bp.route('/api/upgrade/startRollback', methods=['POST'])
def upgrade_startRollback():
    try:
        # 回滚暂时只支持LC,不支持PCS
        operationTarget = "lc"
        _result = operationLog.OperationResult.FAIL
        remark = ""
        _rollback = False
        operatorName = (request.form.get('operatorName') or '').strip()
        job_name = (request.form.get('taskName') or '').strip()
        objectSPCVersion = (request.form.get('objectSPCVersion') or '').strip()
        if not operatorName:
            remark = f"'taskName': 'N/A', 'status': {STATE_ERROR}, 'error': 'operatorName is required'"
            return jsonify({'error': 'operatorName is required'}), 400
        if not job_name:
            remark = f"'taskName': 'N/A', 'status': {STATE_ERROR}, 'error': 'taskName is required'"
            return jsonify({'taskName': 'N/A', 'status': STATE_ERROR, 'error': 'taskName is required'}), 400
        if not objectSPCVersion:
            remark = f"'taskName': 'N/A', 'status': {STATE_ERROR}, 'error': 'objectSPCVersion is required'"
            return jsonify({'error': 'objectSPCVersion is required'}), 400
        try:
            spcversion = objectSPCVersion.split("_")[-1]
            objSPCVersion=int(spcversion)
        except ValueError:
            remark=f"invalid objectSPCVersion format: {objectSPCVersion}"
            return jsonify({
                "error": remark
            }),400
        _spc_addr = common.SYSTEM_SPC_VERSION_ADDR
        try:
            spc_registers = query_register_data(FIXED_DEVICE_ID, READ_INPUT_REGISTER, _spc_addr, 1)
            now_spc_version = int(spc_registers[0]) & 0xFFFF
            if now_spc_version == objSPCVersion:
                remark = f'current SPC version is already object version: {objSPCVersion}'
                return jsonify({
                    'error': f'current SPC version is already object version: {objSPCVersion}'
                }), 400
            history_spc_dict = get_folder_dict(config.HISTORY_ROLL_PATH)
            DPrint(f"history_spc_dict:{history_spc_dict}")
            if objectSPCVersion in history_spc_dict:
                if secure_filename(job_name) != job_name:
                    return _upgrade_error('taskName contains unsupported characters')
                _write_status(job_name, STATE_IN_PROGRESS, 0, 'rollback starting')
                start_rollback(job_name, objectSPCVersion)
            else:
                remark = f'local has no object version backup: {objSPCVersion}'
                return jsonify({
                    'error': f'local has no object version backup: {objSPCVersion}'
                }), 400
            remark = f'local has started rollback to SPC Version: {objSPCVersion}'
            _rollback = True
            return jsonify({'now_spc': now_spc_version,
                            'obj_spc': objSPCVersion,
                            'start_roll': _rollback
                            }), 200
        except Exception as e:
            DPrint(f"地址 {_spc_addr} 读取异常: {e}")
            return jsonify({'error': str(e)}), 500

    except Exception as e:
        DPrint(f"[CALIBRATION] 校验结果获取异常: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if _rollback:
            _result = operationLog.OperationResult.SUCCESS
        else:
            _result = operationLog.OperationResult.FAIL
        OperationType = operationLog.OperationType.ROLLBACK
        operationLog.enqueue_operation_log(
            operatorName,
            OperationType,
            operationTarget,
            1,
            _result,
            remark
        )

# 系统一致性检查
@g3_bp.route('/api/system/consistencyCheck',methods=['GET'])
def SystemConsistencyCheck():
    """
    系统一致性检查
    当前检查指定寄存器是否存在异常,若存在,告警位写true
    """
    try:
        pcsVersionCheck = True
        pcsSafetyCheck = True
        pcsModeCheck = True
        check_list = [
            pcsVersionCheck,
            pcsSafetyCheck,
            pcsModeCheck
        ]
        check_names = []
        check_idx = 0

        for index, addr in enumerate(SYSTEM_CONSISTENCY_CHECK_LIST):
            registers = query_register_data(deviceid=FIXED_DEVICE_ID,
                                            functioncode=READ_INPUT_REGISTER,
                                            address=addr,
                                            quantity=1
                                            )
            # TEST
            if common.TEST_MODE is True:
                registers[0] = addr
            register_value = int(registers[0]) & 0xFFFF
            # 整体检查
            if register_value != 0:
                check_list[index] = False
            # 细节点位检查
            # bit_mapping = SYSTEM_CONSISTENCY_CHECK_LIST.get(addr, {})
            # for bit_index, check_info in bit_mapping.items():
            #     checkName = check_info if check_info else "未知告警/故障"
            #     if (register_value >> bit_index) & 1:
            #         check_list[check_idx] = False
            #         check_names[check_idx] = checkName
            #         check_idx += 1

        return jsonify({
            "pcsVersionCheck": check_list[0],
            "pcsSafetyCheck": check_list[1],
            "pcsModeCheck": check_list[2],
        }), 200

    except Exception as e:
        DPrint(f"[{now_str()}] [/api/system/consistencyCheck] 服务器异常: {e}")
        return jsonify({
            "error": f"服务器异常: {e}"
        }), 500

# 参数下发模块
@g3_bp.route('/api/paraConfig/getParams',methods=['GET'])
def getConfigParams():
    """
    查询参数点表接口。

    示例:
      GET /api/paraConfig/getParams?dataType=runParaSetting-pcsSetting
      GET /api/paraConfig/getParams?dataType=runParaSetting-ParaCalibration

    返回:
    {
        "paramsList": [
      {
        "moduleName": "PowerControl",
        "params": {
          "buttom": [
           {        // 遥控按钮参数数组
            "address": 1001,
            "name": "PCS故障清除",
            "sort": "2",
            "eValue": "1", //生效值
            "rule": [1002,...]
            },
            ...
          ],
           ...
          "text": [
            {
              "address": 1004,
              "name": "PCS 有功功率参考",
              "sort": "1",
              "maxValue": "7200",
              "minValue": "-7200",
              "unit": "kW"
            },
            ...
          ]
        }
        ...
      }
    ]
    }
    """
    try:
        data_type = str(request.args.get("dataType", "")).strip()

        if not data_type:
            return jsonify({
                "paramsList": [],
                "error": "Missing dataType",
            }), 400
        DPrint(f"调用[/api/paraConfig/getParams]接口,data_type--{data_type}")

        params_list = CONFIG_PARAMS_BY_DATA_TYPE.get(data_type)

        if params_list is None:
            return jsonify({
                "paramsList": [],
                "error": f"Unsupported dataType: {data_type}",
            }), 400

        return jsonify({
            "paramsList": [_public_config_param(param) for param in params_list],
        }), 200

    except Exception as e:
        DPrint(f"[{now_str()}] [/api/paraConfig/getParams] 服务器异常: {e}")
        return jsonify({
            "paramsList": [],
            "error": f"服务器异常: {e}",
        }), 500

@g3_bp.route('/api/paraConfig/getData', methods=['GET'])
def getConfigDatafromParams():
    """
    查询实时参数值接口。

    示例:
      GET /api/paraConfig/getParams?dataType=runParaSetting-pcsSetting&deviceid=3
      GET /api/paraConfig/getParams?dataType=runParaSetting-ParaCalibration&deviceid=3
    返回:
    {
      "dataList": [第1个参数的数值, 第2个参数的数值, ...]
    }

    说明:
    - dataList 顺序与 getParams 的 paramsList 顺序一致。
    - 设备地址固定为 1。
    - 字节序按大端模式处理。
    - 实际值 = 原始寄存器值 * precision。
    """
    try:
        DPrint("调用/api/paraConfig/getData接口")
        data_type = str(request.args.get("dataType", "")).strip()
        deviceid = int(request.args.get("deviceid", 0))
        DPrint("dataType:", data_type)
        if not data_type:
            return jsonify({"dataList": [], "error": "Missing dataType",}), 400
        if not deviceid:
            return jsonify({"dataList": [], "error": "Missing deviceid",}), 400
        # params_list = _build_params_list_for_data_type(data_type)
        params_list = CONFIG_PARAMS_BY_DATA_TYPE.get(data_type)
        if params_list is None: 
            return jsonify({"dataList": [], "error": f"Unsupported dataType: {data_type}", }), 400
        # ----------------------------------
        # 查设备信息
        # ----------------------------------
        ini_data = read_ini_all()
        pcs_num = _ini_get_int(ini_data, "SYSTEM", "pcsNum", 0)
        device_info = None
        device_info = find_device(deviceid)
        device_type = device_info.get("deviceType")
        sort = device_info.get("sort")
        device_name = device_info.get("name")
        DPrint(f"device_type:{device_type},device_name:{device_name}")
        if data_type in ["runParaSetting-pcsSetting", "runParaSetting-ParaCalibration"]:
            DPrint(device_info)
            if not device_info:
                return jsonify({"code": 1, "msg": f"设备不存在: id={deviceid}"})
            if device_name not in ["G3_PCS"]:
                return jsonify(
                    {"code": 1, "msg": f"不支持获取该设备参数: device_name={device_name} {sort}"})
            elif (sort > pcs_num) or (sort < 1):
                return jsonify(
                    {"code": 1, "msg": f"不支持获取该设备参数: device_name={device_name} {sort}"})
        DPrint(f"正在获取该设备参数: device_name={device_name} {sort}")
        data_list = []
        is_reac_mode = False
        # 读取寄存器值
        if data_type in ["runParaSetting-pcsSetting", "runParaSetting-ParaCalibration"]:
            for params in params_list:
                for buttom in params.get("params").get("buttom",""):
                    buttom_t = buttom.copy()
                    if buttom_t["address"] == PCS_REACTIVE_POWER_MODE_ADDR:
                        is_reac_mode = True
                    buttom_t["address"] += PCS_CONFIG_PARAM_GAP * (sort - 1)
                    actual_value = _read_param_value(buttom_t, functioncode = READ_HOLD_REGISTER)
                    # 分离按钮和文本值
                    if is_reac_mode:
                        actual_value &= 1
                        is_reac_mode = False
                    data_list.append(actual_value)
                for text in params.get("params").get("text",""):
                    text_t = text.copy()
                    if text_t["address"] == PCS_REACTIVE_POWER_MODE_ADDR:
                        is_reac_mode = True
                    text_t["address"] += PCS_CONFIG_PARAM_GAP * (sort - 1)
                    actual_value = _read_param_value(text_t, functioncode = READ_HOLD_REGISTER)
                    # 分离按钮和文本值
                    if is_reac_mode and (actual_value & 1) == 1:
                        actual_value -= 1
                        is_reac_mode = False
                    data_list.append(actual_value)
        elif data_type in ["systemctl-power"]:
            for params in params_list:
                for text in params.get("params").get("text",""):
                    text_t = text.copy()
                    actual_value = _read_param_value(text_t, functioncode = READ_HOLD_REGISTER)
                    data_list.append(actual_value)
        # 读取ini文件
        else:
            for params in params_list:
                for text in params.get("params").get("text",""):
                    text_t = text.copy()
                    actual_value = _read_ini_value(text_t)
                    data_list.append(actual_value)
        DPrint(data_list)
        return jsonify({
            "dataList": data_list,
        }), 200

    except ValueError as e:
        DPrint(f"[{now_str()}] [/api/paraConfig/getData] 参数配置错误: {e}")
        return jsonify({
            "dataList": [],
            "error": f"参数配置错误: {e}",
        }), 400

    except Exception as e:
        DPrint(f"[{now_str()}] [/api/paraConfig/getData] 服务器异常: {e}")
        traceback.print_exc()
        return jsonify({
            "dataList": [],
            "error": f"服务器异常: {e}",
        }), 500

@g3_bp.route('/api/paraConfig/modifyParams', methods=['POST'])
def modifyConfigDatafromParams():
    """
    下发实时参数值接口。

    示例:
      POST /api/paraConfig/modifyParams
      POST /api/paraConfig/modifyParams
        {
            "operatorName":string,
            "deviceid":int,
            "address":int,
            "value":string
        }
        对于mv的配置参数,也需要deviceid,任意值
    返回:
        {
            "success": true,
            "msg": "Successfully sent"
        }
    """
    operatorName = ""
    operationTarget = ""
    sort = 1
    _result = operationLog.OperationResult.FAIL
    remark = ""
    try:
        # 兼容 form 表单 / json 两种传参方式
        if request.is_json:
            req_data = request.get_json()
            operatorName = g.current_user["username"]
            deviceid_raw = req_data.get("deviceid", "")
            address_raw = req_data.get("address", "")
            value_raw = req_data.get("value", "")
        else:
            operatorName = g.current_user["username"]
            deviceid_raw = request.form.get('deviceid', '')
            address_raw = request.form.get('address', '')
            value_raw = request.form.get('value', '')

        # 去除首尾空格
        operatorName = str(operatorName).strip()
        deviceid_str = str(deviceid_raw).strip()
        address_str = str(address_raw).strip()
        value = str(value_raw).strip()

        # 1. 非空校验
        if not operatorName:
            return jsonify({"success": False, "msg": "参数operatorName不能为空"}), 400
        if not deviceid_str:
            return jsonify({"success": False, "msg": "参数deviceid不能为空"}), 400
        if not address_str:
            return jsonify({"success": False, "msg": "参数address不能为空"}), 400
        if value == "":
            return jsonify({"success": False, "msg": "参数value不能为空"}), 400

        # 2. 强制转换为整型
        try:
            deviceid = int(deviceid_str)
        except ValueError:
            return jsonify({"success": False, "msg": "deviceid必须为整数"}), 400
        try:
            address = int(address_str)
        except ValueError:
            return jsonify({"success": False, "msg": "address寄存器地址必须为整数"}), 400

        # 3. 权限校验
        permission_level = _getlevel_permission_table(operatorName)
        if permission_level is None:
            return jsonify({"success": False, "msg": "invalid user"}), 400
        if permission_level not in PERMISSION_TABLE.get("param"):
            return jsonify({"success": False, "msg": "No permission to modify param"}), 400

        # 4. 业务逻辑：解析modbus值,下发参数
        # ----------------------------------
        # 查设备信息
        # ----------------------------------
        ini_data = read_ini_all()
        pcs_num = _ini_get_int(ini_data, "SYSTEM", "pcsNum", 0)
        device_info = None
        device_info = find_device(deviceid)
        if not device_info:
            _result = operationLog.OperationResult.FAIL
            remark = f"Device not found: id={deviceid}"
            return jsonify({"code": 1, "msg": f"设备不存在: id={deviceid}"}), 400
        device_type = device_info.get("deviceType")
        sort = device_info.get("sort")
        device_name = device_info.get("name")
        g.audit_target = f"{device_name} {sort} / register:{address}"
        # 系统参数下发,不记录设备名,暂记录为system
        if address > 1505:
            operationTarget = device_name
            DPrint(f"device_type:{device_type},device_name:{device_name}")
            DPrint(device_info)
        else:
            operationTarget = "system"
            DPrint(f"Put down: System param: address{address}")
        DPrint(f"device_type:{device_type},device_name:{device_name}")
        DPrint(device_info)
        if sort < 1:
            _result = operationLog.OperationResult.FAIL
            remark = f"Device not found: id={deviceid} {sort}"
            return jsonify({"code": 1, "msg": f"设备不存在: id={deviceid} {sort}"})
        # 提取寄存器信息
        modbus_value = int(value)
        DPrint(f"准备下发参数: device_name={device_name} {sort}, address={address}, value={modbus_value}")
        target_item = get_addr_config(address)
        regName = target_item.get("name", "unknown")
        min_phy = target_item.get("min", None)
        max_phy = target_item.get("max", None)
        if not (min_phy <= modbus_value <= max_phy):
            raise ValueError(f"输入值超出配置范围，区间[{min_phy}, {max_phy}]，输入：{modbus_value}")
        # modbus点表映射地址
        if address < 65536:
            if sort > pcs_num:
                _result = operationLog.OperationResult.FAIL
                remark = f"no device: device_name={device_name} {sort}"
                return jsonify(
                    {"code": 1, "msg": f"设备不存在: device_name={device_name} {sort}"})
            DPrint(f"正在下发该设备参数: device_name={device_name} {sort}")
            # modbus_value = _trans_to_modbus_value(address, actual_value)
            # # 特殊寄存器,无功模式
            # if (address == PCS_REACTIVE_POWER_MODE_ADDR) and (modbus_value != 1):
            #     registers = query_register_data(
            #         deviceid=FIXED_DEVICE_ID,
            #         functioncode = READ_HOLD_REGISTER,
            #         address=PCS_REACTIVE_POWER_MODE_ADDR,
            #         quantity=1,
            #     )
            #     if (registers & 1) == 1:
            #         modbus_value += 1
            modbus_address = address + (sort - 1) * PCS_CONFIG_PARAM_GAP
            old_value = query_register_data(
            deviceid=FIXED_DEVICE_ID,
            functioncode = READ_HOLD_REGISTER,
            address=modbus_address,
            quantity=1)
            ret, try_count = write_register_with_retry(modbus_address, modbus_value)
            DPrint(f"下发参数 device={deviceid}, addr={modbus_address}, val={modbus_value}")
            if ret.isError() == True:
                _result = operationLog.OperationResult.FAIL
                remark = f"{regName}: Modbus push down failed, try {try_count} failed"
                return jsonify({
                "success": False,
                "msg": f"Modbus push down failed, try {try_count} failed"
                })
            remark = f"{regName}: {old_value[0]} -> {modbus_value}"
            # time.sleep(0.5)
            # readback = query_register_data(
            # deviceid=FIXED_DEVICE_ID,
            # functioncode = READ_HOLD_REGISTER,
            # address=modbus_address,
            # quantity=1)
            # if readback[0] != modbus_value:
            #     DPrint(f"the readback value:{readback}, the push value:{modbus_value}")
            #     return jsonify({
            #     "success": False,
            #     "msg": f"Modbus push down failed, the readback value:{readback} not equal"
            #     })
            DPrint({"success": True,"msg": "Successfully sent"})
        # 配置文件映射地址
        else:
            _result = operationLog.OperationResult.FAIL
            remark = f"{regName}: invalid Modbus address {modbus_address}"
            return jsonify({
            "success": False,
            "msg": f"invalid Modbus address {modbus_address}"
            })
            # old_value = _read_ini_value(target_item)
            # _write_ini_value(target_item, modbus_value)
            # remark = f"{regName}: {old_value} -> {modbus_value}"
            # time.sleep(0.1)
            # readback = _read_ini_value(target_item)
            # if readback != value:
            #     DPrint(f"the readback value:{readback}, the push value:{modbus_value}")
            #     return jsonify({
            #     "success": False,
            #     "msg": f"Modbus push down failed, the readback value:{readback} not equal"
            #     })
            # DPrint({"success": True,"msg": "Successfully sent"})
        # 成功返回
        _result = operationLog.OperationResult.SUCCESS
        return jsonify({"success": True,"msg": "Successfully sent"})

    except Exception as e:
        err_msg = f"下发参数异常：{str(e)}"
        DPrint(err_msg)
        _result = operationLog.OperationResult.FAIL
        remark = f"{regName}: Send parameters error: {str(e)}"
        return jsonify({"success": False,"msg": err_msg}), 500
    finally:
        if address > 1505:
            OperationType = operationLog.OperationType.PARAM
        else:
            OperationType = operationLog.OperationType.CONTROL
        operationLog.enqueue_operation_log(
            operatorName,
            OperationType,
            operationTarget,
            int(sort),
            _result,
            remark
        )
