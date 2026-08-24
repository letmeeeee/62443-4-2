#!/usr/bin/env python3
import os, threading
from pathlib import Path
from pymodbus.client import ModbusTcpClient

SAVE_LOG = True    # 是否写入日志文件
RETENTION_DAYS = 30
LOG_FILE = Path("/mnt/nvme/applog")  # 日志文件路径
LOG_FILE.mkdir(parents=True, exist_ok=True)

# ================== 基础初始化 ==================
INI_PATH = Path(os.environ.get("LC_INI_PATH", "/home/zlg/lc_data_set.ini"))
HOST_IP = None
#remote_client = ModbusTcpClient(HOST_IP, port=1502, keep_alive=True)
remote_client = ModbusTcpClient(HOST_IP, port=1502)
remote_client_lock = threading.Lock()
FIXED_DEVICE_ID = 1
READ_HOLD_REGISTER = 3
READ_INPUT_REGISTER = 4
DB_HOST = None
DB_PORT = None
DB_USER = None
DB_PASSWORD = None
DB_NAME = None
DEFINE_16BIT = 16
DEFINE_BIT = 1
# ======================
# SCP录波配置
# ======================
# 远端装置信息
REMOTE_IPS = []    # PCS IP
REMOTE_PORTS = []  # PCS PORT
REMOTE_IPS = None
REMOTE_PORTS = None
REMOTE_PORT = 22               # SSH端口（默认22）
REMOTE_USERNAME = "root"              # 账号
REMOTE_PASSWORD = "1"            # 密码
REMOTE_PASSWORD_TEST = "root"            # TEST密码
# 远端录波DB文件路径（绝对路径）
REMOTE_DB_FILE = "/home/root/data/database/fault_wave.db"
# 本地保存路径（完整文件名）
LOCAL_SAVE_PATH = "/home/data/database/pcs/fault_wave.db"
p = Path(LOCAL_SAVE_PATH)
p.parent.mkdir(parents=True, exist_ok=True)
SQL_TABLE_NAME = "fault_wave"
SQL_TABLE_WORD = ["msFaultCode", "j1FaultCode", "j2FaultCode"]

# ======================
# 权限配置
# ======================
PERMISSION_MAPPING_TABLE = {
    1:"visitor",
    2:"Qualified_user",
    3:"Trina_employee",
    4:"Trina_R&D",
    None:"unknown user"
}
PERMISSION_TABLE = {
    "data":[1,2,3,4], #All
    "param":[2,3,4],  #not visitor
    "upgrade":[3,4],  #not user and visitor
    "usermanage":[4]
}

# 本地update保存文件路径
# UPLOAD_DIR = Path("/tmp/upgrade")
# UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
# 固件类型映射
FIRMWARE_CATEGORY = {
    1: "config-file",
    2: "lc",
    3: "pcs-g2",
    4: "pcs-g3",
    5: "reserved"
}

"""
状态约定：
  0: received / start（已接收，准备升级）
  1: in_progress（升级进行中）
  2: done（升级完成）
  3: rebooting（重启中）
 -1: error（错误）
"""

STATE_IDLE = 0
STATE_IN_PROGRESS = 1
STATE_FAILED = 2
STATE_DONE = 3
STATE_ERROR = -1

# 升级枚举值与前端显示的状态文本映射
UPGRADE_STATE_MAP = {
    STATE_IDLE: "空闲",
    STATE_IN_PROGRESS: "升级中",
    STATE_FAILED: "升级失败",
    STATE_DONE: "升级成功",
    STATE_ERROR: "发生错误"
}

# —— 设备到固定 IP 的映射：
DEVICE_IP_MAP = {
    'PCS1': '192.168.1.163',
    'PCS2': '192.168.1.164',
    'PCS3': '192.168.1.165',
    'PCS4': '192.168.1.166',
}
VALID_DEVICES = set(DEVICE_IP_MAP.keys())

# 路径与常量
UPLOAD_DIR = Path('/home/zlg/upgrade')
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
STATUS_DIR = Path('/home/zlg/upgrade/status')
STATUS_DIR.mkdir(parents=True, exist_ok=True)
UPGRADE_SCRIPT = Path('/home/zlg/app/script/upgrade.sh')
PCS_REMOTE_USER = 'root'
PCS_REMOTE_DEST = '/home/root/config/firmware/upgrade/zip/'
PCS_REMOTE_DEST_TEST = '/root/test'
ROLLBACK_DIR = Path('/home/zlg/upgrade/rollback')
ROLLBACK_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_ROLL_PATH = Path('/home/zlg/upgrade/backups')
HISTORY_ROLL_PATH.mkdir(parents=True, exist_ok=True)
ROLLBACK_SCRIPT = Path('/home/zlg/app/script/rollback.sh')
# 测试参数
TEST_REMOTE_USERNAME = "wx"              # 账号
TEST_REMOTE_PASSWORD = "1"            # 密码
TEST_REMOTE_PORT = 2222
TEST_REMOTE_IP = "192.168.2.150"
TEST_REMOTE_DB_FILE = "/home/wx/data/database/fault_wave.db"
# ================== 同步 pcs_ware 配置（显式私钥/端口/用户） ==================
REMOTE_USER = "zlg"
REMOTE_HOST = "192.168.1.163"
REMOTE_DIR  = "/home/zlg/pcs_ware"
LOCAL_DIR   = Path("/home/zlg/fault_wave")
ZLOG_DIR = Path("/home/zlgmcu/zlog")

SSH_KEY_PATH = "/root/.ssh/id_ed25519"   # 如不需要可设为 "" 或 None


engine = None

PERM_TABLE = "Permission_Management"
DEFAULT_PASSWORD = "12345678"
PASSWORD_LIFETIME_DAYS = 180
PASSWORD_WARNING_DAYS = 15
