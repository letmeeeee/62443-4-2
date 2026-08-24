from utils.utils import debug_log, now_str, DPrint
from utils.systemctl import restart_service_and_exit
import os, sys, time
import numpy as np

# ================== 共享内存模型（严格失败即重启） ==================
SERVICE_NAME = "python_app.service"  # 失败时重启的服务

class RegistersModel:
    def __init__(self):
        default_path = '/dev/shm/my_shared_memory_logger'
        path = os.environ.get("LOGGER_SHM_PATH", default_path)
        dtype = np.uint16
        self.Reg = None
        # region agent log
        debug_log(
            "H2",
            "app:RegistersModel.__init__",
            "registers model init start",
            {
                "path": path,
                "platform": sys.platform,
                "path_exists_at_start": os.path.exists(path),
            },
        )
        # endregion

        for attempt in (1, 2):
            try:
                from utils.systemctl import restart_service_and_exit
                # region agent log
                debug_log(
                    "H4",
                    "app.py:RegistersModel.__init__:attempt",
                    "registers model mapping attempt",
                    {
                        "attempt": attempt,
                        "path": path,
                        "path_exists": os.path.exists(path),
                    },
                )
                # endregion
                if not os.path.exists(path):
                    if os.name == "nt" and path == default_path:
                        raise RuntimeError(
                            f"共享内存文件不存在: {path}（Windows 下请设置 LOGGER_SHM_PATH 指向实际共享内存文件）"
                        )
                    raise RuntimeError(f"共享内存文件不存在: {path}")

                filesize = os.path.getsize(path)
                itemsize = np.dtype(dtype).itemsize
                if itemsize <= 0:
                    raise RuntimeError("dtype itemsize 非法")

                count = filesize // itemsize
                if count < 2 or (count % 2) != 0:
                    raise RuntimeError(f"元素数不合法（需要>=2且为偶数），实际: {count}")

                self.Reg = np.memmap(path, dtype=dtype, mode='r', shape=(count,))
                _ = int(self.Reg[0])  # 触发实际访问
                DPrint(f"[{now_str()}] [INFO] RegistersModel 映射成功: {path}，元素个数: {count}")
                break
            except Exception as e:
                if attempt == 1:
                    DPrint(f"[{now_str()}] [WARNING] RegistersModel 映射失败(第1次): {e}，15秒后重试 ...")
                    time.sleep(15)
                else:
                    restart_service_and_exit(SERVICE_NAME, f"RegistersModel 第2次失败: {e}")

        self.ALL_SIZE = len(self.Reg)
        self.INPUT_SIZE = self.ALL_SIZE // 2
        self.HOLD_SIZE = self.ALL_SIZE - self.INPUT_SIZE
        self.Input = self.Reg[:self.INPUT_SIZE]
        self.Hold = self.Reg[self.INPUT_SIZE:]

    def get_input(self, address):
        return self.Input[address] if 0 <= address < self.INPUT_SIZE else 0

    def get_hold(self, address):
        return self.Hold[address] if 0 <= address < self.HOLD_SIZE else 0

class RankModel:
    def __init__(self):
        self.BANK_SIZE = 10
        self.R_INPUT_SIZE = 17280
        default_path = '/dev/shm/my_shared_memory_bms'
        self.path = os.environ.get("BMS_SHM_PATH", default_path)
        self.dtype = np.uint16
        expected_count = self.BANK_SIZE * self.R_INPUT_SIZE

        self.Reg = None
        self.Input = None

        for attempt in (1, 2):
            try:
                if not os.path.exists(self.path):
                    if os.name == "nt" and self.path == default_path:
                        raise RuntimeError(
                            f"共享内存文件不存在: {self.path}（Windows 下请设置 BMS_SHM_PATH 指向实际共享内存文件）"
                        )
                    raise RuntimeError(f"共享内存文件不存在: {self.path}")

                filesize = os.path.getsize(self.path)
                itemsize = np.dtype(self.dtype).itemsize
                count = filesize // itemsize
                if count != expected_count:
                    raise RuntimeError(f"元素数不匹配，实际: {count}，预期: {expected_count}")

                self.Reg = np.memmap(self.path, dtype=self.dtype, mode='r', shape=(count,))
                self.Input = self.Reg.reshape(self.BANK_SIZE, self.R_INPUT_SIZE)
                _ = int(self.Input[0][0])
                DPrint(f"[{now_str()}] [INFO] RankModel 映射成功: {self.path}, shape=({self.BANK_SIZE}, {self.R_INPUT_SIZE})")
                break
            except Exception as e:
                if attempt == 1:
                    DPrint(f"[{now_str()}] [WARNING] RankModel 映射失败(第1次): {e}，15秒后重试 ...")
                    time.sleep(15)
                else:
                    restart_service_and_exit(SERVICE_NAME, f"RankModel 第2次失败: {e}")

    def get_r_input(self, bank_index, address):
        if 0 <= bank_index < self.BANK_SIZE and 0 <= address < self.R_INPUT_SIZE:
            return self.Input[bank_index][address]
        return 0

    def get_r_hold(self, bank_index, address):
        return self.get_r_input(bank_index, address)

# 初始化共享内存（若失败会在内部重启并退出）
registers_model = RegistersModel()
rank_model = RankModel()
