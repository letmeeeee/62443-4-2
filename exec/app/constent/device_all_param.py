from constent.device_info import DEVICE_TYPE
from constent.device_pcs_param import DEVICE_PCS_ALL_REGS
from constent.device_mv_param import *
from constent.device_bms_param import DEVICE_BMS_ALL_REGS

#  ========================= G3点表寄存器信息汇总 ========================
# 暂包含G3_PCS、MV、BMS_BANK
ALL_REG_LIST = {
    DEVICE_TYPE.get("G3_PCS"):DEVICE_PCS_ALL_REGS,
    DEVICE_TYPE.get("MV"): (ELECTRA_TRANSFORMER_PARAMS + ELECTRA_METER_PARAMS + 
                            ELECTRA_HVIP_PARAMS + ELECTRA_UPS_PARAMS + 
                            ELECTRA_MC_PARAMS),
    DEVICE_TYPE.get("BMS_BANK"): DEVICE_BMS_ALL_REGS
}
