#!/usr/bin/env python3
import json, threading, shutil
from flask import request, jsonify
from werkzeug.utils import secure_filename
import traceback
import zipfile, time
from datetime import datetime
from config import DEFINE_16BIT, READ_HOLD_REGISTER, FIXED_DEVICE_ID, READ_INPUT_REGISTER, UPGRADE_STATE_MAP, PCS_REMOTE_DEST, PCS_REMOTE_DEST_TEST, REMOTE_PASSWORD_TEST,UPLOAD_DIR, SQL_TABLE_NAME, REMOTE_IPS, REMOTE_PORTS, REMOTE_USERNAME, REMOTE_PASSWORD, REMOTE_DB_FILE, LOCAL_SAVE_PATH
from constent.param_config import CONFIG_PARAMS_BY_DATA_TYPE, PCS_REACTIVE_POWER_MODE_ADDR, PCS_CONFIG_PARAM_GAP
from config import HOST_IP, STATUS_DIR, STATE_ERROR, STATE_IDLE, STATE_IN_PROGRESS, STATE_DONE, PERMISSION_MAPPING_TABLE, PERMISSION_TABLE
from utils.utils import DPrint, now_str
from utils.ini import find_device, read_ini_all, _ini_get_int, _get_pcs_device_type_by_brand, _ini_get_str
from utils.method import get_spc_num, load_release_note, read_status, get_folder_dict, _getlevel_permission_table, write_register_with_retry, get_addr_config, _write_ini_value, _trans_to_modbus_value, _read_ini_value, _public_config_param, query_register_data, safe_extract, extract_inner_zip_by_prefix, parse_pcs_ip_mapping_from_ini, verify_upgrade_package, _write_status, upload_ini_file_async, parse_targets, _getFaultCodeList, _getFaultDataList, query_device_sqlitedata, _apply_precision, fill_simudata2mysql, query_device_mysqldata, query_fault_list, makeFaultListFromMysqlHistoryReg, CheckFaultFromRows, query_fault_poschange, query_device_alarm_data, _public_param, _read_param_value, _build_params_list_for_data_type
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
import constent.fault_all as fault_all
import constent.common as common
import config
from flask import Blueprint, Response
import utils.operationLog as operationLog

g3_bp = Blueprint("g3", __name__)
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
        for i in range(1, pcs_num + 1):
            brand = _ini_get_int(
                ini_data,
                "PCS_NETWORK",
                f"pcs{i}_brand",
                PCS_BRAND["G3_SELF"]
            )
            DPrint(brand)

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

        operatorName = body["operatorName"]
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
        begin_dt = str(request.args.get("beginDt", "")).strip()
        end_dt = str(request.args.get("endDt", "")).strip()
        page_num = int(request.args.get("pageNum", 1))
        page_size = int(request.args.get("pageSize", 10))

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
        return jsonify({"error": f"服务器异常: {e}"}), 500

# 操作日志查询
@g3_bp.route('/api/history/getOperationlog', methods=['GET'])
def GetOperationlog():
    """
    查询操作日志接口。

    请求示例:
      GET /api/history/getOperationlog?beginDt=2026-05-08T00:00:00&endDt=2026-05-08T09:01:21&pageNum=1&pageSize=10

    参数:
    beginDt: 2026-05-08T00:00:00
    endDt: 2026-05-08T09:01:21
    pageNum: 1
    pageSize: 10
    """
    try:
        begin_dt = str(request.args.get("beginDt", "")).strip()
        end_dt = str(request.args.get("endDt", "")).strip()
        page_num = int(request.args.get("pageNum", 1))
        page_size = int(request.args.get("pageSize", 10))
        operator = str(request.args.get("operator", "")).strip() or None
        _type = str(request.args.get("operationType", "")).strip() or None
        _target = str(request.args.get("operationTarget", "")).strip() or None
        result_arg = str(request.args.get("result", "")).strip()

        if not begin_dt or not end_dt:
            return jsonify({"error": "Missing beginDt or endDt"}), 400

        if page_num <= 0 or page_size <= 0:
            return jsonify({"error": "Missing page_num or page_size"}), 400

        begin_dt = begin_dt.replace('T', ' ')
        end_dt = end_dt.replace('T', ' ')
        begin_dt = datetime.strptime(begin_dt, "%Y-%m-%d %H:%M:%S")
        end_dt = datetime.strptime(end_dt, "%Y-%m-%d %H:%M:%S")
        operation_target = None
        sort = None
        operation_type = None
        result = int(result_arg) if result_arg != "" else None
        if _type is not None:
            try:
                op_type = int(_type)
            except ValueError:
                return jsonify({"success": False, "msg": "operationType必须是整数"}), 400
            operation_type = operationLog.OP_NUM_MAP.get(op_type)
            if operation_type is None:
                return jsonify({"success": False, "msg": "operationType非法枚举"}), 400
        if result is not None and result not in (0, 1):
            return jsonify({"error": "result must be 0 or 1"}), 400
        if _target is not None:
            try:
                deviceid = int(_target)
                ini_data = read_ini_all()
                pcs_num = _ini_get_int(ini_data, "SYSTEM", "pcsNum", 0)
                device_info = None
                device_info = find_device(deviceid)
                if not device_info:
                    return jsonify({"code": 1, "msg": f"查询设备不存在: {deviceid}"}), 400
                device_type = device_info.get("deviceType")
                sort = device_info.get("sort")
                device_name = device_info.get("name")
                operation_target = device_name
                DPrint(f"query: device_type:{device_type},device_name:{device_name}")
                if operation_target not in ["G3_PCS","MV"]:
                    return jsonify({"code": 1, "msg": f"不支持查询该设备: {device_name} {sort}"}), 400
                if (sort < 1) or (sort > pcs_num):
                    return jsonify({"code": 1, "msg": f"查询设备不存在: {device_name} {sort}"}), 400
            except ValueError:
                return jsonify({"success": False, "msg": "operation_target必须为整数"}), 400
        offset = (page_num - 1) * page_size
        total, results = operationLog.query_operation_log(
            begin_dt=begin_dt,
            end_dt=end_dt,
            offset=offset,
            page_size=page_size,
            operator=operator,
            operation_type=operation_type,
            operation_target=operation_target,
            sort=sort,
            result=result,
        )

        return jsonify({
            "total": total,
            "pageNum": page_num,
            "pageSize": page_size,
            "operationLogList": results
        }), 200
    except ValueError as e:
        return jsonify({"ok": False, "error": f"参数格式错误: {e}"}), 400
    except Exception as e:
        DPrint(f"[{now_str()}] [/api/history/getOperationlog] 服务器异常: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500

# 设备数据查询
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
        device_id = int(request.args.get("id"))
        begin_dt = request.args.get("beginDt", "")
        end_dt = request.args.get("endDt", "")
        page_num = int(request.args.get("pageNum", 1))
        page_size = int(request.args.get("pageSize", 10))

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
            return jsonify({
                "code": 1,
                "msg": f"设备不存在: id={device_id}"
            })

        device_type = device_info.get("deviceType")
        sort = device_info.get("sort")
        DPrint(f"device_type:{device_type}")
        # ----------------------------------
        # 3. 提取日期构造表名
        # ----------------------------------
        date_str = begin_dt.split('T')[0].replace('-', '')
        table_prefix = TABLE_PREFIX_MAP.get(device_type)
        if not table_prefix:
            return jsonify({
                "code": 1,
                "msg": f"未知设备或不支持设备类型: {device_type}"
            })
        if device_type == DEVICE_TYPE.get("G3_PCS"):
            device_num = pcs_num
        if device_type == DEVICE_TYPE.get("MV"):
            device_num = mv_num
        if device_type == DEVICE_TYPE.get("BMS_BANK"):
            device_num = bms_num
        if (sort > device_num) or (sort < 1):
            return jsonify({
                "code": 1,
                "msg": f"当前无该设备信息: {table_prefix} {sort}"
            })
        table_name = f"{table_prefix}{date_str}"
        # ----------------------------------
        # 4. 查表MySQL
        # ----------------------------------
        rows = query_device_mysqldata(table_name, begin_dt, end_dt, offset, page_size, sort - 1)
        # DPrint(f"rows:{rows}")
        if not rows and (common.TEST_MODE is False):
            return jsonify({
                "code": 1,
                "msg": f"查询日期无该设备信息: {begin_dt} ~ {end_dt} {table_prefix} {sort}"
            })
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
        return jsonify({
            "code": 1,
            "msg": str(e)
        })

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
        pcsid = int(request.args.get("pcsId"))
        begin_dt = request.args.get("beginDt", "")
        end_dt = request.args.get("endDt", "")

        if not pcsid:
            return jsonify({"error": "Missing pcsid"}), 400

        if not begin_dt or not end_dt:
            return jsonify({"error": "Missing beginDt or endDt"}), 400

        begin_dt = begin_dt.replace("T"," ")
        end_dt = end_dt.replace("T"," ")
        device_info = None
        device_info = find_device(pcsid)
        # ----------------------------------
        # 2. 查设备信息
        # ----------------------------------
        if not device_info:
            return jsonify({
                "code": 1,
                "msg": f"设备不存在: pcsid={pcsid}"
            })
        pcs_sort = int(device_info.get("sort"))
        # 执行下载
        if pcs_sort < 1:
            return jsonify({
                "code": 1,
                "msg": f"设备不存在: pcsid={pcsid}"
            })
        if not check_network(REMOTE_IPS[pcs_sort - 1], REMOTE_PORTS[pcs_sort - 1]):
            return jsonify({
                "code": 1,
                "msg": f"连接设备网络异常: pcsid={pcsid}"
            })
        DPrint(f"scp:{REMOTE_IPS[pcs_sort - 1]}")
        # scp拉取远端PCS录波到本地,覆盖旧文件
        scp_download(
            remote_ip=REMOTE_IPS[pcs_sort - 1], # PCS ip
            user=REMOTE_USERNAME,               # user name
            password = REMOTE_PASSWORD,         # user password
            remote_path=REMOTE_DB_FILE,         # PCS db file path
            local_path=LOCAL_SAVE_PATH,         # local db file path
            port = REMOTE_PORTS[pcs_sort - 1]   # PCS port
        )
        rows = query_device_sqlitedata(LOCAL_SAVE_PATH, SQL_TABLE_NAME, begin_dt, end_dt)
        recordList = []
        for row in rows:
            record = f"{row['faultCodeOccurDate']}_{row['id']}"
            recordList.append(record)
        if not recordList:
            return jsonify({
                "code": 1,
                "msg": f"未找到符合条件的录波: pcsid={pcsid}"
            })
        return jsonify({
         "recordList": recordList
        }), 200

    except Exception as e:
        DPrint(f"[/api/faultRecord/getRecordList] 服务器异常: {e}")
        return jsonify({
            "code": 1,
            "msg": str(e)
        })

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
        recordId = int(request.args.get("recordId"))
        if not recordId:
            return jsonify({"error": "Missing recordId"}), 400

        rows = query_device_sqlitedata(LOCAL_SAVE_PATH, SQL_TABLE_NAME, record_id=recordId)
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
        return jsonify({
            "code": 1,
            "msg": str(e)
        })

# 程序升级
@g3_bp.route('/api/upgrade/file', methods=['POST'])
def upgrade_file():

    try:
        # —— 打印收到的表单键 ——
        f = request.files.get('firmwareFile')
        operatorName = (request.form.get('operatorName') or '').strip()
        job_name = (request.form.get('taskName') or '').strip()
        # releaseVersion = (request.form.get('releaseVersion') or '').strip()
        raw_target = (request.form.get('firmwareCategory') or '').strip()
        operationTarget = ""
        sort = []
        _result = operationLog.OperationResult.FAIL
        remark = ""
        job_id = ""
        global releaseVersion
        releaseVersion = 0
        # getlist 直接拿到列表字符串
        id_str_list = request.form.getlist("deviceId")
        if not job_name:
            remark = f"'taskName': 'N/A', 'status': {STATE_ERROR}, 'error': 'taskName is required'"
            return jsonify({'taskName': 'N/A', 'status': STATE_ERROR, 'error': 'taskName is required'}), 400
        if not id_str_list:
            remark = f"'taskName': {job_name}, 'status': {STATE_ERROR}, 'error': 'deviceId is required'"
            return jsonify({'taskName': job_name, 'status': STATE_ERROR, 'error': 'deviceId is required'}), 400
        # 转int列表
        deviceId = [int(x) for x in id_str_list]
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

        safe_name = secure_filename(f.filename) or 'upload.zip'
        if not safe_name.lower().endswith('.zip'):
            remark = '必须上传 .zip 压缩包'
            return jsonify({'taskName': job_id, 'status': STATE_ERROR, 'error': '必须上传 .zip 压缩包'}), 400

        #=============
        # 校验升级包
        #=============
        work_dir = UPLOAD_DIR / f"_incoming_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{job_id}"
        work_dir.mkdir(parents=True, exist_ok=True)
        outer_zip_path = work_dir / safe_name
        f.save(outer_zip_path)

        try:
            global SECRET_KEY
            key = _ini_get_str(ini_data, "SYSTEM", "key", "")
            crc_mode = _ini_get_str(ini_data, "SYSTEM", "crcMode", "SHA256").upper()
            SECRET_KEY = key.strip().encode()
            verify_upgrade_package(outer_zip_path, crc_mode)
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
                    # 支持 PCS.zip / PCS2026.zip ...
                    DPrint(f"[UPLOAD]({job_id}) 处理PCS升级包")
                    pcs_inner = extract_inner_zip_by_prefix(outer_zip_path, 'pcs', work_dir)
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
                            # TEST
                            # ret0 = STATE_DONE
                            if ret0 != STATE_IDLE:
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
                        # 3.分发升级包
                        global pending_count
                        pending_count = len(deviceId)
                        deviceNum = len(deviceId)
                        if len(fault_host) == 0:
                            for idx, pcs in enumerate(pcs_ip_mapping_list, start=1):
                                host = pcs_ip_mapping_list.get(pcs)
                                if idx not in deviceId:
                                    continue
                                scp_send_async(pcs_inner,REMOTE_USERNAME,host,PCS_REMOTE_DEST)
                                _write_status(job_id, STATE_IN_PROGRESS, 0, f"push pcs upgrade package {idx}/{deviceNum}")
                        else:
                            DPrint(f"[UPLOAD]({job_id}) 由于清理远程升级目录失败或PCS升级状态异常, hosts: {fault_host},中止所有PCS升级")
                    else:
                        DPrint(f"[UPLOAD]({job_id}) 未找到有效的 PCS 升级包内容")
                        _write_status(job_id, STATE_ERROR, 0, "未找到有效的 PCS 升级包内容")

                # 支持 LC.zip / LC2026.zip / LCspc102.zip ...
                elif target == "lc":

                    DPrint(f"[UPLOAD]({job_id}) 处理LC升级包")
                    lc_inner = extract_inner_zip_by_prefix(outer_zip_path, 'LC', work_dir)
                    # ===== 处理 LC 包 =====
                    lc_out_path = UPLOAD_DIR / "LC"
                    lc_out_path.mkdir(parents=True, exist_ok=True)
                    if lc_inner and zipfile.is_zipfile(lc_inner):
                        with zipfile.ZipFile(lc_inner, 'r') as zf:
                            safe_extract(zf, lc_out_path)

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
                            if now_spc_version == releaseVersion:
                                DPrint(f'current SPC version is already object version: {releaseVersion}')
                                _write_status(job_id, STATE_ERROR, 0, f'current SPC version is already object version: {releaseVersion}')
                                return
                                # return jsonify({
                                #     'error': f'current SPC version is already object version: {releaseVersion}'
                                # }), 400
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

        threading.Thread(target=_bg_process, daemon=True).start()

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

# 状态回读,单独服务
# @g3_bp.route('/api/upgrade/process', methods=['GET'])
# def status_get():
#     try:
#         job = (request.args.get('taskName') or '').strip()
#         raw_target = (request.args.get('firmwareCategory') or '').strip()
#         # getlist 直接拿到列表字符串
#         id_str_list = request.args.getlist("deviceId")
#         if not job:
#             return jsonify({'taskName': 'N/A', 'status': STATE_ERROR, 'error': 'taskName is required'}), 400
#         if not id_str_list:
#             return jsonify({'taskName': job, 'status': STATE_ERROR, 'error': 'deviceId is required'}), 400
#         # 转int列表
#         deviceId = [int(x) for x in id_str_list]
#         target = parse_targets(raw_target)
#         _processes = []
#         _states = []
#         if not job:
#             return jsonify({'error': 'Missing taskName parameter'}), 400
#         if target in ["pcs-g2", "pcs-g3"]:
#             # 读取寄存器
#             for id in deviceId:
#                 if id < 1:
#                     DPrint(f"设备编号异常: {id} < 1")
#                     continue
#                 process_address = common.PCS_BASE_UPGRADE_PROCESS_ADDR + common.PCS_ADDR_STEP * (id - 1)
#                 state_address =  common.PCS_BASE_UPGRADE_STATE_ADDR + common.PCS_ADDR_STEP * (id - 1)
#                 try:
#                     process_registers = query_register_data(FIXED_DEVICE_ID, READ_INPUT_REGISTER, process_address, 1)
#                     state_registers = query_register_data(FIXED_DEVICE_ID, READ_INPUT_REGISTER, state_address, 1)
#                     _process = int(process_registers[0]) & 0xFFFF
#                     _state = int(state_registers[0]) & 0xFFFF
#                     _processes.append(_process)
#                     _states.append(_state)

#                 except Exception as e:
#                     DPrint(f"地址 {process_address} / {state_address} 读取异常: {e}")
#                     continue
#         else:
#             job = str(job).strip()
#             path = STATUS_DIR / f'{job}.json'
#             if path.exists():
#                 with open(path, 'r', encoding='utf-8') as f:
#                     status_data = json.load(f)
#             _process = status_data.get('progress', 0)
#             _state = UPGRADE_STATE_MAP.get(status_data.get('state'), 'unknown')
#             _processes.append(_process)
#             _states.append(_state)
#         return jsonify({'taskName': job,
#                         'process': _processes,
#                         'status': _states
#                         }), 200

#     except Exception as e:
#         DPrint(f"[STATUS] 获取状态异常: {e}")
#         return jsonify({'error': str(e)}), 500

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
            operatorName = req_data.get("operatorName", "")
            deviceid_raw = req_data.get("deviceid", "")
            address_raw = req_data.get("address", "")
            value_raw = req_data.get("value", "")
        else:
            operatorName = request.form.get('operatorName', '')
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
