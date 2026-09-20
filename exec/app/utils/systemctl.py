#!/usr/bin/env python3
import os, sys, subprocess, socket, shutil, threading, time
from datetime import datetime
from utils.utils import DPrint, debug_log, now_str
from config import ROLLBACK_SCRIPT, UPGRADE_SCRIPT, STATE_ERROR, SSH_KEY_PATH, REMOTE_PORT, REMOTE_PASSWORD, REMOTE_PASSWORD_TEST, FIXED_DEVICE_ID, READ_INPUT_REGISTER
from constent.common import PCS_UPGRADE_STATUS_BASE_ADDRESS, PCS_FAULT_STEP
from pathlib import Path
from typing import Tuple, Optional

# 线程安全
pending_lock = threading.Lock()
pending_count = 0


def inc_pending(n: int = 1) -> int:
    """线程安全地增加 pending_count，返回新值。"""
    global pending_count
    with pending_lock:
        pending_count += n
        DPrint(f"[SCP] pending_count 增加 {n}, 新值: {pending_count}")
        return pending_count


def dec_pending(n: int = 1) -> int:
    """线程安全地减少 pending_count，返回新值（可能为负）。"""
    global pending_count
    with pending_lock:
        pending_count -= n
        return pending_count


def get_pending() -> int:
    """线程安全地获取 pending_count 的当前值。"""
    with pending_lock:
        return pending_count

# ================== 网络配置接口 ==================
NETWORK_CONFIG_PATH = Path("/etc/network/interfaces")

def reboot_system():
    """
    调用系统 reboot。若失败，返回错误字符串；成功/已发起返回 None。
    """
    try:
        result = subprocess.run(["reboot"], capture_output=True, text=True)
        if result.returncode != 0:
            return f"reboot 失败: rc={result.returncode}, stderr={result.stderr.strip()}"
        return None
    except Exception as e:
        return f"reboot 异常: {e}"

def schedule_reboot(delay_sec: int = 2):
    """
    异步延时重启，避免阻塞响应。
    """
    def _task():
        err = reboot_system()
        if err:
            DPrint(f"[{now_str()}] [REBOOT] 重启失败: {err}")
        else:
            DPrint(f"[{now_str()}] [REBOOT] 已触发系统重启")

    try:
        t = threading.Timer(delay_sec, _task)
        t.daemon = True
        t.start()
        return None
    except Exception as e:
        return f"调度重启异常: {e}"

# ========== scp ==========
def scp_send(
    src_file: Path,
    user: str,
    host: str,
    dest_dir: str,
    password: Optional[str] = None,
    timeout_sec: int = 120
) -> Tuple[bool, str]:
    remote_dest = f"{user}@{host}:{Path(dest_dir).as_posix()}/"
    base_opts = ["-q", "-o", "StrictHostKeyChecking=no"]

    if password:
        # 使用 sshpass 传递密码
        cmd = [
            "sshpass", "-p", password,
            "scp", *base_opts, str(src_file), remote_dest
        ]
        # DPrint(f"[SCP] 使用密码传输: {cmd}")
    else:
        # 走 SSH 密钥免密登录
        cmd = ["scp", *base_opts, str(src_file), remote_dest]

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_sec
        )
    except subprocess.TimeoutExpired:
        return False, f"传输超时 {timeout_sec}s"
    except FileNotFoundError:
        return False, "缺少依赖: scp 或 sshpass"
    except Exception as e:
        return False, f"执行异常: {str(e)}"

    if proc.returncode == 0:
        return True, "ok"
    return False, proc.stderr.strip()


# 发送函数
def scp_send_async(src_file: Path, user: str, host: str, dest_dir: str):
    # 在调用时自增计数，线程结束时再减
    # try:
    #     inc_pending(1)
    # except Exception:
    #     # 保底：若 inc_pending 未定义或失败，不阻塞调用
    #     pass
    src_file = Path(src_file)
    def _runner():
        try:
            ok, msg = scp_send(src_file, user, host, dest_dir, REMOTE_PASSWORD_TEST)
            DPrint(f"[SCP][async] host={host} ok={ok} msg={msg}")
        except Exception as e:
            DPrint(f"[SCP][async] host={host} exception: {e}")
        finally:
            try:
                new_count = dec_pending(1)
            except Exception:
                new_count = None

            DPrint(f"[SCP][async] host={host} pending_count={new_count}")

            if new_count == 0:
                work_dir = src_file.parent
                if work_dir.exists() and work_dir.is_dir():
                    try:
                        shutil.rmtree(work_dir)
                        DPrint(f"[SCP][async] 所有文件传输完成,已删除临时文件夹: {work_dir}")
                    except Exception as e:
                        DPrint(f"[SCP][async] 删除临时文件夹失败: {work_dir}, err: {e}")
            elif isinstance(new_count, int) and new_count < 0:
                DPrint(f"[SCP][async] 警告: pending_count 负值: {new_count}")

    threading.Thread(target=_runner, daemon=True).start()

# 清空目标升级文件夹
def clear_remote_upgrade_folder(remote_name, remote_ip, remote_dest, password):
    try:
        # 使用 sshpass + ssh 执行远程命令删除升级文件夹中的内容
        cmd = f"sshpass -p {password} ssh -o StrictHostKeyChecking=no root@{remote_ip} 'rm -rf {remote_dest}/*'"
        subprocess.run(cmd, shell=True, check=True)
        DPrint(f"[CLEAN] 已清理远程设备 {remote_name} ({remote_ip}) 的升级文件夹")
        return True
    except Exception as e:
        DPrint(f"[CLEAN] 清理远程设备 {remote_name} ({remote_ip}) 升级文件夹失败: {e}")
        return False

# 查询PCS升级状态寄存器,是否处于就绪/空闲状态
def query_pcs_upgrade_status(idx=0):
    from utils.method import query_register_data
    try:
        if idx < 1:
            DPrint(f"[QUERY] query_pcs_upgrade_status idx 参数异常: {idx}")
            return None
        upgrade_status_address = PCS_UPGRADE_STATUS_BASE_ADDRESS + (idx - 1) * PCS_FAULT_STEP
        registers = query_register_data(FIXED_DEVICE_ID, READ_INPUT_REGISTER, upgrade_status_address, 1)
        if registers:
            status = int(registers[0]) & 0xFFFF
            DPrint(f"[QUERY] PCS升级状态寄存器值: {status}")
            return status
        else:
            DPrint(f"[QUERY] 读取PCS升级状态寄存器失败: 无数据返回")
            return None
    except Exception as e:
        DPrint(f"[QUERY] 读取PCS升级状态寄存器异常: {e}")
        return None

# ========== 触发升级脚本 ==========
def run_upgrade_async(job_id: str, release_version: str, delay_sec: int = 2):
    from utils.method import _write_status
    from config import UPLOAD_DIR
    def _runner():
        try:
            time.sleep(delay_sec)

            if not UPGRADE_SCRIPT.exists():
                DPrint(f"[UPGRADE] 未找到升级脚本: {UPGRADE_SCRIPT}")
                _write_status(job_id, STATE_ERROR, 0, "upgrade.sh not found")
                return

            if not os.access(UPGRADE_SCRIPT, os.X_OK):
                try:
                    UPGRADE_SCRIPT.chmod(0o755)
                except Exception as e:
                    DPrint(f"[UPGRADE] 赋予执行权限失败: {e}")

            cmd = [
                'systemctl', 'restart', 'python_upgrade.service'
            ]
            # job_id写入临时文件,脚本负责清理
            with open(UPLOAD_DIR / 'job_id', 'w') as f:
                f.write(job_id)
            with open(UPLOAD_DIR / 'release_version', 'w') as f:
                f.write(release_version)
            env = dict(os.environ)
            env['PATH'] = env.get('PATH', '') + ':/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'

            subprocess.Popen(
                cmd,
                cwd='/home/zlg',
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )

            DPrint(f"[UPGRADE] upgrade.sh 已后台启动（job={job_id}）")

        except Exception as e:
            DPrint(f"[UPGRADE] 启动升级脚本异常: {e}")
            _write_status(job_id, STATE_ERROR, 0, f"start script error: {e}")

    threading.Thread(target=_runner, daemon=True).start()

def start_rollback(job_id: str, spcVersion: str, delay_sec: int = 2):
    from utils.method import _write_status
    from config import ROLLBACK_DIR
    def _runner():
        try:
            time.sleep(delay_sec)

            if not ROLLBACK_SCRIPT.exists():
                DPrint(f"[ROLLBACK] 未找到升级脚本: {ROLLBACK_SCRIPT}")
                _write_status(job_id, STATE_ERROR, 0, "rollback.sh not found")
                return

            if not os.access(ROLLBACK_SCRIPT, os.X_OK):
                try:
                    ROLLBACK_SCRIPT.chmod(0o755)
                except Exception as e:
                    DPrint(f"[ROLLBACK] 赋予执行权限失败: {e}")

            cmd = [
                'systemctl', 'restart', 'python_rollback.service'
            ]
            # job_id写入临时文件,脚本负责清理
            with open(ROLLBACK_DIR / 'job_id', 'w') as f:
                f.write(job_id)
            with open(ROLLBACK_DIR / 'spcVersion', 'w') as f:
                f.write(spcVersion)
            env = dict(os.environ)
            env['PATH'] = env.get('PATH', '') + ':/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'

            subprocess.Popen(
                cmd,
                cwd='/home/zlg',
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )

            DPrint(f"[ROLLBACK] rollback.sh 已后台启动（job={job_id}）")

        except Exception as e:
            DPrint(f"[ROLLBACK] 启动升级脚本异常: {e}")
            _write_status(job_id, STATE_ERROR, 0, f"start script error: {e}")

    threading.Thread(target=_runner, daemon=True).start()

def _base_ssh_args():
    args = ["ssh", "-o", "StrictHostKeyChecking=no", "-p", str(REMOTE_PORT)]
    if SSH_KEY_PATH:
        args += ["-i", SSH_KEY_PATH]
    return args

def _base_scp_args():
    args = ["scp", "-q", "-o", "StrictHostKeyChecking=no", "-P", str(REMOTE_PORT)]
    if SSH_KEY_PATH:
        args += ["-i", SSH_KEY_PATH]
    return args

def restart_service_and_exit(service_name: str, reason: str):
    """重启 systemd 服务并立刻退出当前进程"""
    DPrint(f"[{now_str()}] [FATAL] 共享内存最终失败: {reason} → 重启服务: {service_name}")
    # region agent log
    debug_log(
        "H3",
        "app.py:restart_service_and_exit",
        "about to restart service after fatal shared memory failure",
        {
            "service_name": service_name,
            "reason": str(reason),
            "platform": sys.platform,
            "is_windows": (os.name == "nt"),
        },
    )
    # endregion
    try:
        if os.name != "nt" and shutil.which("systemctl"):
            subprocess.run(
                ["systemctl", "restart", service_name],
                check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
        else:
            DPrint(f"[{now_str()}] [INFO] 当前平台不支持 systemctl，跳过服务重启")
    except Exception as e:
        DPrint(f"[{now_str()}] [ERROR] systemctl restart 失败: {e}")
    os._exit(1)

def restart_sys_service(service_name: str, remark: str):
    """重启 systemd 服务"""
    DPrint(f"[{now_str()}] 重启服务: {service_name}, remark: {remark}")
    # endregion
    try:
        if os.name != "nt" and shutil.which("systemctl"):
            subprocess.run(
                ["systemctl", "restart", service_name],
                check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
        else:
            DPrint(f"[{now_str()}] [INFO] 当前平台不支持 systemctl，跳过服务重启")
    except Exception as e:
        DPrint(f"[{now_str()}] [ERROR] systemctl restart 失败: {e}")

def run_cmd(args, timeout=60):
    """运行命令并返回 (rc, stdout, stderr)"""
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr

def norm_dt(s: str) -> str:
    """
    规范化前端 datetime-local 字符串为 'YYYY-MM-DD HH:MM:SS'
    支持：
      - 'YYYY-MM-DDTHH:MM'        -> 秒补 ':00'
      - 'YYYY-MM-DDTHH:MM:SS'
      - 'YYYY-MM-DD HH:MM'        -> 秒补 ':00'
      - 'YYYY-MM-DD HH:MM:SS'
    其他输入返回空串（视作未提供）。
    """
    if not s or not isinstance(s, str):
        return ""
    s = s.strip()
    if not s:
        return ""
    s = s.replace('T', ' ')
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        pass
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M")
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return ""

def check_ssh_port(ip, port=22, timeout=2):
    try:
        s = socket.socket()
        s.settimeout(timeout)
        s.connect((ip, port))
        s.close()
        return True
    except:
        return False

def check_network(ip, port):

    if not check_ssh_port(ip, port):
        DPrint("SSH 端口不通")
        return False

    DPrint("网络正常")
    return True

def scp_download(remote_ip, user, password, remote_path, local_path, port=22):
    """
    从远程设备拉文件到本地
    """
    cmd = [
        "sshpass", 
        "-p", f"{password}", 
        "scp",
        "-P", str(port),
        f"{user}@{remote_ip}:{remote_path}",
        local_path
    ]
    DPrint(cmd)

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"SCP失败: {result.stderr}")

    return result.stdout
