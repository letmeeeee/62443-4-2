
# ===================== 设备配置参数 ====================
SYSTEM_VIEW_STATUS_PARAMS = [
    # 3个参数
    # {
    #     "name": "status.pcsGroup1Status",
    #     "address": 221,
    #     "offset": 1,
    #     "precision": "1",
    #     "unit": "",
    #     "valueType": "uint16",
    #     "bitMapping": "0"
    # },
    {
        "name": "status.MeasuringandControlDeviceCommunicationStatus",
        "address": 219,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": "8"
    },
    {
        "name": "status.UPS485CommunicationStatus",
        "address": 219,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": "9"
    },
    {
        "name": "status.EMSCommunicationStatus",
        "address": 219,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": "10"
    },
]

SYSTEM_VIEW_PCS_PARAMS = [
    # 16个参数
    {
        "name": "status.pcsCommunicationStatus",
        "address": 218,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": "0"
    },
    {
        "name": "device.pcs.activePower(total)Pcc",
        "address": 2711,
        "offset": 1,
        "precision": "1",
        "unit": "kW",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.reactivePower(total)Pcc",
        "address": 2712,
        "offset": 1,
        "precision": "1",
        "unit": "kVar",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.dcPower(total)",
        "address": 2710,
        "offset": 1,
        "precision": "1",
        "unit": "kW",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.batteryPower(j1)",
        "address": 2741,
        "offset": 1,
        "precision": "1",
        "unit": "kW",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.batteryPower(j2)",
        "address": 2748,
        "offset": 1,
        "precision": "1",
        "unit": "kW",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridVoltageRsPcc",
        "address": 2703,
        "offset": 1,
        "precision": "0.1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridVoltageStPcc",
        "address": 2704,
        "offset": 1,
        "precision": "0.1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridVoltageTrPcc",
        "address": 2705,
        "offset": 1,
        "precision": "0.1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridCurrentPhaseR(total)Pcc",
        "address": 2707,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridCurrentPhaseS(total)Pcc",
        "address": 2708,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridCurrentPhaseT(total)Pcc",
        "address": 2709,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.batteryVoltage(j1)",
        "address": 2735,
        "offset": 1,
        "precision": "0.1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.batteryCurrent(j1)",
        "address": 2736,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.batteryVoltage(j2)",
        "address": 2742,
        "offset": 1,
        "precision": "0.1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.batteryCurrent(j2)",
        "address": 2743,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
]

SYSTEM_VIEW_BMS_PARAMS = [
    # 13个参数
    {
        "name": "status.bmsRunningStatus",
        "address": 220,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": "0"
    },
    {
        "name": "bms.bank.bankTotalVoltage",
        "address": 38000 + 0,
        "offset": 1,
        "precision": "0.1",
        "unit": "V",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.systemTotalCurrent",
        "address": 38000 + 1,
        "offset": 2,
        "precision": "0.1",
        "unit": "A",
        "valueType": "int32",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.totalSOC",
        "address": 38000 + 3,
        "offset": 1,
        "precision": "0.1",
        "unit": "%",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.bausoh",
        "address": 38000 + 4,
        "offset": 1,
        "precision": "0.1",
        "unit": "%",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.systemInsulation",
        "address": 38000 + 5,
        "offset": 1,
        "precision": "1",
        "unit": "kΩ",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.systemChargeSOPDisplay",
        "address": 38000 + 8,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.systemDischargeSOPDisplay",
        "address": 38000 + 9,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.cluMaxCurrentDiff",
        "address": 38000 + 10,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.maxBatteryVoltage",
        "address": 38000 + 15,
        "offset": 1,
        "precision": "0.1",
        "unit": "mV",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.minBatteryVoltage",
        "address": 38000 + 19,
        "offset": 1,
        "precision": "0.1",
        "unit": "mV",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.maxBatteryTemp",
        "address": 38000 + 24,
        "offset": 1,
        "precision": "0.1",
        "unit": "°C",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.minBatteryTemp",
        "address": 38000 + 28,
        "offset": 1,
        "precision": "0.1",
        "unit": "°C",
        "valueType": "int16",
        "bitMapping": ""
    },
]

SYSTEM_VIEW_COMSTATUS = {
    0: "status.communicationFault",
    1: "status.communicationNormal"
}

COM_REG_LIST = [
    218, 219, 220, 221 # system 通信状态寄存器地址
]