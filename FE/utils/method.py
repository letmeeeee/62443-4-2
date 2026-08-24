from constent.param_config import CONFIG_PARAMS_BY_DATA_TYPE, ADDR_CONFIG_CACHE
from config import INI_PATH, PERM_TABLE, STATUS_DIR, DEVICE_IP_MAP, engine, FIRMWARE_CATEGORY, SQL_TABLE_WORD, DEFINE_16BIT, READ_INPUT_REGISTER, FIXED_DEVICE_ID, HOST_IP, DB_HOST, DB_PORT, DB_NAME, DB_USER, remote_client, remote_client_lock, STATE_ERROR, STATE_DONE, STATE_IDLE, STATE_IN_PROGRESS
from daemon import registers_model, rank_model
from sqlalchemy import text
from utils.utils import debug_log, DPrint, now_str, _to_signed_32, _to_signed_16, _combine_uint32_big_endian
from utils.ini import ini_param, get_ini_path, read_ini_all, _write_ini, _ini_get_int, _get_pcs_device_type_by_brand, _ini_get_str
from utils.systemctl import schedule_reboot, run_cmd, restart_sys_service, NETWORK_CONFIG_PATH
from constent.device_info import DEVICE_TYPE, PCS_BRAND, BMS_BRAND
import constent.common as common
from constent.fault_all import FAULT_TABLE_ALL
from constent.mv_fault import MV_MC_Trip_Summary_ADDRESS, MV_MC_PCS_FAULT4_BASE_ADDRESS
import sys, time, ipaddress, configparser, struct, re, sqlite3, os, json, zipfile, shutil, threading, zlib, hmac, hashlib, tempfile, tarfile
from typing import List, Optional, Union, Tuple
from datetime import datetime
from pathlib import Path
from werkzeug.utils import secure_filename
from flask import jsonify
import constent.device_info as device_info
from constent.device_all_param import ALL_REG_LIST
import config
import hashlib
import secrets
from typing import Dict, Any, Optional

def get_job_upgrade_status(
    job: str,
    status_dir: Path,
    state_map: dict
) -> Tuple[int, str, str]:
    """
    读取任务升级状态JSON文件，返回进度与映射后状态
    :param job: 任务编号/名称
    :param status_dir: 状态文件根目录 Path对象
    :param state_map: 原始状态 -> 可读状态映射字典
    :return: (progress:int, state:str)
    """
    job_str = str(job).strip()
    file_path = status_dir / f"{job_str}.json"

    data: dict = {}
    # 仅当是文件且存在才读取
    if file_path.exists() and file_path.is_file():
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, PermissionError, OSError, UnicodeDecodeError):
            # 文件损坏、权限不足、编码错误全部兜底为空字典
            data = {}

    progress = data.get("progress", 0)
    raw_state = data.get("state")
    state = state_map.get(raw_state, "unknown")
    remark = data.get("msg", "")

    return progress, state, remark

def load_release_note(file_path: str = "release_note.json") -> Dict[str, Any]:
    """
    读取升级包release note json文件
    :param file_path: json文件路径，默认当前目录release_note.json
    :return: 解析后的完整字典数据
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        print(f"错误：文件 {file_path} 不存在")
        return {}
    except json.JSONDecodeError:
        print(f"错误：{file_path} JSON格式非法，解析失败")
        return {}
    except Exception as e:
        print(f"读取文件异常：{str(e)}")
        return {}

def get_spc_num(version: str) -> Optional[int]:
    """从版本字符串提取SPC后的数字"""
    match = re.search(r"SPC(\d+)", version)
    if match:
        return int(match.group(1))
    return None

def get_folder_dict(directory):
    """
    获取指定目录下的文件夹列表，并生成字典

    Args:
        directory (str): 目标目录路径

    Returns:
        dict: {文件夹名: 文件夹完整路径}
    """
    folder_dict = {}

    base_path = Path(directory)

    if not base_path.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")

    if not base_path.is_dir():
        raise NotADirectoryError(f"{directory} is not a directory")

    for item in base_path.iterdir():
        if item.is_dir():
            folder_dict[item.name] = str(item.resolve())

    return folder_dict

def _perm_table_exists(conn) -> bool:
    row = conn.execute(
        text("SHOW TABLES LIKE :tname"),
        {"tname": PERM_TABLE},
    ).fetchone()
    return row is not None

def _ensure_perm_table_in_request():
    try:
        ensure_permission_table()
        return None
    except Exception as e:
        return str(e)

def update_ini_from_payload(payload: dict, path: Optional[Path] = None):
    """
    前端字段 -> lc_data_set.ini 映射：
    - mainSystem -> sysNum
    - subSystem -> subNum
    - pcsCount -> pcsNum
    - bmsCount -> bmsNum
    - pointToPointEnabled -> P2P_EN (bool -> 0/1)
    - pcsList/bmsList: id/ip/port -> pcs{id}_ip, pcs{id}_port / bms{id}_ip, bms{id}_port
    - testCtlList: id/ip/port -> measure{id}_ip, measure{id}_port
    - bmsBrand -> bms1_brand ~ bms8_brand
    - pcsBrand -> pcs1_brand ~ pcs4_brand
    其余字段保持不变。
    """
    path = Path(path) if path else get_ini_path()
    if not path.is_file():
        raise FileNotFoundError(f"ini 不存在: {path}")

    cfg = configparser.ConfigParser()
    cfg.optionxform = str
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        cfg.read_file(f)

    if not cfg.has_section("SYSTEM"):
        cfg.add_section("SYSTEM")
    if not cfg.has_section("PCS_NETWORK"):
        cfg.add_section("PCS_NETWORK")
    if not cfg.has_section("BMS_NETWORK"):
        cfg.add_section("BMS_NETWORK")
    if not cfg.has_section("MEASURE_NETWORK"):
        cfg.add_section("MEASURE_NETWORK")

    mapping = {
        "mainSystem": "sysNum",
        "subSystem": "subNum",
        "pcsCount": "pcsNum",
        "bmsCount": "bmsNum",
    }

    system_updates = {}
    for req_key, ini_key in mapping.items():
        if req_key in payload:
            try:
                val = int(payload[req_key])
            except (TypeError, ValueError):
                raise ValueError(f"{req_key} 需为整数")
            cfg.set("SYSTEM", ini_key, str(val))
            system_updates[ini_key] = val

    if "pointToPointEnabled" in payload:
        val_raw = payload["pointToPointEnabled"]
        val = 1 if str(val_raw).lower() in ("1", "true", "yes", "on") else 0
        cfg.set("SYSTEM", "P2P_EN", str(val))
        system_updates["P2P_EN"] = val

    def _update_devices(section: str, prefix: str, items, label: str):
        if not items:
            return []
        updated = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError(f"{label} 项需为object: {item}")
            try:
                idx = int(item["id"])
            except Exception:
                raise ValueError(f"{label} 项缺 id 或非整数: {item}")
            ip = str(item.get("ip", "")).strip()
            if not ip:
                raise ValueError(f"{label}{idx} 缺 ip")
            try:
                port = int(item.get("port"))
            except Exception:
                raise ValueError(f"{label}{idx} port 需为整数")
            cfg.set(section, f"{prefix}{idx}_ip", ip)
            cfg.set(section, f"{prefix}{idx}_port", str(port))
            updated.append({"id": idx, "ip": ip, "port": port})
        return updated

    pcs_updated = _update_devices("PCS_NETWORK", "pcs", payload.get("pcsList", []), "pcs")
    bms_updated = _update_devices("BMS_NETWORK", "bms", payload.get("bmsList", []), "bms")
    measure_updated = _update_devices("MEASURE_NETWORK", "measure", payload.get("testCtlList", []), "measure")

    brand_updates = {
        "bms_brand": [],
        "pcs_brand": [],
    }

    if "bmsBrand" in payload:
        try:
            bms_brand_val = int(payload["bmsBrand"])
        except (TypeError, ValueError):
            raise ValueError("bmsBrand 需为整数")

        for i in range(1, 9):
            key = f"bms{i}_brand"
            cfg.set("BMS_NETWORK", key, str(bms_brand_val))
            brand_updates["bms_brand"].append({key: bms_brand_val})

    if "pcsBrand" in payload:
        try:
            pcs_brand_val = int(payload["pcsBrand"])
        except (TypeError, ValueError):
            raise ValueError("pcsBrand 需为整数")

        for i in range(1, 5):
            key = f"pcs{i}_brand"
            cfg.set("PCS_NETWORK", key, str(pcs_brand_val))
            brand_updates["pcs_brand"].append({key: pcs_brand_val})

    with open(path, "w", encoding="utf-8") as f:
        cfg.write(f)

    return {
        "path": str(path),
        "system": system_updates,
        "pcs": pcs_updated,
        "bms": bms_updated,
        "measure": measure_updated,
        **brand_updates,
    }
def verify_ini_matches_payload(payload: dict, path: Optional[Path] = None):
    """
    读取写回后的 ini，与前端 payload 做一致性校对。只校对被写入的字段。
    """
    path = Path(path) if path else get_ini_path()
    if not path.is_file():
        return {"ok": False, "errors": [f"ini 不存在: {path}"]}

    cfg = configparser.ConfigParser()
    cfg.optionxform = str
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        cfg.read_file(f)

    errors = []
    sec = "SYSTEM"
    mapping = {
        "mainSystem": "sysNum",
        "subSystem": "subNum",
        "pcsCount": "pcsNum",
        "bmsCount": "bmsNum",
    }

    for req_key, ini_key in mapping.items():
        if req_key in payload:
            try:
                expected = int(payload[req_key])
                actual = cfg.getint(sec, ini_key, fallback=None)
                if actual is None or actual != expected:
                    errors.append(f"[SYSTEM]{ini_key}={actual} 期望 {expected}")
            except Exception as e:
                errors.append(f"[SYSTEM]{ini_key} 读取失败: {e}")

    if "pointToPointEnabled" in payload:
        expected = 1 if str(payload["pointToPointEnabled"]).lower() in ("1", "true", "yes", "on") else 0
        actual = cfg.getint(sec, "P2P_EN", fallback=None)
        if actual is None or actual != expected:
            errors.append(f"[SYSTEM]P2P_EN={actual} 期望 {expected}")

    def _check_devices(section: str, prefix: str, items, label: str):
        if not items:
            return
        for item in items:
            try:
                idx = int(item["id"])
            except Exception:
                errors.append(f"{label} 项缺少/非法 id: {item}")
                continue
            expected_ip = str(item.get("ip", "")).strip()
            expected_port = None
            try:
                expected_port = int(item.get("port"))
            except Exception:
                errors.append(f"{label}{idx} port 非整数: {item.get('port')}")
            actual_ip = cfg.get(section, f"{prefix}{idx}_ip", fallback=None)
            actual_port = cfg.getint(section, f"{prefix}{idx}_port", fallback=None)
            if actual_ip != expected_ip:
                errors.append(f"[{section}]{prefix}{idx}_ip={actual_ip} 期望 {expected_ip}")
            if expected_port is not None and actual_port != expected_port:
                errors.append(f"[{section}]{prefix}{idx}_port={actual_port} 期望 {expected_port}")

    _check_devices("PCS_NETWORK", "pcs", payload.get("pcsList", []), "pcs")
    _check_devices("BMS_NETWORK", "bms", payload.get("bmsList", []), "bms")
    _check_devices("MEASURE_NETWORK", "measure", payload.get("testCtlList", []), "measure")

    if "bmsBrand" in payload:
        try:
            expected_bms_brand = int(payload["bmsBrand"])
            for i in range(1, 9):
                actual = cfg.getint("BMS_NETWORK", f"bms{i}_brand", fallback=None)
                if actual is None or actual != expected_bms_brand:
                    errors.append(f"[BMS_NETWORK]bms{i}_brand={actual} 期望 {expected_bms_brand}")
        except Exception as e:
            errors.append(f"bmsBrand 校验失败: {e}")

    if "pcsBrand" in payload:
        try:
            expected_pcs_brand = int(payload["pcsBrand"])
            for i in range(1, 5):
                actual = cfg.getint("PCS_NETWORK", f"pcs{i}_brand", fallback=None)
                if actual is None or actual != expected_pcs_brand:
                    errors.append(f"[PCS_NETWORK]pcs{i}_brand={actual} 期望 {expected_pcs_brand}")
        except Exception as e:
            errors.append(f"pcsBrand 校验失败: {e}")

    return {"ok": len(errors) == 0, "errors": errors}

def normalize_interface_name(raw_iface: str) -> str:
    """
    将传入的网口号/名称标准化：
    - 纯数字 -> eth{数字}
    - ethX 形式转为小写
    - 其余仅允许字母/数字/._:- 组合
    """
    if raw_iface is None:
        raise ValueError("缺少网口号/名称")
    iface = str(raw_iface).strip()
    if not iface:
        raise ValueError("网口号/名称为空")
    if iface.isdigit():
        return f"eth{iface}"
    if iface.lower().startswith("eth") and iface[3:].isdigit():
        return f"eth{int(iface[3:])}"
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", iface):
        raise ValueError("网口名称仅支持字母/数字/._:-")
    return iface

def parse_ip_interface(ip_value, netmask=None, prefix=None) -> ipaddress.IPv4Interface:
    """
    解析 IP，支持：
    - 直接传 CIDR，如 192.168.1.10/24
    - 传 ip + netmask（255.255.255.0 或前缀数字）
    - 传 ip + prefix（前缀数字）
    """
    if ip_value is None:
        raise ValueError("缺少 IP 地址")
    ip_text = str(ip_value).strip()
    if not ip_text:
        raise ValueError("IP 地址为空")

    try:
        if "/" in ip_text:
            ip_iface = ipaddress.ip_interface(ip_text)
        else:
            if prefix is not None and str(prefix).strip():
                ip_iface = ipaddress.ip_interface(f"{ip_text}/{int(prefix)}")
            elif netmask:
                mask_raw = str(netmask).strip()
                if mask_raw.isdigit():
                    ip_iface = ipaddress.ip_interface(f"{ip_text}/{int(mask_raw)}")
                else:
                    try:
                        prefix_len = ipaddress.IPv4Network(f"0.0.0.0/{mask_raw}", strict=False).prefixlen
                    except Exception:
                        raise ValueError(f"无效的子网掩码: {mask_raw}")
                    ip_iface = ipaddress.ip_interface(f"{ip_text}/{prefix_len}")
            else:
                raise ValueError("IP 需带掩码，如 192.168.1.10/24，或提供 netmask/prefix")
    except ValueError as e:
        raise ValueError(f"IP 地址格式错误: {e}")

    if ip_iface.version != 4:
        raise ValueError("仅支持 IPv4")
    return ip_iface

def apply_ip_runtime(iface: str, ip_iface: ipaddress.IPv4Interface) -> Optional[str]:
    """
    立即更新网口 IP（仅本次运行，需持久化配置文件保证重启后生效）。
    返回 None 表示成功，返回字符串表示错误。
    """
    cmds = [
        (["ip", "addr", "flush", "dev", iface], "flush"),
        (["ip", "addr", "add", str(ip_iface), "dev", iface], "add"),
        (["ip", "link", "set", iface, "up"], "link_up"),
    ]
    for cmd, desc in cmds:
        rc, so, se = run_cmd(cmd, timeout=10)
        if rc != 0:
            return f"{desc} 失败(rc={rc}): {(se or so).strip()}"
    return None

def apply_gateway_runtime(iface: str, gateway: ipaddress.IPv4Address) -> Optional[str]:
    """
    设置默认网关（替换当前默认路由）。
    """
    rc, so, se = run_cmd(["ip", "route", "replace", "default", "via", str(gateway), "dev", iface], timeout=10)
    if rc != 0:
        return f"设置网关失败(rc={rc}): {(se or so).strip()}"
    return None

def persist_interface_config(iface: str, ip_iface: ipaddress.IPv4Interface,
                             path: Path = NETWORK_CONFIG_PATH,
                             gateway: Optional[ipaddress.IPv4Address] = None) -> Optional[str]:
    """
    将网口 IP 写入 /etc/network/interfaces，覆盖原有 iface 块并追加新的静态配置。
    返回 None 表示成功，返回字符串表示错误。
    """
    if not path.exists():
        return f"持久化失败: {path} 不存在"
    try:
        lines = path.read_text().splitlines()
    except Exception as e:
        return f"读取 {path} 失败: {e}"

    new_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("iface") and stripped.split()[1:2] == [iface]:
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if nxt.startswith(" ") or not nxt.strip():
                    i += 1
                    continue
                break
            continue
        new_lines.append(line)
        i += 1

    if not any(l.strip().startswith(f"auto {iface}") for l in new_lines):
        new_lines.append(f"auto {iface}")

    new_lines.extend([
        f"iface {iface} inet static",
        f"    address {ip_iface.ip}",
        f"    netmask {ip_iface.netmask}",
    ])
    if gateway:
        new_lines.append(f"    gateway {gateway}")
    new_lines.append("")

    try:
        path.write_text("\n".join(new_lines).rstrip() + "\n")
        return None
    except Exception as e:
        return f"写入 {path} 失败: {e}"

def persist_network_to_ini(iface: str, ip_iface: ipaddress.IPv4Interface,
                           gateway: Optional[ipaddress.IPv4Address] = None,
                           path: Path = INI_PATH) -> Tuple[str, Optional[str]]:
    """
    将 /network/set_ip 的新配置写入 lc_data_set.ini。
    若已存在相同 iface 则替换，否则新增一个 NETWORK_* 段。
    返回 (写入路径, 错误或 None)。
    """
    path = Path(path)
    cfg = configparser.ConfigParser()
    cfg.optionxform = str

    seed_path = path if path.is_file() else get_ini_path()
    if seed_path.is_file():
        try:
            with open(seed_path, "r", encoding="utf-8", errors="ignore") as f:
                cfg.read_file(f)
        except Exception as e:
            return str(path), f"读取 {seed_path} 失败: {e}"

    section = None
    for sec in cfg.sections():
        if sec == "NETWORK" or sec.startswith("NETWORK_") or sec.startswith("NETWORK:"):
            if cfg.get(sec, "iface", fallback=None) == iface:
                section = sec
                break
    if section is None:
        if cfg.has_section("NETWORK") and not cfg.has_option("NETWORK", "iface"):
            section = "NETWORK"
        else:
            section = f"NETWORK_{iface}"
        if not cfg.has_section(section):
            cfg.add_section(section)

    cfg.set(section, "iface", iface)
    cfg.set(section, "cidr", str(ip_iface))
    cfg.set(section, "ip", str(ip_iface.ip))
    cfg.set(section, "netmask", str(ip_iface.netmask))
    cfg.set(section, "prefix", str(ip_iface.network.prefixlen))
    if gateway:
        cfg.set(section, "gateway", str(gateway))
    elif cfg.has_option(section, "gateway"):
        cfg.remove_option(section, "gateway")

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            cfg.write(f)
        return str(path), None
    except Exception as e:
        return str(path), f"写入 {path} 失败: {e}"

def schedule_network_change(iface: str, ip_iface: ipaddress.IPv4Interface,
                            gateway: Optional[ipaddress.IPv4Address] = None,
                            delay_sec: float = 0.5) -> Optional[str]:
    """
    后台异步修改 IP/网关并持久化，避免阻断当前 HTTP 连接。
    """
    def _task():
        try:
            if delay_sec > 0:
                time.sleep(delay_sec)
            apply_err = apply_ip_runtime(iface, ip_iface)
            if apply_err:
                DPrint(f"[{now_str()}] [/network/set_ip] 后台应用失败: {apply_err}")
                return
            if gateway:
                gw_err = apply_gateway_runtime(iface, gateway)
                if gw_err:
                    DPrint(f"[{now_str()}] [/network/set_ip] 后台网关失败: {gw_err}")
                    return
            persist_err = persist_interface_config(iface, ip_iface, gateway=gateway)
            reboot_err = None
            if persist_err is None:
                reboot_err = schedule_reboot(2)
            else:
                reboot_err = "未调度（持久化失败）"
            DPrint(f"[{now_str()}] [/network/set_ip] 后台完成 iface={iface}, ip={ip_iface}, gateway={gateway}, "
                  f"persist_err={persist_err}, reboot_err={reboot_err}")
        except Exception as e:
            DPrint(f"[{now_str()}] [/network/set_ip] 后台任务异常: {e}")

    try:
        t = threading.Thread(target=_task, daemon=True)
        t.start()
        return None
    except Exception as e:
        return f"调度网络变更失败: {e}"

# 提取压缩包中内层升级包
def extract_inner_zip_by_prefix(
    outer_zip_path: Path,
    prefix: str,
    out_dir: Path
) -> Union[Path, None]:
    """
    从总包中提取“文件名以 prefix 开头且以 .zip 结尾”的内层 zip。

    例如：
        prefix='LC'  可匹配 LC.zip / LC2026.zip / LCspc102.zip
        prefix='PCS' 可匹配 PCS.zip / PCS2026.zip

    只提取第一个匹配项。
    """
    prefix_lower = prefix.lower()

    with zipfile.ZipFile(outer_zip_path, 'r') as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue

            # 只取文件名，不取路径
            name = Path(info.filename).name
            name_lower = name.lower()

            if name_lower.startswith(prefix_lower) and (name_lower.endswith('.zip') or name_lower.endswith('.tar')):
                out_dir.mkdir(parents=True, exist_ok=True)

                # 保留原始文件名，比如 LC2026.zip，不强制改成 LC.zip
                safe_inner_name = secure_filename(name) or f"{prefix}.zip"
                dst = out_dir / safe_inner_name

                with zf.open(info) as src, open(dst, 'wb') as f:
                    shutil.copyfileobj(src, f)

                DPrint(f"[UPLOAD] 已从总包中提取: {name} -> {dst}")
                return dst

    return None

# ========== 安全解压 ==========
def _is_within_directory(base_dir: Path, target: Path) -> bool:
    try:
        base = base_dir.resolve()
        tgt = target.resolve()
        return str(tgt).startswith(str(base) + os.sep)
    except Exception:
        return False

def safe_extract(zip_file: zipfile.ZipFile, dest_dir: Path):
    for member in zip_file.infolist():
        member_path = dest_dir / member.filename

        if not _is_within_directory(dest_dir, member_path):
            raise RuntimeError(f"拒绝解压危险路径: {member.filename}")

        if member.is_dir():
            (dest_dir / member.filename).mkdir(parents=True, exist_ok=True)
        else:
            (dest_dir / member.filename).parent.mkdir(parents=True, exist_ok=True)
            with zip_file.open(member) as src, open(dest_dir / member.filename, 'wb') as dst:
                shutil.copyfileobj(src, dst)

def device_to_ip(dev_id: str) -> Optional[str]:
    return DEVICE_IP_MAP.get(dev_id.upper())

def upload_ini_file_async(file, job_id=None):
    # ========== 主线程：同步做参数校验，直接返回HTTP响应 ==========
    safe_name = secure_filename(file.filename) or ''
    if not safe_name:
        return jsonify({
            'taskName': job_id,
            'state': STATE_ERROR,
            'error': 'invalid filename'
        }), 400

    if not safe_name.lower().endswith('.ini'):
        return jsonify({
            'taskName': job_id,
            'state': STATE_ERROR,
            'error': 'has to be a .ini file'
        }), 400

    # ========== 校验通过，启动后台线程执行耗时操作 ==========
    def process():
        try:
            save_path = Path('/home/zlg') / safe_name
            file.save(save_path)

            DPrint(f"[UPLOAD_INI] 文件已保存: {save_path}")
            _write_status(job_id, STATE_DONE, 100, f"[UPLOAD_INI] 文件已保存: {save_path}")
            # 延时重启、写入任务状态
            # schedule_reboot(2)
            restart_sys_service("tems.service", "update_ini")
            restart_sys_service("python_app.service", "update_ini")

        except Exception as e:
            DPrint(f"[UPLOAD]({job_id}) 后台处理异常: {e}")
            _write_status(job_id, STATE_ERROR, 0, f"error:{e}")

    # 后台守护线程执行保存与重启
    threading.Thread(target=process, daemon=True).start()

    # ========== 主线程立刻返回成功JSON给前端 ==========
    return jsonify({
        'taskName': job_id,
        'state': STATE_IN_PROGRESS,
        'msg': 'The file has been received and is being processed asynchronously in the backend.'
    }), 200

def parse_pcs_ip_mapping_from_ini():
    try:
        ini_data = read_ini_all()
        sys_num = _ini_get_int(ini_data, "SYSTEM", "pcsNum", 1)
        pcs_ip_mapping = {}
        for i in range(1, sys_num + 1):
            ip = _ini_get_str(ini_data, "PCS_NETWORK", f"pcs{i}_ip", "")
            if ip:
                pcs_ip_mapping[f"PCS{i}"] = ip
        return pcs_ip_mapping
    except Exception as e:
        DPrint(f"[{now_str()}] 解析 ini 获取 PCS IP 映射异常: {e}")
        return {}

# ============ 升级包校验 =============
def parse_manifest(manifest_path):
    result = {}

    with open(manifest_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for line in lines:

        line = line.strip()

        if not line:
            continue

        if line.startswith("["):
            continue

        if "=" not in line:
            continue

        name, value = line.split("=", 1)

        m = re.search(
            r"CRC32:([0-9A-F]+),SIGN:([0-9a-f]+)",
            value
        )

        if not m:
            continue

        result[name] = {
            "crc": m.group(1),
            "sign": m.group(2)
        }

    return result

def calc_crc32(file_path):
    crc = 0

    with open(file_path, "rb") as f:
        while True:
            data = f.read(8192)

            if not data:
                break

            crc = zlib.crc32(data, crc)

    return f"{crc & 0xFFFFFFFF:08X}"

def make_sign(data: str, key: bytes, mode: str):
    if mode == "CRC32-HMAC":
        return hmac.new(
            key,
            data.encode(),
            hashlib.sha256
        ).hexdigest()

    elif mode == "SHA256":
        return hashlib.sha256(
            (data + key.decode()).encode()
        ).hexdigest()

def verify_upgrade_package(pkg_file, crc_mode: str):
    from routes.route_g3 import SECRET_KEY
    with tempfile.TemporaryDirectory() as tmp:

        tmp = Path(tmp)

        outer_dir = tmp / "outer"
        firmware_dir = tmp / "firmware"

        outer_dir.mkdir()
        firmware_dir.mkdir()

        #
        # 解压 upgrade.zip
        #
        with zipfile.ZipFile(pkg_file, "r") as zf:
            zf.extractall(outer_dir)

        manifest_file = outer_dir / "manifest.ini"

        if not manifest_file.exists():
            raise RuntimeError(
                "缺少manifest.ini"
            )

        #
        # 找 firmware.zip
        #
        firmware_zip = None

        for f in outer_dir.iterdir():
            if f.suffix.lower() in [".zip", ".tar"] \
                    and f.name != "manifest.ini":
                firmware_zip = f
                break
        DPrint("===== firmware_zip =====")
        for f in sorted(outer_dir.rglob("*")):
            DPrint(f.relative_to(outer_dir).as_posix())
    
        DPrint(f"found firmware_zip: {firmware_zip}")
        if firmware_zip is None:
            raise RuntimeError(
                "缺少固件包"
            )
        #
        # 解压 firmware.zip
        #
        DPrint(f"===== 解压固件包 {firmware_zip} =====")
        def _try_extract_tar(path: Path, mode: str):
            with tarfile.open(path, mode) as tf:
                tf.extractall(firmware_dir)

        if zipfile.is_zipfile(firmware_zip):
            with zipfile.ZipFile(firmware_zip, "r") as zf:
                zf.extractall(firmware_dir)
        elif tarfile.is_tarfile(firmware_zip):
            with tarfile.open(firmware_zip, "r:*") as tf:
                tf.extractall(firmware_dir)
        else:
            header = firmware_zip.open("rb").read(6)
            if header.startswith(b"PK"):
                with zipfile.ZipFile(firmware_zip, "r") as zf:
                    zf.extractall(firmware_dir)
            elif header.startswith(b"\x1f\x8b"):
                try:
                    _try_extract_tar(firmware_zip, "r:gz")
                except tarfile.ReadError as e:
                    raise RuntimeError(
                        f"无法解压固件包 {firmware_zip}: {e}"
                    )
            elif header.startswith(b"BZh"):
                try:
                    _try_extract_tar(firmware_zip, "r:bz2")
                except tarfile.ReadError as e:
                    raise RuntimeError(
                        f"无法解压固件包 {firmware_zip}: {e}"
                    )
            elif header.startswith(b"\xfd7zXZ\x00"):
                try:
                    _try_extract_tar(firmware_zip, "r:xz")
                except tarfile.ReadError as e:
                    raise RuntimeError(
                        f"无法解压固件包 {firmware_zip}: {e}"
                    )
            else:
                DPrint("不支持的格式")
                raise RuntimeError(
                    f"不支持格式: {firmware_zip.suffix}, header={header.hex()}"
                )
        DPrint("===== firmware_dir =====")
        for f in sorted(firmware_dir.rglob("*")):
            DPrint(f.relative_to(firmware_dir).as_posix())

        manifest = parse_manifest(
            manifest_file
        )

        #
        # 校验全部文件
        #
        for f in firmware_dir.rglob("*"):

            if not f.is_file():
                continue

            rel = f.relative_to(
                firmware_dir
            ).as_posix()

            if rel not in manifest:
                raise RuntimeError(
                    f"manifest缺少文件: {rel}"
                )

            crc = calc_crc32(f)

            if crc != manifest[rel]["crc"]:
                DPrint(f"文件: {rel}")
                DPrint(f"Expected CRC: {manifest[rel]['crc']}")
                DPrint(f"Actual   CRC: {crc}")
                raise RuntimeError(
                    f"CRC错误: {rel}"
                )

            sign = make_sign(crc, SECRET_KEY, crc_mode)

            if sign != manifest[rel]["sign"]:
                DPrint(f"KEY: {repr(SECRET_KEY)}")
                DPrint(f"文件: {rel}")
                DPrint(f"Expected SIGN: {manifest[rel]['sign']}")
                DPrint(f"Actual   SIGN: {sign}")
                raise RuntimeError(
                    f"SIGN错误: {rel}"
                )

        return True

def _public_param(param: dict) -> dict:
    """
    返回给前端的参数结构。
    valueType 是后端解析用字段，不返回给前端。
    """
    return {
        "name": param["name"],
        "address": param["address"],
        "offset": param["offset"],
        "precision": param["precision"],
        "unit": param["unit"],
    }

def _public_config_param(param: dict) -> dict:
    """
    返回给前端的参数结构。
    valueType 是后端解析用字段，不返回给前端。
    """
    return {
        "moduleName": param["moduleName"],
        "params": param["params"],
    }

def _decode_register_value(registers, value_type: str):
    """
    根据 valueType 解码寄存器原始值。

    支持:
    - uint16
    - int16
    - uint32
    - int32
    """
    value_type = str(value_type or "").strip().lower()
    regs = [int(x) & 0xFFFF for x in registers]

    if value_type == "uint16":
        if len(regs) != 1:
            raise ValueError(f"uint16 需要 1 个寄存器，实际读取到 {len(regs)} 个")
        return regs[0]

    if value_type == "int16":
        if len(regs) != 1:
            raise ValueError(f"int16 需要 1 个寄存器，实际读取到 {len(regs)} 个")
        return _to_signed_16(regs[0])

    if value_type == "uint32":
        return _combine_uint32_big_endian(regs)

    if value_type == "int32":
        return _to_signed_32(_combine_uint32_big_endian(regs))
    
    if value_type == "float":
        combined = _combine_uint32_big_endian(regs)
        return struct.unpack('>f', combined.to_bytes(4, byteorder='big'))[0]

    raise ValueError(f"不支持的数据类型: {value_type}")

def _decode_register_bit_mapping(registers, value_type: str, bit_mapping: int):
    """
    根据 valueType 和 bit_mapping 解码寄存器原始值。

    支持:
    - uint16
    - int16
    - uint32
    - int32
    """
    value_type = str(value_type or "").strip().lower()
    regs = [int(x) & 0xFFFF for x in registers]

    if value_type == "uint16" or value_type == "int16":
        if bit_mapping < 0 or bit_mapping > 15:
            raise ValueError(f"bitMapping 需要在 0-15 之间，实际: {bit_mapping}")
        reg_value = regs[0]
        return (reg_value >> bit_mapping) & 1
    if value_type == "uint32" or value_type == "int32":
        if bit_mapping < 0 or bit_mapping > 31:
            raise ValueError(f"bitMapping 需要在 0-31 之间，实际: {bit_mapping}")
        combined_value = _combine_uint32_big_endian(regs)
        return (combined_value >> bit_mapping) & 1

def _apply_precision(raw_value, precision):
    """
    应用缩放系数。

    实际值 = 原始寄存器值 * precision

    示例:
      raw_value = 1234
      precision = "0.01"
      actual_value = 12.34
    """
    try:
        factor = float(str(precision).strip())
    except Exception:
        factor = 1.0

    value = raw_value * factor

    # precision 为 1 时，返回整数，避免 12.0
    if value == int(value):
        return int(value)
    else:
        # 消除浮点抖动
        value = round(value, 6)
    return value

def _read_param_value(param: dict, functioncode: int = READ_INPUT_REGISTER):
    """
    根据单个参数点表读取实时值。
    """
    name = str(param.get("name", ""))
    address = int(param.get("actual_address",0))
    offset = int(param.get("offset", 1))
    precision = param.get("precision", "1")
    value_type = param.get("valueType", "uint16")
    bit_mapping_raw = param.get("bitMapping")
    bit_mapping = int(bit_mapping_raw) if bit_mapping_raw not in (None, "") else None

    if address == 0:
        address = int(param.get("address",-1))

    if address < 0:
        raise ValueError(f"{name} address 非法: {address}")

    if offset <= 0:
        raise ValueError(f"{name} offset 非法: {offset}")

    if not value_type:
        raise ValueError(f"{name} 缺少 valueType")

    # 设备地址固定为 1。
    # functioncode = 3 表示读取 holding register。
    registers = query_register_data(
        deviceid=FIXED_DEVICE_ID,
        functioncode = functioncode,
        address=address,
        quantity=offset,
    )
    # TEST
    if common.TEST_MODE is True:
        for i in range(len(registers)):
            registers[i] = address + i

    if bit_mapping is not None:
        # bitMapping 解析
        actual_value = _decode_register_bit_mapping(registers, value_type, bit_mapping)
    else:# register解析
        raw_value = _decode_register_value(registers, value_type)
        # TEST 跳过float转换
        if common.TEST_MODE is True and (value_type == "float"):
            raw_value = float(registers[0])
        actual_value = _apply_precision(raw_value, precision)
    if address == 2703:
        DPrint(f'address:{address}, precision:{precision}, actual_value: {actual_value}')

    return actual_value

def _read_ini_value(params: dict):
    param = params.copy()
    # 获取参数字符串
    param_name = param.get("name")
    # 按点分割层级
    name_parts = param_name.split(".")
    # 提取section和key
    section = name_parts[-2]
    key = name_parts[-1]
    # 将section、key、原始参数名存入列表（可按需调整存储结构）
    item = {
        "section": section,
        "key": key,
        "param_name": param_name
    }
    ini_data = read_ini_all()
    if item.get("key") == "pcs_brand":
        CODE_TO_BRAND = {v: k for k, v in PCS_BRAND.items()}
        pcs_num = _ini_get_int(ini_data, "SYSTEM", "pcsNum", 1)
        brand_list = []
        for i in range(pcs_num):
            item["key"] = f"pcs{i + 1}_brand"
            brand = _ini_get_int(ini_data, item.get("section"), item.get("key"), -1)
            brand_name = CODE_TO_BRAND.get(brand)
            brand_list.append(brand_name)
        # 校验PCS品牌是否一致
        first_brand = brand_list[0]
        for b in brand_list:
            if b != first_brand:
                raise ValueError(f"多台PCS品牌不统一,品牌列表: {brand_list}")
        param_value = first_brand
    elif item.get("key") == "bms_brand":
        CODE_TO_BRAND = {v: k for k, v in BMS_BRAND.items()}
        bms_num = _ini_get_int(ini_data, "SYSTEM", "bmsNum", 1)
        brand_list = []
        for i in range(bms_num):
            item["key"] = f"bms{i + 1}_brand"
            brand = _ini_get_int(ini_data, item.get("section"), item.get("key"), -1)
            brand_name = CODE_TO_BRAND.get(brand)
            brand_list.append(brand_name)
        # 校验PCS品牌是否一致
        first_brand = brand_list[0]
        for b in brand_list:
            if b != first_brand:
                raise ValueError(f"多台BMS品牌不统一,品牌列表: {brand_list}")
        param_value = first_brand
    elif key.endswith(("ip", "netmask", "gateway")):
        param_value = _ini_get_str(ini_data, item.get("section"), item.get("key"))
    else:
        param_value = _ini_get_int(ini_data, item.get("section"), item.get("key"), None)
        if param_value is None:
            DPrint(f"未找到param_value,请检查ini文件是否存在该参数: {item}")
    return param_value

def _write_ini_value(params: dict, write_val):
    """
    写入ini配置参数
    :param params: 原始参数字典，含name字段如 device.pcs.PCS_NETWORK.pcs1_ip
    :param write_val: 需要写入的值（字符串/数字/品牌名称）
    :return: None
    """
    param = params.copy()
    param_name = param.get("name")
    name_parts = param_name.split(".")
    # 拆分section、key
    section = name_parts[-2]
    key = name_parts[-1]
    item = {
        "section": section,
        "key": key,
        "param_name": param_name
    }
    ini_data = read_ini_all()

    # 1. 批量统一写入所有PCS品牌
    if item.get("key") == "pcs_brand":
        BRAND_TO_CODE = {k: v for k, v in PCS_BRAND.items()}
        # 传入的write_val是品牌名称，转数字编码
        target_code = BRAND_TO_CODE.get(write_val)
        if target_code is None:
            DPrint(f"不支持的PCS品牌名称: {write_val}, 可选：{list(BRAND_TO_CODE.keys())}")
            raise ValueError(f"不支持的PCS品牌名称: {write_val}, 可选：{list(BRAND_TO_CODE.keys())}")

        pcs_num = _ini_get_int(ini_data, "SYSTEM", "pcsNum", 1)
        # 循环全部pcs，统一写入相同品牌编码
        for i in range(pcs_num):
            write_key = f"pcs{i + 1}_brand"
            _write_ini(ini_data, section, write_key, str(target_code))
            DPrint(f"write {write_val} : {target_code} to section:{section} --key:{write_key} succeed")
        return

    # 2. 批量统一写入所有BMS品牌
    elif item.get("key") == "bms_brand":
        BRAND_TO_CODE = {k: v for k, v in BMS_BRAND.items()}
        target_code = BRAND_TO_CODE.get(write_val)
        if target_code is None:
            DPrint(f"不支持的BMS品牌名称: {write_val}, 可选：{list(BRAND_TO_CODE.keys())}")
            raise ValueError(f"不支持的BMS品牌名称: {write_val}, 可选：{list(BRAND_TO_CODE.keys())}")

        bms_num = _ini_get_int(ini_data, "SYSTEM", "bmsNum", 1)
        for i in range(bms_num):
            write_key = f"bms{i + 1}_brand"
            _write_ini(ini_data, section, write_key, str(target_code))
            DPrint(f"write {write_val} : {target_code} to section:{section} --key:{write_key} succeed")
        return

    # 3. IP、子网掩码、网关等字符串类型参数
    elif key.endswith(("ip", "netmask", "gateway")):
        _write_ini(ini_data, section, key, str(write_val))
        DPrint(f"write {write_val} to section:{section} --key:{key} succeed")
        return

    # 4. 普通数字参数
    else:
        # 校验是否为合法数字
        try:
            num_val = int(write_val)
        except ValueError:
            DPrint(f"参数{key}必须传入整数，当前输入：{write_val}")
            raise ValueError(f"参数{key}必须传入整数，当前输入：{write_val}")
        _write_ini(ini_data, section, key, str(num_val))
        DPrint(f"write {num_val} to section:{section} --key:{key} succeed")
        return

def _build_params_list_for_data_type(base_params_list: list, data_type: str, data_group: int, data_step: int):

    params_list = []
    if data_type == "device-pcs-slave":
        for i in range(data_group):
            for param in base_params_list:
                new_param = dict(param)
                if new_param.get("bitMapping"):
                    new_param["bitMapping"] = int(new_param["bitMapping"]) + i * 2 + 1
                else:
                    new_param["actual_address"] = int(new_param["address"]) + data_step * i + common.PCS_FAULT_STEP
                params_list.append(new_param)
    elif data_type == "device-pcs-master":
        for i in range(data_group):
            for param in base_params_list:
                new_param = dict(param)
                if new_param.get("bitMapping"):
                    new_param["bitMapping"] = int(new_param["bitMapping"]) + i * 2
                else:
                    new_param["actual_address"] = int(new_param["address"]) + data_step * i
                params_list.append(new_param)
    else:
        for i in range(data_group):
            for param in base_params_list:
                new_param = dict(param)
                if new_param.get("bitMapping"):
                    new_param["bitMapping"] = int(new_param["bitMapping"]) + i
                else:
                    new_param["actual_address"] = int(new_param["address"]) + data_step * i
                params_list.append(new_param)

    return params_list

def query_device_alarm_data(check_list, device_num, data_gap, device_reg_list, data_type = "BMS"):
    """
    查询 BMS/PCS 告警/故障数据
    """

    alarm_list = []
    alarm_triggered_count = 0
    alarm_untriggered_count = 0

    # fault / warning
    check_types = {
        "fault": check_list.get("fault", []),
        "warning": check_list.get("warning", []),
    }

    for device_index in range(1, device_num + 1):
        if data_type == "device-pcs-slave":
            base_offset = (device_index - 1) * data_gap + common.PCS_FAULT_STEP
        else:
            base_offset = (device_index - 1) * data_gap
        # 构建当前设备的寄存器映射
        reg_map = {
            reg.get("address") + base_offset: reg
            for reg in device_reg_list
        }
        for regtype, addr_list in check_types.items():
            for register_addr in addr_list:
                address = register_addr + base_offset
                try:
                    registers = query_register_data(FIXED_DEVICE_ID, READ_INPUT_REGISTER, address, 1)
                    # TEST
                    if common.TEST_MODE is True:
                        for i in range(len(registers)):
                            registers[i] = address + i
                    if not registers:
                        DPrint(f"地址 {address} 读取失败")
                        continue
                    register_value = int(registers[0]) & 0xFFFF

                except Exception as e:
                    DPrint(f"地址 {address} 读取异常: {e}")
                    continue

                # 获取寄存器名称
                dataName = reg_map.get(address, {}).get("name", f"Reg_{address}")
                # bit 映射表
                bit_mapping = FAULT_TABLE_ALL.get(register_addr, {})
                for bit_index, alarm_info in bit_mapping.items():
                    alarmName = alarm_info if alarm_info else "未知告警/故障"
                    if (register_value >> bit_index) & 1:
                        current_time = now_str()
                        alarm_list.append({
                            "time": current_time,
                            "dataName": dataName,
                            "alarmName": alarmName,
                            "type": regtype,
                            "area": str(device_index),
                        })
                        alarm_triggered_count += 1
                        DPrint(f"[{current_time}] "f"[{regtype.upper()}] "f"{device_index} - "f"{dataName} - "f"{alarmName} 触发")
                    else:
                        alarm_untriggered_count += 1

    total = alarm_triggered_count + alarm_untriggered_count
    DPrint(f"[{now_str()}] "f"[告警/故障统计] "f"总触发点位: {alarm_triggered_count}, "f"未触发点位: {alarm_untriggered_count}, "f"总点位数: {total}")

    return alarm_list

def makeFaultListFromMysqlHistoryReg(register_row, time_str, device_type="BMS", reg_addr = 1, reg_offset = 100, reg_num = 1):
    """
    根据MySQL中的历史故障寄存器值生成 fault_list 条目。

    参数:
        register_row: query_fault_poschange 返回的单条注册寄存器行。
        time_str: 该故障记录的时间字符串。
        device_type: 发生故障的设备类型，PCS/MV/BMS。

    返回:
        fault_list: 解析后的历史故障条目列表。
    """
    fault_list = []
    if (register_row is None) and (common.TEST_MODE is False):
        return fault_list

    # SQLAlchemy Row类型
    if hasattr(register_row, "_mapping"):
        row_dict = dict(register_row._mapping)
    else:
        try:
            row_dict = dict(register_row)
        except Exception:
            row_dict = {}

    for index in range(reg_num):
        reg_index = reg_addr + index * reg_offset
        column_name = f"Input{reg_index}"
        if column_name not in row_dict:
            continue

        register_value = int(row_dict.get(column_name, 0) or 0) & 0xFFFF

        # TEST 模式下，模拟寄存器值为地址值
        if common.TEST_MODE is True:
            register_value = reg_index

        if register_value == 0:
            continue
        DPrint(f"register_value: {register_value}, bin: {bin(register_value)}")
        # 填充content,各自寄存器的list
        # 无点位故障寄存器
        nobit_mv_start = MV_MC_Trip_Summary_ADDRESS + index * reg_offset
        nobit_mv_end   = MV_MC_PCS_FAULT4_BASE_ADDRESS + index * reg_offset
        if (nobit_mv_start <= reg_index <= nobit_mv_end):
            if register_value > 0:
                # 查故障定义
                fault_content = (FAULT_TABLE_ALL.get(reg_addr))
                # 找不到定义时给默认描述
                if not fault_content:
                    fault_content = f"{column_name} 触发"
                DPrint(f"find a fault_pos:{fault_content}")
                fault_list.append({
                    "deviceType": device_type,
                    "deviceNum": index + 1,
                    "time": time_str,
                    "content": fault_content
                })
                continue
        else:
            reg_map = {}        
            reg_list = ALL_REG_LIST.get(DEVICE_TYPE.get(device_type), [])
            # 相同设备类型的设备,在MySQL存储的字段不变,比如bms1和bms2都是用"Input2600、Input2601.."等字段存储的
            for reg in reg_list:
                addr = reg.get("address")
                # 适配lc_data字段规则,32位数据用第二个字的地址命名
                if reg.get("offset") == 2:
                    addr += 1
                reg_map[addr] = reg
            # 有点位故障寄存器
            for bit_index in range(DEFINE_16BIT):
                if (register_value >> bit_index) & 1:
                    # 查故障定义
                    fault_content = (FAULT_TABLE_ALL.get(reg_addr, {}).get(bit_index))
                    # 找不到定义时给默认描述
                    if not fault_content:
                        fault_content = f"{column_name} 位{bit_index} 触发"
                    DPrint(f"find a fault_pos:{fault_content}")
                    fault_list.append({
                        "deviceType": device_type,
                        "deviceNum": index + 1,
                        "time": time_str,
                        "faultType": reg_map.get(reg_addr, {}).get("name", f"Reg_{reg_addr}"),
                        "content": fault_content
                    })

    return fault_list

def CheckFaultFromRows(rows):

    pcs_fault = False
    mv_fault = False
    bms_fault = False

    if rows is None:
        return -1

    rows_list = list(rows)

    for row in rows_list:
        if (row.pcsModel or 0) > 0:
            pcs_fault = True

        if (row.Mv or 0) > 0:
            mv_fault = True

        if (row.bms or 0) > 0:
            bms_fault = True

    return (pcs_fault, mv_fault, bms_fault)

# 请求MySQL故障统计寄存器
def query_fault_list(table_name, begin_dt, end_dt, offset, page_size):
    """
    查询故障列表数据
    
    参数:
        table_name: 表名，如 'fault20260508'
        begin_dt: 开始时间
        end_dt: 结束时间
        offset: 分页偏移
        page_size: 每页大小
    
    返回:
        查询结果的行对象列表
    """
    with config.engine.connect() as conn:
        data_query = text(f"""
            SELECT Time, pcsModel, Mv, bms
            FROM {table_name}
            WHERE Time >= :begin_dt AND Time <= :end_dt
            AND (pcsModel > 0 OR Mv > 0 OR bms > 0)
            ORDER BY Time DESC
            LIMIT :offset, :page_size
        """)
        rows = conn.execute(data_query, {
            "begin_dt": begin_dt,
            "end_dt": end_dt,
            "offset": offset,
            "page_size": page_size
        }).fetchall()
    DPrint(data_query)
    DPrint("rows count:", len(rows))
    if rows is None:
        DPrint("rows is None!")
    else:
        for row in rows:
            DPrint(dict(row._mapping))
    return rows

# 请求MySQL故障日志
def query_fault_poschange(table_name,begin_dt,end_dt,offset,page_size,reg_addrs,reg_offset,reg_num):
    """
    查询故障变位数据
#     参数:
#         table_name: 表名，如 'fault20260508'
#         begin_dt: 开始时间
#         end_dt: 结束时间
#         offset: 分页偏移
#         page_size: 每页大小
#         reg_addrs: 地址集合
#         reg_offset: 设备寄存器固定偏移
#         reg_num: 设备数量
#     返回:
#         查询结果的行对象列表
    """

    # =========================
    # 计算偏移寄存器
    # =========================
    reg_names = []
    for i in range(reg_num):
        for addr in reg_addrs:
            reg_name = f"Input{addr + i * reg_offset}"
            reg_names.append(reg_name)

    reg_name = ", ".join(reg_names)

    # =========================
    # SQL查询,PCS、MV、BMS
    # =========================
    with config.engine.connect() as conn:
        data_query = text(f"""
            SELECT {reg_name}
            FROM {table_name}
            WHERE Time >= :begin_dt AND Time <= :end_dt
            AND (pcsModel > 0 OR Mv > 0 OR bms > 0)
            ORDER BY Time DESC
            LIMIT :offset, :page_size
        """)

        rows = conn.execute(data_query, {
            "begin_dt": begin_dt,
            "end_dt": end_dt,
            "offset": offset,
            "page_size": page_size
        }).fetchall()

        return rows

# 请求MySQL设备数据日志
def query_device_mysqldata(table_name,begin_dt,end_dt,offset,page_size,sort):
    """
    查询故障变位数据
#     参数:
#         table_name: 表名，如 'pcsmodel20260508'
#         begin_dt: 开始时间
#         end_dt: 结束时间
#         offset: 分页偏移
#         page_size: 每页大小
#         sort: 设备编号,从0开始

#     返回:
#         查询结果的行对象列表
    """

    # =========================
    # SQL查询指定编号的设备
    # =========================
    with config.engine.connect() as conn:
        data_query = text(f"""
            SELECT *
            FROM {table_name}
            WHERE Time >= :begin_dt AND Time <= :end_dt
            AND Num = :sort
            ORDER BY Time DESC
            LIMIT :offset, :page_size
        """)
        DPrint(data_query)
        rows = conn.execute(data_query, {
            "begin_dt": begin_dt,
            "end_dt": end_dt,
            "sort": sort,
            "offset": offset,
            "page_size": page_size
        }).fetchall()

        return rows

# 请求sqlite数据库录波数据
def query_device_sqlitedata(db_path, table_name, begin_dt = None, end_dt = None, record_id = None):
    """
    查询SQLite故障变位数据

    参数:
        db_path: sqlite数据库文件路径
        table_name: 表名
        begin_dt: 开始时间
        end_dt: 结束时间
        record_id: 录波数据ID(唯一)
    返回:
        查询结果列表
    """
    if not re.match(r'^\w+$', table_name):
        raise ValueError("非法表名")

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            # 时间查询
            if begin_dt is not None and end_dt is not None:
                sql = f"""
                    SELECT id, faultCodeOccurDate
                    FROM {table_name}
                    WHERE faultCodeOccurDate >= :begin_dt
                    AND faultCodeOccurDate <= :end_dt
                    ORDER BY faultCodeOccurDate DESC
                """
                cur.execute(sql, {
                    "begin_dt": begin_dt,
                    "end_dt": end_dt
                })
                return cur.fetchall()
            # ID查询
            elif record_id is not None:
                sql = f"""
                    SELECT *
                    FROM {table_name}
                    WHERE id = :record_id
                """
                cur.execute(sql, {
                    "record_id": record_id
                })
                return cur.fetchone()
            else:
                raise ValueError("查询参数错误")

    except Exception as e:
        DPrint(f"query_device_sqlitedata error: {e}")
        return []

# 解析faultCode字段数据
def _getFaultCodeList(rows):
    num = 0
    _list = []
    for num in range(5):
        for word in SQL_TABLE_WORD:
            fault_code = rows[f"{word}{num+1}"]
            _list.append(fault_code)
    return _list

# 解析data字段数据,2字节,大端模式,int16
def _getFaultDataList(rows):
    num = 0
    seq = 0
    _list = []
    for num in range(24):
        data_group = []
        seq = num + 1
        sql_data = rows[f"data{seq}"]
        list_data = list(sql_data)
        for index in range(len(list_data) // 2):
            val = struct.unpack('<h',  bytes([list_data[2 * index], list_data[2 * index + 1]]))[0]
            data_group.append(val)
        if num == 0:
            DPrint(f"wave{seq} size:", len(data_group))
        _list.append({f"data{seq}":data_group})
    return _list

# 写入模拟数据
def fill_simudata2mysql(table_name, timestr):
    with config.engine.connect() as conn:
        insert_query = text(f"""
            INSERT INTO {table_name} (Time, pcsModel, Mv, bms)
            VALUES (:time, :pcsModel, :Mv, :bms)
        """)
        conn.execute(insert_query, {
            "time": timestr,
            "pcsModel": 1,
            "Mv": 1,
            "bms": 1
        })
        conn.commit()

# ========== 设备选择解析与映射 ==========
def parse_targets(raw: Optional[str]) -> List[str]:
    if not raw:
        return []

    out = int(raw.strip())
    out_str = FIRMWARE_CATEGORY.get(out, "")

    return out_str

# ========== 状态存取 ==========
def _write_status(job: str, state: int, percentage: int, msg: str = ''):
    """落地状态到 /home/zlg/upgrade/status/<job>.json （原子替换）"""
    rec = {
        'job': job,
        'state': int(state),
        'progress': int(percentage),
        'msg': str(msg)[:256],
        'ts': datetime.now().isoformat()
    }
    os.makedirs(STATUS_DIR, exist_ok=True) 
    path = STATUS_DIR / f'{job}.json'
    tmp = STATUS_DIR / f'.{job}.json.tmp'

    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(rec, f, ensure_ascii=False)

    os.replace(tmp, path)

def read_status(job: str):

    path = STATUS_DIR / f"{job}.json"

    if not path.exists():
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {
            "job": job,
            "state": -1,
            "progress": 0,
            "msg": f"读取状态失败: {e}",
            "ts": ""
        }
    
def init_addr_config_cache():
    global ADDR_CONFIG_CACHE
    ADDR_CONFIG_CACHE.clear()
    cache = {}
    for group_cfg in CONFIG_PARAMS_BY_DATA_TYPE.values():
        for module in group_cfg:
            params = module.get("params", {})
            for param_group in params.values():
                if not isinstance(param_group, list):
                    continue
                for item in param_group:
                    addr = item.get("address")
                    if addr is None:
                        continue
                    name = str(item.get("name", "unknow"))
                    prec = float(item.get("precision", "1"))
                    val_type = item.get("valueType", "uint16")
                    min_phy = float(item.get("minValue", "-99999"))
                    max_phy = float(item.get("maxValue", "99999"))
                    cache[addr] = {
                        "name": name,
                        "precision": prec,
                        "valueType": val_type,
                        "min": min_phy,
                        "max": max_phy
                    }
    ADDR_CONFIG_CACHE = cache

def get_addr_config(target_addr: int):
    default_cfg = {
        "name": "unknow",
        "precision": 1.0,
        "valueType": "uint16",
        "min": -99999,
        "max": 99999
    }
    return ADDR_CONFIG_CACHE.get(target_addr, default_cfg)

def md5_password(password, salt):
    """
    MD5加盐
    """
    data = password + salt
    return hashlib.md5(
        data.encode("utf-8")
    ).hexdigest()


def generate_salt():
    """
    生成随机salt
    """
    return secrets.token_hex(16)

def ensure_permission_table() -> None:
    """
    确保 Permission_Management 表存在；不存在则创建并写入默认用户。
    表结构:
      username VARCHAR(64) 主键
      password VARCHAR(128)
      permission TINYINT (1-4)
      first_login TINYINT (0/1)
    """
    salt = generate_salt()
    password_hash = md5_password(config.DEFAULT_PASSWORD, salt)
    create_sql = f"""
    CREATE TABLE IF NOT EXISTS `{PERM_TABLE}` (
        `username` VARCHAR(64) NOT NULL,
        `password` VARCHAR(128) NOT NULL,
        `salt` VARCHAR(128) NOT NULL,
        `permission` TINYINT NOT NULL,
        `first_login` TINYINT NOT NULL,
        `password_created_at` DATETIME NULL,
        `password_expire_at` DATETIME NULL,
        `last_notify_at` DATETIME NULL,
        PRIMARY KEY (`username`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """
    default_user = {
        "username": "trinastorage",
        "password": password_hash,
        "salt": salt,
        "permission": 4,
        "first_login": 0,
    }
    with config.engine.begin() as conn:
        conn.execute(text(create_sql))
        row = conn.execute(
            text(f"SELECT 1 FROM `{PERM_TABLE}` WHERE username=:username LIMIT 1"),
            {"username": default_user["username"]},
        ).fetchone()
        if row is None:
            conn.execute(
                text(
                    f"INSERT INTO `{PERM_TABLE}` (username, password, salt, permission, first_login) "
                    f"VALUES (:username, :password, :salt, :permission, :first_login)"
                ),
                default_user,
            )

def _getlevel_permission_table(username: str):
    try:
        with config.engine.begin() as conn:
            if not _perm_table_exists(conn):
                raise ValueError({"ok": False, "error": "Permission table does not exist"})
            row = conn.execute(
                text(f"SELECT permission FROM `{PERM_TABLE}` WHERE username=:username LIMIT 1"),
                {"username": username},
            ).fetchone()
            DPrint(f"username: {username}, table info: {row}")
            if row is None:
                return None
            else:
                return row[0]

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

def init_permission_table():
    # region agent log
    debug_log(
        "H1",
        "app.py:init_permission_table",
        "starting permission table init",
        {
            "host_ip": config.HOST_IP,
            "db_host": config.DB_HOST,
            "db_port": config.DB_PORT,
            "db_name": config.DB_NAME,
            "db_user": config.DB_USER,
            "platform": sys.platform,
        },
    )
    # endregion
    try:
        ensure_permission_table()
        DPrint(f"[{now_str()}] [INIT] Permission table ready: {PERM_TABLE}")
    except Exception as e:
        # region agent log
        debug_log(
            "H1",
            "app.py:init_permission_table:except",
            "permission table init failed",
            {"error": str(e), "host_ip": HOST_IP},
        )
        # endregion
        DPrint(f"[{now_str()}] [INIT] Permission table init failed: {e}")

def ensure_remote_connected(context: str = "") -> bool:
    if remote_client.is_socket_open():
        return True
    ok = remote_client.connect()
    if not ok:
        DPrint(f"[{now_str()}] [REMOTE] connect failed ({context})")
        return False
    DPrint(f"[{now_str()}] [REMOTE] connected ({context})")
    return True

def write_register_with_retry(write_address: int, write_value: int, slave: int = 1):
    """
    下发寄存器值,单次失败重连下发
    """
    with remote_client_lock:
        if not ensure_remote_connected("write_register"):
            raise RuntimeError("remote not connected")

        result = remote_client.write_register(write_address, write_value, slave=slave)
        if result is not None and (not result.isError()):
            return result, 1

        DPrint(f"[{now_str()}] [REMOTE] 下发寄存器: addr={write_address}, result={result}")
        remote_client.close()
        if not ensure_remote_connected("write_register_retry"):
            raise RuntimeError("remote reconnect failed")

        result2 = remote_client.write_register(write_address, write_value, slave=slave)
        return result2, 2

def _physical_to_register(physical_val: int, addr_cfg: dict) -> int:
    prec = addr_cfg["precision"]
    vtype = addr_cfg["valueType"]
    min_phy = addr_cfg["min"]
    max_phy = addr_cfg["max"]

    # 1. 校验物理值范围
    if not (min_phy <= physical_val <= max_phy):
        raise ValueError(f"输入值超出配置范围，区间[{min_phy}, {max_phy}]，输入：{physical_val}")

    # 2. 物理值 / 精度 得到寄存器原始整数
    # raw_reg = round(physical_val / prec)

    # 3. 根据寄存器类型截断溢出
    # if vtype == "int16":
    #     raw_reg = max(-32768, min(32767, raw_reg))
    # elif vtype == "uint16":
    #     raw_reg = max(0, min(65535, raw_reg))
    return physical_val

def _trans_to_modbus_value(write_address: int, write_value: int):
    target_item = get_addr_config(write_address)
    return _physical_to_register(write_value, target_item)

def query_register_data(deviceid, functioncode, address, quantity):
    if functioncode == 3:
        return [registers_model.get_hold(address + j) for j in range(quantity)]
    else:
        return [registers_model.get_input(address + j) for j in range(quantity)]

def query_rank_register_data(bank_index, functioncode, address, quantity):
    if functioncode == 3:
        return [rank_model.get_r_hold(bank_index, address + j) for j in range(quantity)]
    else:
        return [rank_model.get_r_input(bank_index, address + j) for j in range(quantity)]

# 内部生成list接口
def GenerateList():

    ini_data = read_ini_all()
    sys_num = _ini_get_int(ini_data, "SYSTEM", "sysNum", 1)
    pcs_num = _ini_get_int(ini_data, "SYSTEM", "pcsNum", 0)
    bms_num = _ini_get_int(ini_data, "SYSTEM", "bmsNum", 0)

    if sys_num < 0 or pcs_num < 0 or bms_num < 0:
        return None

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
            PCS_BRAND["G3_SELF"]
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

    DPrint(device_list)

    return device_list

ini_param()
init_permission_table()
init_addr_config_cache()
device_info.DEVICE_MAP = GenerateList()
DPrint("===============配置参数缓存区映射完毕===============")
