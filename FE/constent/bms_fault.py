from constent.common import BMS_BASE_ADDRESS

################################## BMS 故障寄存器地址 ##################################
# BMS告警点表地址
BMS_ALARM_BASE_ADDRESS = BMS_BASE_ADDRESS
BMS_ALARM_BMS_STEP = 200

# BMS历史故障数据地址,共3个寄存器,8个分区
BMS_FAULT_REG_NUM = 1
BMS_SYSTEM_FAULT_OFFSET = 39
# BMS_RACK_FAULT1_OFFSET = 50
# BMS_RACK_FAULT2_OFFSET = 51
BMS_SYSTEM_FAULT_BASE_ADDRESS = BMS_BASE_ADDRESS + BMS_SYSTEM_FAULT_OFFSET
# BMS_RACK_FAULT1_BASE_ADDRESS = BMS_BASE_ADDRESS + BMS_RACK_FAULT1_OFFSET
# BMS_RACK_FAULT2_BASE_ADDRESS = BMS_BASE_ADDRESS + BMS_RACK_FAULT2_OFFSET
# BMS故障信息寄存器地址
BMS_FAULT_ADDR_LIST = [
    BMS_SYSTEM_FAULT_BASE_ADDRESS
    # BMS_RACK_FAULT1_BASE_ADDRESS,
    # BMS_RACK_FAULT2_BASE_ADDRESS
]

# BMS告警信息寄存器地址
BMS_WARNING_ADDR_LIST = []

# BMS检查地址列表
BMS_CHECK_ADDR_LIST = {
    "fault": BMS_FAULT_ADDR_LIST,
    "warning": BMS_WARNING_ADDR_LIST
}

# ALARM_REGISTER
# 更新后BMS的告警信息集成在一个寄存器
BMS_ALARM_REGISTER_DEFINITIONS = [
    {
        "dataName": "bms.bank.externalFaultStatusSum",
        "addressOffset": BMS_SYSTEM_FAULT_BASE_ADDRESS,
        "type":"fault",
        "Names": [
            "bms.faults.bmsFaultSum.systemWarn",
            "bms.faults.bmsFaultSum.systemAlm",
            "bms.faults.bmsFaultSum.systemCritical",
            "bms.faults.bmsFaultSum.systemForbidChg",
            "bms.faults.bmsFaultSum.systemForbidDischg",
            "bms.faults.bmsFaultSum.pcsControlFault",
            "bms.faults.bmsFaultSum.circuitConectFault",
            "history.table.pcsGroup.reserved",
            "history.table.pcsGroup.reserved",
            "history.table.pcsGroup.reserved",
            "history.table.pcsGroup.reserved",
            "history.table.pcsGroup.reserved",
            "history.table.pcsGroup.reserved",
            "history.table.pcsGroup.reserved",
            "history.table.pcsGroup.reserved",
            "history.table.pcsGroup.reserved"
        ]
    }
]
