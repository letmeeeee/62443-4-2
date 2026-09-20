#!/usr/bin/env python3
import configparser, os, socket
from typing import Optional
from pathlib import Path
from config import INI_PATH
import config
from constent.device_info import PCS_BRAND, DEVICE_TYPE, DEVICE_MAP
from sqlalchemy import create_engine
import constent.device_info as device_info
import utils.operationLog as operationLog

def _ini_get_int(ini_data: dict, section: str, key: str, default: int = 0) -> int:
    """
    从 read_ini_all() 返回的 dict 中安全读取整数。
    """
    try:
        return int(ini_data.get(section, {}).get(key, default))
    except Exception:
        return default

def _ini_get_str(ini_data: dict, section: str, key: str, default: str = "") -> str:
    """
    从 read_ini_all() 返回的 dict 中安全读取字符串。
    """
    try:
        value = ini_data.get(section, {}).get(key, default)

        # 防止返回 None
        if value is None:
            return default

        return str(value)

    except Exception:
        return default

def _get_pcs_device_type_by_brand(brand: int):
    """
    根据 pcs*_brand 判断 PCS GROUP / PCS 的 deviceType。

    品牌映射:
    - pcs*_brand = 6：G2-PCS，台达PCS
    - pcs*_brand = 2：G3-PCS，自研PCS

    返回:
    (group_device_type, pcs_device_type)
    """
    if brand == PCS_BRAND["G2_DELTA"]:
        return DEVICE_TYPE["G2_PCS_GROUP"], DEVICE_TYPE["G2_PCS"]

    if brand == PCS_BRAND["G3_SELF"]:
        return DEVICE_TYPE["G3_PCS_GROUP"], DEVICE_TYPE["G3_PCS"]

    # 未识别品牌时，默认按 G2 台达PCS 处理
    return DEVICE_TYPE["G2_PCS_GROUP"], DEVICE_TYPE["G2_PCS"]

# ================== 读取ini文件 ==================
def get_ini_path() -> Path:
    """
    解析 ini 路径：优先使用环境变量/默认值；如不存在，回退到脚本同目录的 lc_data_set.ini。
    """
    if INI_PATH.is_file():
        return INI_PATH
    local_path = Path(__file__).with_name("lc_data_set.ini")
    if local_path.is_file():
        return local_path
    return INI_PATH

def read_ini_system_counts(path: Optional[Path] = None):
    path = Path(path) if path else get_ini_path()
    if not path.is_file():
        raise FileNotFoundError(f"ini 不存在: {path}")

    cfg = configparser.ConfigParser()
    cfg.optionxform = str  # 选项名保留大小写，便于与文件一致
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        cfg.read_file(f)

    sec = "SYSTEM" if "SYSTEM" in cfg else ("system" if "system" in cfg else None)
    if sec is None:
        raise KeyError("缺少 [SYSTEM] 段")

    def _get_int(name):
        if cfg.has_option(sec, name):
            return cfg.getint(sec, name)
        if cfg.has_option(sec, name.lower()):
            return cfg.getint(sec, name.lower())
        raise KeyError(f"[{sec}] 缺少字段: {name}")

    bms_num = _get_int("bmsNum")
    pcs_num = _get_int("pcsNum")
    return {"bmsNum": bms_num, "pcsNum": pcs_num}

def read_ini_all(path: Optional[Path] = None):
    path = Path(path) if path else get_ini_path()
    if not path.is_file():
        raise FileNotFoundError(f"ini 不存在: {path}")

    cfg = configparser.ConfigParser()
    cfg.optionxform = str
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        cfg.read_file(f)

    data = {}
    for sec in cfg.sections():
        data[sec] = {k: v for k, v in cfg.items(sec)}
    return data

def _write_ini(ini_data: dict, section: str, key: str, value: str):
    """
    写入ini内存字典并保存文件
    :param ini_data: read_ini_all读取的内存ini字典
    :param section: 分区名
    :param key: 参数key
    :param value: 待写入字符串值
    """
    # 分区不存在则新建
    if section not in ini_data:
        raise RuntimeError(f"ConfigFile not found the section {section}")
    # 赋值内存
    ini_data[section][key] = value

    # 持久化写入ini文件
    cfg = configparser.ConfigParser()
    cfg.optionxform = str
    # 回填所有分区数据
    for sec, items in ini_data.items():
        cfg[sec] = items
    # 保存文件，替换为你的ini实际路径
    with open("lc_data_set.ini", "w", encoding="utf-8") as f:
        cfg.write(f)

def find_device(device_id):
    return next(
        (item for item in device_info.DEVICE_MAP if item.get("id") == device_id),
        None
    )

def getPcsIP_ini():
    ini_data = read_ini_all()
    IP1 = _ini_get_str(ini_data, "PCS_NETWORK", "pcs1_ip", None)
    IP2 = _ini_get_str(ini_data, "PCS_NETWORK", "pcs2_ip", None)
    IP3 = _ini_get_str(ini_data, "PCS_NETWORK", "pcs3_ip", None)
    IP4 = _ini_get_str(ini_data, "PCS_NETWORK", "pcs4_ip", None)
    return [IP1, IP2, IP3, IP4]

def getPcsPort_ini():
    ini_data = read_ini_all()
    port1 = _ini_get_str(ini_data, "PCS_NETWORK", "pcs1_port", None)
    port2 = _ini_get_str(ini_data, "PCS_NETWORK", "pcs2_port", None)
    port3 = _ini_get_str(ini_data, "PCS_NETWORK", "pcs3_port", None)
    port4 = _ini_get_str(ini_data, "PCS_NETWORK", "pcs4_port", None)
    return [port1, port2, port3, port4]

def get_local_ip():
    env_ip = os.environ.get("APP_HOST", "").strip()
    if env_ip:
        return env_ip
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"

def ini_param():
    config.HOST_IP = get_local_ip()
    config.REMOTE_IPS = getPcsIP_ini()
    config.REMOTE_PORTS = getPcsPort_ini()
    config.DB_HOST = os.environ.get("DB_HOST", config.HOST_IP).strip() or config.HOST_IP
    config.DB_PORT = int(os.environ.get("DB_PORT", "3306"))
    config.DB_USER = os.environ.get("DB_USER", "root")
    config.DB_PASSWORD = os.environ.get("DB_PASSWORD", "qwer1234")
    config.DB_NAME = os.environ.get("DB_NAME", "log_db")
    config.engine = create_engine(
        f'mysql+pymysql://{config.DB_USER}:{config.DB_PASSWORD}@{config.DB_HOST}:{config.DB_PORT}/{config.DB_NAME}',
        pool_pre_ping=True,
        pool_recycle=3600
    )
    operationLog.create_operation_log_table()
    operationLog.start_operation_log_worker()
