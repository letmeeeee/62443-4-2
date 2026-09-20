# ===================== BMS BANK 相关参数 ====================
# BMS寄存器汇总,地址38000~38074
# /bms/bank/ and /history/table/bmstable/
DEVICE_BMS_ALL_REGS = [
    {
        "name": "bms.bank.bankTotalVoltage",
        "address": 38000,
        "offset": 1,
        "precision": "0.1",
        "unit": "V",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.systemTotalCurrent",
        "address": 38001,
        "offset": 2,
        "precision": "0.1",
        "unit": "A",
        "valueType": "int32",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.totalSOC",
        "address": 38003,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.bausoh",
        "address": 38004,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.systemInsulation",
        "address": 38005,
        "offset": 1,
        "precision": "1",
        "unit": "kΩ",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.chargeRemainCapacity",
        "address": 38006,
        "offset": 1,
        "precision": "1",
        "unit": "kWh",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.dischargeRemainCapacity",
        "address": 38007,
        "offset": 1,
        "precision": "1",
        "unit": "kWh",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.systemChargeSOPDisplay",
        "address": 38008,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.systemDischargeSOPDisplay",
        "address": 38009,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.cluMaxCurrentDiff",
        "address": 38010,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.cluMaxTotalVoltageDiff",
        "address": 38011,
        "offset": 1,
        "precision": "0.1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.maxVoltageRackNum",
        "address": 38012,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.maxVoltageCluNum",
        "address": 38013,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.maxVoltageCellPos",
        "address": 38014,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.maxBatteryVoltage",
        "address": 38015,
        "offset": 1,
        "precision": "1",
        "unit": "mV",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.minVoltageRackNum",
        "address": 38016,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.minVoltageCluNum",
        "address": 38017,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.minVoltageCellPos",
        "address": 38018,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.minBatteryVoltage",
        "address": 38019,
        "offset": 1,
        "precision": "1",
        "unit": "mV",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.bankAverageVoltage",
        "address": 38020,
        "offset": 1,
        "precision": "1",
        "unit": "mV",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.maxTempRackNum",
        "address": 38021,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.maxTempCluNum",
        "address": 38022,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.maxTempCellPos",
        "address": 38023,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.maxBatteryTemp",
        "address": 38024,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.minTempRackNum",
        "address": 38025,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.minTempCluNum",
        "address": 38026,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.minTempCellPos",
        "address": 38027,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.minBatteryTemp",
        "address": 38028,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.bankAverageTemp",
        "address": 38029,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "history.table.bmsTable.totalChargeCapacityHigh",
        "address": 38030,
        "offset": 1,
        "precision": "1",
        "unit": "kWh",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "history.table.bmsTable.totalChargeCapacityLow",
        "address": 38031,
        "offset": 1,
        "precision": "1",
        "unit": "kWh",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "history.table.bmsTable.totalDischargeCapacityHigh",
        "address": 38032,
        "offset": 1,
        "precision": "1",
        "unit": "kWh",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "history.table.bmsTable.totalDischargeCapacityLow",
        "address": 38033,
        "offset": 1,
        "precision": "1",
        "unit": "kWh",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.gridConnectCluNum",
        "address": 38034,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.systemTotalCluNum",
        "address": 38035,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.bauMinGridCluNum",
        "address": 38036,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.dischargePower",
        "address": 38037,
        "offset": 1,
        "precision": "1",
        "unit": "kW",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.chargePower",
        "address": 38038,
        "offset": 1,
        "precision": "1",
        "unit": "kW",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.externalFaultStatusSum",
        "address": 38039,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "bms.bank.EntryIntoBlackStartMode",
        "address": 38060,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "valueMapping": {
            0: "blackStatus.Disconnected",
            1: "blackStatus.Connected",
        },
    },
    {
        "name": "bms.bank.BlackStartStatus",
        "address": 38061,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "pointMapping": {
            0: "blackStatus.Confirm black start issued by EMS",
            1: "blackStatus.Disable DI4-UPS power supply disconnection, DI15 fire fault, liquid cooling communication fault",
            2: "blackStatus.Start automatic grid connection",
            3: "blackStatus.Execution successful",
            4: "blackStatus.Execution failed",
            5: "blackStatus.EMS terminates black start",
        },
    },
    {
        "name": "bms.bank.gridConnectStatus",
        "address": 38062,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "pointMapping": {
            0: "status.NoProcess",
            1: "status.Open",
            2: "status.ConnectionSuccessful",
            3: "status.ProcessEnd",
        },
    },
    {
        "name": "bms.bank.systemRunMode",
        "address": 38071,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "pointMapping": {
            0: "status.Normal",
            1: "status.NoCharge",
            2: "status.NoDischarge",
            3: "status.Standby",
            4: "status.Shutdown",
        },
    },
    {
        "name": "bms.bank.chargeDischargeStatus",
        "address": 38072,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "valueMapping": {
            0: "status.Idle",
            1: "status.Discharging",
            2: "status.Charging",
        },
    },
    {
        "name": "bms.bank.heartbeat",
        "address": 38074,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    }
]
