#!/usr/bin/env python3
import os, io, csv, json, re, ipaddress
import pymysql
import sqlite3
from datetime import datetime
from sqlalchemy import text
from flask import request, jsonify, make_response, Response
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime
from config import engine, remote_client_lock, remote_client, LOCAL_DIR, REMOTE_USER, REMOTE_HOST, REMOTE_DIR, REMOTE_PORT, SSH_KEY_PATH, ZLOG_DIR, HOST_IP
from utils.systemctl import schedule_reboot, _base_ssh_args, run_cmd, _base_scp_args, schedule_reboot, norm_dt, NETWORK_CONFIG_PATH
from utils.utils import DPrint, now_str, jdump
import utils.method as method
from utils.ini import read_ini_system_counts, get_ini_path, read_ini_all
from flask import Blueprint, g
import config
import utils.operationLog as operationLog

g2_bp = Blueprint("g2", __name__)
@g2_bp.after_request
def after_request(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    return response

# ================== 拉取接口 & 诊断接口 ==================
@g2_bp.route('/fault_wave/fetch', methods=['POST'])
def fetch_wave():
    """
    固定拉取 pcs1.db 文件（覆盖本地），并返回本地已有的全部文件名(local_files)。
    """
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)

    def list_local_files():
        return sorted([p.name for p in LOCAL_DIR.iterdir() if p.is_file()])

    ssh_target = f"{REMOTE_USER}@{REMOTE_HOST}"

    # 只拉取固定的文件名 pcs1.db
    list_cmd = _base_ssh_args() + [
        ssh_target,
        f"find {REMOTE_DIR} -maxdepth 1 -type f -name 'pcs1.db' -printf '%f\\n'"
    ]
    rc, out, err = run_cmd(list_cmd, timeout=30)

    if rc != 0:
        all_local = list_local_files()
        return jsonify({
            "ok": False,
            "error": f"列远端目录失败: {err.strip()}",
            "dest_dir": str(LOCAL_DIR),
            "local_files": all_local,
            "local_count": len(all_local),
            "fetched": [],
            "errors": []
        }), 500

    remote_names = [line.strip() for line in out.splitlines() if line.strip() == "pcs1.db"]
    if not remote_names:
        all_local = list_local_files()
        return jsonify({
            "ok": False,
            "error": "远端未找到 pcs1.db 文件",
            "dest_dir": str(LOCAL_DIR),
            "local_files": all_local,
            "local_count": len(all_local),
            "fetched": [],
            "errors": []
        }), 404

    # 无条件拉取并覆盖
    fetched, errors = [], []
    for name in remote_names:
        remote_path = f"{ssh_target}:{REMOTE_DIR}/{name}"
        local_path  = str(LOCAL_DIR / name)
        scp_cmd = _base_scp_args() + [remote_path, local_path]
        rc, _o, _e = run_cmd(scp_cmd, timeout=120)
        if rc == 0:
            fetched.append(name)
        else:
            errors.append({"file": name, "error": _e.strip()})

    # 返回结果
    all_local = list_local_files()
    ok = (len(errors) == 0)
    return jsonify({
        "ok": ok,
        "message": f"已拉取 pcs1.db（覆盖）" if ok else f"拉取失败",
        "dest_dir": str(LOCAL_DIR),
        "fetched": fetched,
        "errors": errors,
        "local_files": all_local,
        "local_count": len(all_local)
    }), (200 if ok else 207)

@g2_bp.route('/fault_wave/diag', methods=['GET'])
def fault_wave_diag():
    """快速诊断 SSH/目录/权限问题"""
    ssh_target = f"{REMOTE_USER}@{REMOTE_HOST}"
    checks = {}

    def add_check(name, cmd, timeout=10):
        rc, so, se = run_cmd(cmd, timeout=timeout)
        checks[name] = {"rc": rc, "stdout": so, "stderr": se}

    add_check("whoami_local", ["bash", "-lc", "whoami; id; ls -ld ~/.ssh ~/.ssh/id_* ~/.ssh/authorized_keys || true"])
    add_check("ssh_version", _base_ssh_args() + ["-V"])
    add_check("ssh_echo", _base_ssh_args() + [ssh_target, "echo OK && whoami && ls -ld ~/.ssh ~/.ssh/authorized_keys || true"])
    add_check("remote_ls", _base_ssh_args() + [ssh_target, f"ls -l {REMOTE_DIR} || true"])
    add_check("remote_find", _base_ssh_args() + [ssh_target, f"find {REMOTE_DIR} -maxdepth 1 -type f -printf '%f\\n' || true"])

    return jsonify({
        "config": {
            "REMOTE_USER": REMOTE_USER,
            "REMOTE_HOST": REMOTE_HOST,
            "REMOTE_PORT": REMOTE_PORT,
            "REMOTE_DIR": REMOTE_DIR,
            "LOCAL_DIR": str(LOCAL_DIR),
            "SSH_KEY_PATH": SSH_KEY_PATH,
        },
        "checks": checks
    })
@g2_bp.route("/system/reboot", methods=["POST"])
def system_reboot():
    reboot_err = schedule_reboot(2)
    if reboot_err is not None:
        return jsonify({"ok": False, "error": reboot_err}), 500

    return jsonify({
        "ok": True,
        "message": "设备将在 2 秒后重启",
        "reboot_scheduled_in": 2
    }), 200
# === 统计指定本地 sqlite 的行数（支持时间范围） ===
@g2_bp.route('/sqlite/count_rows', methods=['POST'])
def sqlite_count_rows():
    """
    Request(JSON):
      { "file": "xxx.db", "table": "fault_logs",
        "start_time": "YYYY-MM-DD HH:MM[:SS]|YYYY-MM-DDTHH:MM[:SS]",
        "end_time":   "..." }
    """
    try:
        data = request.get_json(force=True) or {}
        fname = str(data.get("file", "")).strip()
        table = str(data.get("table", "")).strip()
        start_time = norm_dt(str(data.get("start_time", "")).strip())
        end_time   = norm_dt(str(data.get("end_time", "")).strip())

        if not fname:
            return jsonify({"ok": False, "error": "缺少 file"}), 400
        if not table:
            return jsonify({"ok": False, "error": "缺少 table"}), 400

        safe_name = os.path.basename(fname)
        db_path = LOCAL_DIR / safe_name
        if not db_path.is_file():
            return jsonify({"ok": False, "error": f"数据库不存在: {db_path}"}), 404

        if not table.replace('_', '').isalnum():
            return jsonify({"ok": False, "error": "非法表名（仅允许字母数字下划线）"}), 400

        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?;", (table,))
            if cur.fetchone() is None:
                return jsonify({"ok": False, "error": f"表不存在: {table}"}), 404

            where = ""
            params = []
            if start_time and end_time:
                where = 'WHERE "fault_time" BETWEEN ? AND ?'
                params = [start_time, end_time]
            elif start_time:
                where = 'WHERE "fault_time" >= ?'
                params = [start_time]
            elif end_time:
                where = 'WHERE "fault_time" <= ?'
                params = [end_time]

            sql = f'SELECT COUNT(*) FROM "{table}" {where}'
            cur.execute(sql, params)
            row = cur.fetchone()
            count = int(row[0]) if row else 0
        finally:
            conn.close()

        return jsonify({"ok": True, "file": safe_name, "table": table, "count": count})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# === 分帧查询列数据（支持时间范围） ===
@g2_bp.route('/sqlite/query_series', methods=['POST'])
def sqlite_query_series():
    """
    Request(JSON):
      {
        "file": "test.db",
        "table": "fault_logs",
        "columns": ["v_rs", "v_ts"],
        "frame": 1,
        "frame_size": 500,
        "start_time": "...",
        "end_time":   "..."
      }
    """
    try:
        data = request.get_json(force=True) or {}
        fname   = str(data.get("file", "")).strip()
        table   = str(data.get("table", "")).strip()
        columns = data.get("columns", [])
        frame   = int(data.get("frame", 1))
        fsize   = int(data.get("frame_size", 500))
        start_time = norm_dt(str(data.get("start_time", "")).strip())
        end_time   = norm_dt(str(data.get("end_time", "")).strip())

        if not fname or not table or not columns:
            return jsonify({"ok": False, "error": "缺少 file/table/columns"}), 400
        if frame < 1 or fsize < 1:
            return jsonify({"ok": False, "error": "frame/frame_size 非法"}), 400

        if not table.replace('_', '').isalnum():
            return jsonify({"ok": False, "error": "非法表名"}), 400
        for c in columns:
            if not isinstance(c, str) or not c.replace('_', '').isalnum():
                return jsonify({"ok": False, "error": f"非法列名: {c}"}), 400

        safe_name = os.path.basename(fname)
        db_path = LOCAL_DIR / safe_name
        if not db_path.is_file():
            return jsonify({"ok": False, "error": f"数据库不存在: {db_path}"}), 404

        offset = (frame - 1) * fsize
        sel_cols = ", ".join([f'"{c}"' for c in columns])

        where = ""
        params = []
        if start_time and end_time:
            where = 'WHERE "fault_time" BETWEEN ? AND ?'
            params.extend([start_time, end_time])
        elif start_time:
            where = 'WHERE "fault_time" >= ?'
            params.append(start_time)
        elif end_time:
            where = 'WHERE "fault_time" <= ?'
            params.append(end_time)

        sql = f'SELECT {sel_cols} FROM "{table}" {where} ORDER BY "id" LIMIT ? OFFSET ?'
        params.extend([fsize, offset])

        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()
        finally:
            conn.close()

        series = {c: [] for c in columns}
        for r in rows:
            for idx, c in enumerate(columns):
                series[c].append(r[idx])

        return jsonify({
            "ok": True,
            "file": safe_name,
            "table": table,
            "start": offset,
            "limit": fsize,
            "rows": len(rows),
            "series": series
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# === zlog csv: 按时间范围读取第二列 ===
@g2_bp.route('/zlog/query_series', methods=['POST'])
def zlog_query_series():
    """
    Request(JSON):
      {
        "file": "operation20240101" | "operation20240101.csv",
        "start_time": "YYYY-MM-DD HH:MM[:SS]|YYYY-MM-DDTHH:MM[:SS]",
        "end_time":   "..."
      }
    CSV 格式:
      第一列: 时间(精确到秒)
      第二列: 数值
    """
    try:
        data = request.get_json(force=True) or {}
        fname = str(data.get("file", "")).strip()
        start_time = norm_dt(str(data.get("start_time", "")).strip())
        end_time   = norm_dt(str(data.get("end_time", "")).strip())

        if not fname:
            return jsonify({"ok": False, "error": "缺少 file"}), 400

        safe_name = os.path.basename(fname)
        if not safe_name.lower().endswith(".csv"):
            safe_name = safe_name + ".csv"

        if not re.fullmatch(r"operation_?\d{8}\.csv", safe_name):
            return jsonify({"ok": False, "error": "file 必须是 operationYYYYMMDD 或 operation_YYYYMMDD（可带 .csv）"}), 400

        csv_path = ZLOG_DIR / safe_name
        if not csv_path.is_file():
            alt_name = None
            if re.fullmatch(r"operation\d{8}\.csv", safe_name):
                alt_name = safe_name.replace("operation", "operation_", 1)
            elif re.fullmatch(r"operation_\d{8}\.csv", safe_name):
                alt_name = safe_name.replace("operation_", "operation", 1)
            if alt_name:
                alt_path = ZLOG_DIR / alt_name
                if alt_path.is_file():
                    csv_path = alt_path
                    safe_name = alt_name
                else:
                    return jsonify({"ok": False, "error": f"文件不存在: {csv_path}"}), 404
            else:
                return jsonify({"ok": False, "error": f"文件不存在: {csv_path}"}), 404

        if not start_time and not end_time:
            return jsonify({"ok": False, "error": "start_time/end_time 至少提供一个"}), 400

        start_dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S") if start_time else None
        end_dt = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S") if end_time else None

        results = []
        with open(csv_path, "rb") as f:
            raw = f.read().replace(b"\x00", b"")
        text = raw.decode("utf-8", errors="ignore")
        reader = csv.reader(io.StringIO(text))
        for row in reader:
            if len(row) < 2:
                continue
            ts_raw = str(row[0]).strip()
            val_raw = str(row[1]).strip()
            if not ts_raw:
                continue
            try:
                ts = datetime.strptime(ts_raw, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue

            if start_dt and ts < start_dt:
                continue
            if end_dt and ts > end_dt:
                continue

            results.append({
                "time": ts_raw,
                "value": val_raw
            })

        return jsonify({
            "ok": True,
            "file": safe_name,
            "start_time": start_time or None,
            "end_time": end_time or None,
            "count": len(results),
            "values": results
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ================== 业务路由 ==================
@g2_bp.route('/export_csv_stream', methods=['GET'])
def export_csv_stream():
    table_name = request.args.get('table')
    if not table_name or not table_name.replace('_', '').isalnum():
        DPrint(f"[{now_str()}] [CSV导出] 非法表名: {table_name}")
        return jsonify({'error': 'Invalid table name'}), 400

    DPrint(f"[{now_str()}] [CSV导出] 开始导出表: {table_name}")

    def generate():
        conn = None
        cursor = None
        row_count = 0
        try:
            conn = pymysql.connect(
                host=HOST_IP, user='root', password='qwer1234',
                db='log_db', charset='utf8mb4', cursorclass=pymysql.cursors.SSCursor
            )
            cursor = conn.cursor()
            cursor.execute(f"SELECT * FROM `{table_name}`")
            headers = [desc[0] for desc in cursor.description]
            DPrint(f"[{now_str()}] [CSV导出] 表头: {headers}")

            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(headers)
            yield output.getvalue()
            output.seek(0); output.truncate(0)

            for row in cursor:
                row_count += 1
                writer.writerow(row)
                if row_count % 1000 == 0:
                    DPrint(f"[{now_str()}] [CSV导出] 已输出 {row_count} 行...")
                yield output.getvalue()
                output.seek(0); output.truncate(0)
        except Exception as e:
            DPrint(f"[{now_str()}] [CSV导出] 异常: {e}")
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["error", str(e)])
            yield output.getvalue()
        finally:
            if cursor is not None:
                cursor.close()
            if conn is not None:
                conn.close()
            DPrint(f"[{now_str()}] [CSV导出] 完成，总行数（不含表头）: {row_count}")

    response = Response(generate(), mimetype='text/csv')
    response.headers.set('Content-Disposition', 'attachment', filename=f'{table_name}.csv')
    return response

@g2_bp.route('/api', methods=['GET', 'POST', 'OPTIONS'])
def GetData():
    if request.method == 'GET':
        DPrint(f"[{now_str()}] 完整URL: {request.url}")
        sql = request.args.get("sql")
        params = request.args.get("params")
        if not sql or params != 'root':
            err = {'error': 'invalid params'}
            DPrint(f"[{now_str()}] [GET /api] 参数非法: sql={sql}, params={params}")
            return jsonify(err), 400
        try:
            with config.engine.connect() as conn:
                result = conn.execute(text(sql))
                rows = result.fetchall()
                data_packet_arr = [','.join(map(str, row)) for row in rows]
                protocol = ':\r'.join(data_packet_arr)
                response_data = {"sql": sql, "params": params, "result": protocol}
                DPrint(f"[{now_str()}] [GET响应] 返回数据: {jdump(response_data)}")

                response = make_response(json.dumps(response_data))
                response.headers['Access-Control-Allow-Origin'] = '*'
                return response
        except SQLAlchemyError as e:
            DPrint(f"[{now_str()}] [GET /api] SQLAlchemy 异常: {e}")
            return jsonify({"error": str(e)}), 500

    elif request.method == 'POST':
        bodyData = request.get_json()
        DPrint(f"[{now_str()}] [POST /api] 接收到前端数据: {jdump(bodyData)}")
        required_keys = ['deviceid', 'functioncode', 'Address', 'Quantity']
        if not bodyData or not all(k in bodyData for k in required_keys):
            err = {'error': 'Missing required keys.'}
            DPrint(f"[{now_str()}] [POST /api] 缺少必要字段")
            return jsonify(err), 400
        try:
            deviceid = list(map(int, bodyData['deviceid'].split(',')))
            functioncode = list(map(int, bodyData['functioncode'].split(',')))
            address = list(map(int, bodyData['Address'].split(',')))
            quantity = list(map(int, bodyData['Quantity'].split(',')))
            value_list = list(map(int, bodyData.get('value', '0').split(',')))
        except ValueError:
            err = {'error': 'Invalid value types.'}
            DPrint(f"[{now_str()}] [POST /api] 类型转换错误")
            return jsonify(err), 400
        if any(q < 1 for q in quantity):
            err = {'error': 'Quantity is out of range.'}
            DPrint(f"[{now_str()}] [POST /api] Quantity 越界: {quantity}")
            return jsonify(err), 400

        data_packet_arr = []
        for i in range(len(deviceid)):
            if functioncode[i] == 6:
                write_address = address[i]
                value = value_list[i]
                write_value = (value + 0x10000) if value < 0 else value
                try:
                    result, attempt_no = method.write_register_with_retry(write_address, write_value, slave=1)
                    if result is not None and (not result.isError()):
                        strval = f"ok({write_address})"
                    else:
                        DPrint(f"[{now_str()}] [POST /api] ??????: addr={write_address}, attempt={attempt_no}, result={result}")
                        strval = f"error({write_address})"
                except Exception as e:
                    DPrint(f"[{now_str()}] [POST /api] 写寄存器异常: addr={write_address}, err={e}")
                    with remote_client_lock:
                        remote_client.close()
                    strval = f"exception({write_address})"
                data_packet_arr.append(strval)
            elif deviceid[i] == 1:
                result = method.query_register_data(deviceid[i], functioncode[i], address[i], quantity[i])
                data_packet_arr.append(','.join(map(str, result)))
            else:
                result = method.method.query_rank_register_data(deviceid[i] - 2, functioncode[i], address[i], quantity[i])
                data_packet_arr.append(','.join(map(str, result)))

        ret = [
            {'deviceid': bodyData['deviceid']},
            {'functioncode': bodyData['functioncode']},
            {'Address': bodyData['Address']},
            {'Quantity': bodyData['Quantity']},
            {'Registers': ':'.join(data_packet_arr)}
        ]

        DPrint(f"[{now_str()}] [POST响应] 返回数据: {jdump(ret)}")

        response = make_response(json.dumps(ret))
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response

    else:
        DPrint(f"[{now_str()}] [OPTIONS /api] 预检请求")
        response = make_response()
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST'
        response.headers['Access-Control-Allow-Headers'] = 'x-requested-with,Content-Type'
        return response

@g2_bp.route("/network/set_ip", methods=["POST"])
def network_set_ip():
    """
    支持两种请求格式：

    1. 单对象：
    {
        "iface": "net1",
        "ip": "192.168.2.136",
        "netmask": "255.255.255.0",
        "gateway": "192.168.2.1"
    }

    2. 数组：
    [
        {
            "id": 1,
            "iface": "net1",
            "ip": "192.168.2.136",
            "netmask": "255.255.255.0",
            "gateway": "192.168.2.1"
        },
        {
            "id": 2,
            "iface": "net2",
            "ip": "192.168.2.137",
            "netmask": "255.255.255.0",
            "gateway": "192.168.2.1"
        }
    ]

    说明：
      - iface 仅允许 net1/net2/net3/net4
      - 只允许 net1 设置网关，其他接口只支持设置 IP 和子网掩码
      - 支持一次修改 1~4 个端口
      - 如果任何一个端口参数非法，则整个请求失败，不执行任何修改
      - 所有校验通过后，统一调度后台应用 IP，并写入 ini
    """
    OperationType = operationLog.OperationType.PARAM
    operatorName = "unknown"
    operationTarget = "LC network"
    _result = operationLog.OperationResult.FAIL
    remark = "未执行"

    try:
        payload = request.get_json(force=True)
        if not payload:
            _result = operationLog.OperationResult.FAIL
            remark = "请求体为空"
            msg = {"ok": False, "error": "请求体为空"}
            DPrint(f"[{now_str()}] [/network/set_ip] 400 空请求: {jdump(msg)}")
            return jsonify(msg), 400
        # 兼容单对象和数组
        if isinstance(payload, dict):
            items = [payload]
            operatorName = g.current_user["username"]
        elif isinstance(payload, list):
            items = payload
            operatorName = g.current_user["username"]
        else:
            _result = operationLog.OperationResult.FAIL
            remark = "请求格式错误，必须为对象或对象数组"
            msg = {"ok": False, "error": "请求格式错误，必须为对象或对象数组"}
            DPrint(f"[{now_str()}] [/network/set_ip] 400 格式错误: {jdump(msg)}")
            return jsonify(msg), 400

        if len(items) == 0:
            _result = operationLog.OperationResult.FAIL
            remark = "请求数组不能为空"
            msg = {"ok": False, "error": "请求数组不能为空"}
            DPrint(f"[{now_str()}] [/network/set_ip] 400 空数组: {jdump(msg)}")
            return jsonify(msg), 400

        allowed_ifaces = {"net1", "net2", "net3", "net4"}
        parsed_items = []
        req_ip_set = set()

        # =========================
        # 第一阶段：全部校验，不做任何修改
        # =========================
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                _result = operationLog.OperationResult.FAIL
                remark = f"第 {idx+1} 项不是对象"
                msg = {"ok": False, "error": f"第 {idx+1} 项不是对象"}
                DPrint(f"[{now_str()}] [/network/set_ip] 400 项格式错误: {jdump(msg)}")
                return jsonify(msg), 400

            raw_iface = item.get("iface") or item.get("interface") or item.get("port")
            raw_ip = item.get("ip") or item.get("address")
            netmask = item.get("netmask") or item.get("mask")
            prefix = item.get("prefix")
            gateway_raw = item.get("gateway") or item.get("gw")
            item_id = item.get("id", idx + 1)

            if raw_iface is None or raw_ip is None:
                _result = operationLog.OperationResult.FAIL
                remark = f"第 {idx+1} 项缺少 iface/interface/port 或 ip/address 字段"
                msg = {
                    "ok": False,
                    "error": f"第 {idx+1} 项缺少 iface/interface/port 或 ip/address 字段",
                    "item": item
                }
                DPrint(f"[{now_str()}] [/network/set_ip] 400 缺字段: {jdump(msg)}")
                return jsonify(msg), 400

            try:
                iface = method.normalize_interface_name(raw_iface).strip()
            except Exception as e:
                _result = operationLog.OperationResult.FAIL
                remark = f"第 {idx+1} 项接口名非法: {e}"
                msg = {
                    "ok": False,
                    "error": f"第 {idx+1} 项接口名非法: {e}",
                    "item": item
                }
                DPrint(f"[{now_str()}] [/network/set_ip] 400 iface错误: {jdump(msg)}")
                return jsonify(msg), 400

            if iface not in allowed_ifaces:
                _result = operationLog.OperationResult.FAIL
                remark = f"第 {idx+1} 项接口 {iface} 不允许，必须是 net1/net2/net3/net4"
                msg = {
                    "ok": False,
                    "error": f"第 {idx+1} 项接口 {iface} 不允许，必须是 net1/net2/net3/net4",
                    "item": item
                }
                DPrint(f"[{now_str()}] [/network/set_ip] 400 iface范围错误: {jdump(msg)}")
                return jsonify(msg), 400

            try:
                ip_iface = method.parse_ip_interface(raw_ip, netmask=netmask, prefix=prefix)

                gateway_ip = None
                # 只有 net1 可以设置网关，其他接口直接忽略，但仍然记录到 INI 文件中
                if gateway_raw and iface == "net1":
                    gateway_ip = ipaddress.ip_address(str(gateway_raw).strip())
                    if gateway_ip.version != 4:
                        raise ValueError("仅支持 IPv4 网关")

                    if gateway_ip not in ip_iface.network:
                        raise ValueError(
                            f"The gateway {gateway_ip} and the IP address {ip_iface} "
                            f"are not on the same network segment ({ip_iface.network})"
                        )

                    if gateway_ip == ip_iface.ip:
                        raise ValueError("The gateway cannot be the same as the local IP address.")
                elif gateway_raw and iface != "net1":
                    # 对于 net2、net3、net4，网关不生效，但仍然写入 INI 文件
                    gateway_ip = ipaddress.ip_address(str(gateway_raw).strip()) if gateway_raw else None
            except ValueError as e:
                _result = operationLog.OperationResult.FAIL
                remark = f"第 {idx+1} 项参数校验失败: {e}"
                msg = {
                    "ok": False,
                    "error": f"第 {idx+1} 项参数校验失败: {e}",
                    "item": item
                }
                DPrint(f"[{now_str()}] [/network/set_ip] 400 IP校验失败: {jdump(msg)}")
                return jsonify(msg), 400

            # 检查本次请求中是否有重复 IP
            ip_str = str(ip_iface.ip)
            if ip_str in req_ip_set:
                _result = operationLog.OperationResult.FAIL
                remark = f"请求中存在重复 IP: {ip_str}"
                msg = {
                    "ok": False,
                    "error": f"请求中存在重复 IP: {ip_str}",
                    "item": item
                }
                DPrint(f"[{now_str()}] [/network/set_ip] 400 重复IP: {jdump(msg)}")
                return jsonify(msg), 400
            req_ip_set.add(ip_str)

            # 检查接口是否存在
            rc, so, se = run_cmd(["ip", "link", "show", iface], timeout=5)
            if rc != 0:
                _result = operationLog.OperationResult.FAIL
                remark = f"网口不存在: {iface}"
                msg = {
                    "ok": False,
                    "error": f"网口不存在: {iface}",
                    "stdout": so.strip(),
                    "stderr": se.strip(),
                    "item": item
                }
                DPrint(f"[{now_str()}] [/network/set_ip] 404 网口不存在: {jdump(msg)}")
                return jsonify(msg), 404

            parsed_items.append({
                "id": item_id,
                "iface": iface,
                "ip_iface": ip_iface,
                "gateway_ip": gateway_ip,
                "raw_item": item
            })

        # =========================
        # 第二阶段：全部执行
        # =========================
        results = []
        errors = []

        for entry in parsed_items:
            iface = entry["iface"]
            ip_iface = entry["ip_iface"]
            gateway_ip = entry["gateway_ip"]
            item_id = entry["id"]

            apply_delay = 0.5
            schedule_err = method.schedule_network_change(
                iface,
                ip_iface,
                gateway=gateway_ip,
                delay_sec=apply_delay
            )

            ini_path, ini_err = method.persist_network_to_ini(
                iface,
                ip_iface,
                gateway=gateway_ip
            )

            one = {
                "id": item_id,
                "iface": iface,
                "cidr": str(ip_iface),
                "ip": str(ip_iface.ip),
                "netmask": str(ip_iface.netmask),
                "gateway": str(gateway_ip) if gateway_ip else None,
                "config_path": str(NETWORK_CONFIG_PATH),
                "ini_path": ini_path,
                "schedule_error": schedule_err,
                "ini_error": ini_err,
                "ok": (schedule_err is None and ini_err is None)
            }

            if one["ok"]:
                results.append(one)
            else:
                errors.append(one)

        resp = {
            "ok": len(errors) == 0,
            "count": len(parsed_items),
            "success_count": len(results),
            "error_count": len(errors),
            "results": results,
            "errors": errors
        }

        if resp["ok"]:
            _result = operationLog.OperationResult.SUCCESS
            remark = f"成功设置 {len(results)}/{len(parsed_items)} 个网口IP"
        else:
            _result = operationLog.OperationResult.FAIL
            remark = f"部分失败: {len(results)}/{len(parsed_items)} 成功, {len(errors)} 失败"

        status = 200 if resp["ok"] else 500
        DPrint(f"[{now_str()}] [/network/set_ip] 批量处理完成: {jdump(resp)}")
        return jsonify(resp), status

    except Exception as e:
        _result = operationLog.OperationResult.FAIL
        remark = f"设置IP异常: {e}"
        msg = {"ok": False, "error": f"网络设置IP失败: {e}"}
        DPrint(f"[{now_str()}] [/network/set_ip] 500 异常: {jdump(msg)}")
        return jsonify(msg), 500
    finally:
        operationLog.enqueue_operation_log(
            operatorName,
            OperationType,
            operationTarget,
            1,
            _result,
            remark
        )

@g2_bp.route("/ini/update", methods=["POST"])
def ini_update():
    try:
        OperationType = operationLog.OperationType.PARAM
        operatorName = "unknown"
        operationTarget = "LC ini"
        _result = operationLog.OperationResult.FAIL
        remark = "未执行"
        payload = request.get_json(force=True) or {}
    except Exception as e:
        msg = {"ok": False, "error": f"无法解析 JSON: {e}"}
        _result = operationLog.OperationResult.FAIL
        remark = f"无法解析 JSON: {e}"
        DPrint(f"[{now_str()}] [/ini/update] 400 JSON: {jdump(msg)}")
        return jsonify(msg), 400

    try:
        operatorName = g.current_user["username"]
        result = method.update_ini_from_payload(payload)
        verify = method.verify_ini_matches_payload(payload, result["path"])
        if not verify["ok"]:
            msg = {"ok": False, "error": "INI 校验失败", "details": verify["errors"], "path": result["path"]}
            _result = operationLog.OperationResult.FAIL
            remark = f"INI 校验失败: {jdump(msg)}"
            DPrint(f"[{now_str()}] [/ini/update] 校验失败: {jdump(msg)}")
            return jsonify(msg), 400

        reboot_err = schedule_reboot(2)
        resp = {
            "ok": reboot_err is None,
            **result,
            "verify": verify,
            "reboot_error": reboot_err,
            "reboot_scheduled_in": 2,
        }
        log_msg = "成功更新，已调度 2 秒后重启" if reboot_err is None else f"更新成功但调度重启失败: {reboot_err}"
        DPrint(f"[{now_str()}] [/ini/update] {log_msg}: {jdump(resp)}")
        status = 200 if reboot_err is None else 500
        _result = operationLog.OperationResult.SUCCESS
        remark = log_msg
        return jsonify(resp), status
    except FileNotFoundError as e:
        msg = {"ok": False, "error": str(e)}
        _result = operationLog.OperationResult.FAIL
        remark = f"文件未找到: {str(e)}"
        DPrint(f"[{now_str()}] [/ini/update] 404: {jdump(msg)}")
        return jsonify(msg), 404
    except ValueError as e:
        msg = {"ok": False, "error": str(e)}
        _result = operationLog.OperationResult.FAIL
        remark = f"值错误: {str(e)}"
        DPrint(f"[{now_str()}] [/ini/update] 400: {jdump(msg)}")
        return jsonify(msg), 400
    except Exception as e:
        msg = {"ok": False, "error": f"更新失败: {e}"}
        _result = operationLog.OperationResult.FAIL
        remark = f"更新失败: {e}"
        DPrint(f"[{now_str()}] [/ini/update] 500: {jdump(msg)}")
        return jsonify(msg), 500
    finally:
        operationLog.enqueue_operation_log(
            operatorName,
            OperationType,
            operationTarget,
            1,
            _result,
            remark
        )
# ========== 状态接口 ==========
@g2_bp.route('/status/update', methods=['POST'])
def status_update():
    # 允许本机及内网来源（升级脚本、容器/网卡不同场景兼容）
    # {"job":"%s","state":%d,"progress":%d,"msg":"%s"}
    ra = request.remote_addr or ''
    if not (
        ra.startswith('127.')
        or ra == '::1'
        or ra.startswith('192.168.')
        or ra.startswith('10.')
        or ra.startswith('172.')
    ):
        return jsonify({'ok': False, 'error': f'forbidden from {ra}'}), 403

    data = request.get_json(silent=True) or {}
    job = data.get('job')
    state = data.get('state')
    progress = data.get('progress', 0)
    msg = data.get('msg', '')

    if not isinstance(job, str) or not isinstance(state, (int, float)) or not isinstance(progress, (int, float)):
        return jsonify({'ok': False, 'error': 'bad payload'}), 400

    method._write_status(job, int(state), progress, str(msg))
    return jsonify({'ok': True}), 200


@g2_bp.route("/ini/system_counts", methods=["GET", "POST"])
def ini_system_counts():
    try:
        data = read_ini_system_counts()
        resp = {"ok": True, "path": str(get_ini_path()), **data}
        DPrint(f"[{now_str()}] [/ini/system_counts] 返回: {jdump(resp)}")
        return jsonify(resp)
    except FileNotFoundError as e:
        msg = {"ok": False, "error": str(e)}
        DPrint(f"[{now_str()}] [/ini/system_counts] 404: {jdump(msg)}")
        return jsonify(msg), 404
    except (KeyError, ValueError) as e:
        msg = {"ok": False, "error": f"INI 字段缺失或格式错误: {e}"}
        DPrint(f"[{now_str()}] [/ini/system_counts] 400: {jdump(msg)}")
        return jsonify(msg), 400
    except Exception as e:
        msg = {"ok": False, "error": f"服务器异常: {e}"}
        DPrint(f"[{now_str()}] [/ini/system_counts] 500: {jdump(msg)}")
        return jsonify(msg), 500

@g2_bp.route("/ini/all", methods=["GET"])
def ini_all():
    try:
        data = read_ini_all()
        resp = {"ok": True, "path": str(get_ini_path()), "data": data}
        DPrint(f"[{now_str()}] [/ini/all] 返回全部内容")
        return jsonify(resp)
    except FileNotFoundError as e:
        msg = {"ok": False, "error": str(e)}
        DPrint(f"[{now_str()}] [/ini/all] 404: {jdump(msg)}")
        return jsonify(msg), 404
    except Exception as e:
        msg = {"ok": False, "error": f"服务器异常: {e}"}
        DPrint(f"[{now_str()}] [/ini/all] 500: {jdump(msg)}")
        return jsonify(msg), 500
