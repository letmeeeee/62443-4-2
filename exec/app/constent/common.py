################################## G3公共地址 ##################################
# SYSTEM
SYSTEM_SPC_VERSION_ADDR = 5
# BMS
BMS_BASE_ADDRESS = 38000
BMS_FAULT_STEP = 200
# PCS
PCS_BASE_ADDRESS = 2600
PCS_FAULT_STEP = 300

PCS_BASE_HOLD_ADDRESS = 12000
PCS_HOLD_STEP = 700
PCS_GROUP_HOLD_STEP = 1400

PCS_UPGRADE_STATUS_BASE_ADDRESS = PCS_BASE_ADDRESS + 62
PCS_BASE_UPGRADE_PROCESS_ADDR = 2661
PCS_BASE_UPGRADE_STATE_ADDR = 2662
# PCS 固件版本：FC4，从 PCS 输入区 +5 起，每个组件一个 16 位字。
PCS_FIRMWARE_VERSION_OFFSET = 5
PCS_FIRMWARE_COMPONENT_NAMES = (
    'controller', 'cdsp', 'sfpga', 'sdsp',
    'j1dsp', 'j1fpga', 'j2dsp', 'j2fpga',
)
PCS_FIRMWARE_MAIN_VERSION_MASK = 0x03ff      # bit0～9，百分位主版本
PCS_FIRMWARE_SUB_VERSION_SHIFT = 10         # bit10～12，子版本 0～7
PCS_FIRMWARE_FUNCTION_SHIFT = 13            # bit13～15，功能定义 0～7
PCS_FIRMWARE_FIELD_MASK = 0x07
PCS_FIRMWARE_FUNCTION_NAMES = {0: 'M', 1: 'P', 2: 'V'}

# PCS 校验接口：安规码/主从角色使用保持寄存器（FC3）。
PCS_VERIFY_STANDARD_ADDR = 12100
PCS_VERIFY_ROLE_ADDR = 12009
PCS_VERIFY_PARAM_STEP = 700

# 组状态使用输入寄存器（FC4），每组对应两台 PCS。
PCS_VERIFY_GROUP_ADDR = 17060
PCS_VERIFY_GROUP_STEP = 300
PCS_VERIFY_MODE_COUNT = 4
PCS_VERIFY_GROUP_SIZE = 2
# (组内 PCS 序号, 状态字下标, 双 BUS 位掩码)
PCS_VERIFY_PARALLEL_LAYOUT = ((1, 0, 1 << 9), (2, 2, 1 << 14))
PCS_VERIFY_MODE_WORD_INDEX = 4
PCS_VERIFY_OFF_GRID_MASK = 1 << 5
PCS_VERIFY_RUN_MODE_MASK = 0x1f

# 协议枚举及接口输出名称，安规码以元组下标作为枚举值。
PCS_VERIFY_STANDARD_NAMES = (
    'VDE_AR_N_4110', 'VDE_AR_N_4120', 'VDE_AR_N_4130', 'G99', 'TAIWAN',
    'EN50549_2', 'UL_1547', 'RomaniaB', 'RomaniaC', 'RomaniaD',
)
PCS_VERIFY_ROLE_NAMES = {0: 'slave', 1: 'master'}
PCS_VERIFY_UNKNOWN_ROLE = 'unknown'
PCS_VERIFY_RUN_MODE_NAMES = {
    0: 'open_loop',          # 开环（离网）
    1: 'short_circuit_loop', # 短路环（离网）
    2: 'vf',                # VF（离网）
    3: 'pq',                # PQ（并网）
    4: 'afe',               # AFE（并网）
    5: 'cp_dc',             # CP_DC（并网）
    6: 'cc_dc',             # CC_DC（并网）
    7: 'cv_dc',             # CV_DC（并网）
    8: 'droop',             # 下垂
    9: 'vsg_off_grid',      # VSG（离网）
    10: 'vsg_grid_connected', # VSG（并网）
}
PCS_VERIFY_DEFAULT_RUN_MODE = 'none'
PCS_VERIFY_PARALLEL_MODE_NAMES = {0: 'single_bus', 1: 'double_bus'}
PCS_VERIFY_GRID_MODE_NAMES = {0: 'grid_connected', 1: 'off_grid', 2: 'VSG'}

# MV
UPS_BASE_ADDRESS = 27100
MC_BASE_ADDRESS = 27300
MV_FAULT_STEP = 200

# TEST_MODE
TEST_MODE = False


