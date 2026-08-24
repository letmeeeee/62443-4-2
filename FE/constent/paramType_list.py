from constent.homeview_param import *
from constent.device_config_param import *
from constent.device_pcs_param import *
from constent.device_bms_param import *
from constent.device_mv_param import *

# ===================== 按数据类型分类的参数列表 ====================
"""
1.从systemView-pcs到device-bms-info均使用/api/data/muti/getData接口
2.其他读点均使用/api/data/getData接口
"""
PARAMS_BY_DATA_TYPE = {
    "homeView-diagram": HOME_VIEW_DIAGRAM_PARAMS,
    "homeView-information": HOME_VIEW_INFORMATION_PARAMS,
    "homeView-reserver": HOME_VIEW_RESERVER_PARAMS,
    "systemView-status": SYSTEM_VIEW_STATUS_PARAMS,
    "systemView-pcs": SYSTEM_VIEW_PCS_PARAMS,
    "systemView-bms": SYSTEM_VIEW_BMS_PARAMS,
    #================== PCS相关 ==================
    # G3无PCS Group不显示,显示PCS1和PCS2的测点参数
    "device-pcs-group": DEVICE_PCS_GROUP_PARAMS,
    "device-pcs-master": DEVICE_PCS_ALL_REGS,
    "device-pcs-slave": DEVICE_PCS_ALL_REGS,
    #================== BMS相关 ==================
    "device-bms-info": DEVICE_BMS_ALL_REGS,
    #================== 中压系统相关 ==============
    "electra-transformer": ELECTRA_TRANSFORMER_PARAMS,
    "electra-meter": ELECTRA_METER_PARAMS,
    "electra-hvip": ELECTRA_HVIP_PARAMS,
    "electra-ups": ELECTRA_UPS_PARAMS,
    "electra-mc": ELECTRA_MC_PARAMS,
}
