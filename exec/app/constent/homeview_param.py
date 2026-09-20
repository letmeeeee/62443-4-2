
# ===================== 主页面视图 ======================
HOME_VIEW_DIAGRAM_PARAMS = [
    {
        "name": "system.activePower",
        "address": 125,
        "offset": 2,
        "precision": "0.1",
        "unit": "kW",
        "valueType": "int32",
        "bitMapping": ""
    },
    {
        "name": "system.reactivePower",
        "address": 127,
        "offset": 2,
        "precision": "0.1",
        "unit": "kVar",
        "valueType": "int32",
        "bitMapping": ""
    },
    {
        "name": "deviceConf.PCSNum",
        "address": 200,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "system.dcSideAverageVoltage",
        "address": 135,
        "offset": 2,
        "precision": "0.1",
        "unit": "V",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "system.dcSideCurrent",
        "address": 133,
        "offset": 2,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "system.systemSOC",
        "address": 104,
        "offset": 1,
        "precision": "0.1",
        "unit": "%",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "deviceConf.BMSNum",
        "address": 204,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
]

HOME_VIEW_INFORMATION_PARAMS = [
    {
        "name": "system.nominalCapacity",
        "address": 100,
        "offset": 2,
        "precision": "0.1",
        "unit": "kVA",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "system.nominalEnergy",
        "address": 102,
        "offset": 2,
        "precision": "0.1",
        "unit": "kWh",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "system.systemSOC",
        "address": 104,
        "offset": 1,
        "precision": "0.1",
        "unit": "%",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "system.systemSOH",
        "address": 105,
        "offset": 1,
        "precision": "0.1",
        "unit": "%",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "system.systemTotalStatus",
        "address": 106,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": "",
        "valueMapping": {
            0: "status.Initializing",
            1: "status.Already Stopped",
            2: "status.Starting",
            3: "status.Running",
            4: "status.Standby",
            5: "status.Fault",
            6: "status.Alarm",
            7: "status.Warning",
            11: "status.Stopping",  
            13: "status.PCS Stop",
            14: "status.Subsystem Stop",
            15: "status.Subsystem Startup",
            16: "status.PCS Startup",
            20: "status.Configuring",
            21: "status.Starting PQ mode",
            22: "status.PQ Mode Running",
            23: "status.Stopping PQ Mode",
            24: "status.PQ Node Stopping",
            25: "status.Set 0 Power",
            27: "status.Partial Fault Stop"
        }
    },
    {
        "name": "system.systemTotalFault",
        "address": 107,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": "",
        "valueMapping": {
            0: "status.Normal",
            1: "Faulted"
        }
    },
    {
        "name": "system.systemTotalStatus(Summary)",
        "address": 108,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": "",
        "valueMapping": {
            0: "status.Initializing",
            1: "status.Already Stopped",
            2: "status.Starting",
            3: "status.Running",
            4: "status.Standby",
            5: "status.Fault",
            6: "status.Alarm",
            7: "status.Warning",
            11: "status.Stopping",  
            20: "status.Configuring"
        }
    },
    {
        "name": "system.allowedChargeEnergy",
        "address": 109,
        "offset": 2,
        "precision": "0.1",
        "unit": "kWh",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "system.allowedDischargeEnergy",
        "address": 111,
        "offset": 2,
        "precision": "0.1",
        "unit": "kWh",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "system.allowedChargePower",
        "address": 113,
        "offset": 2,
        "precision": "0.1",
        "unit": "kW",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "system.allowedDischargePower",
        "address": 115,
        "offset": 2,
        "precision": "0.1",
        "unit": "kW",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "system.pcsStatusSummary",
        "address": 121,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": "",
        "valueMapping": {
            0: "status.Initializing",
            1: "Shutdown, all pcs is shutdown and can't startup",
            2: "Standy, all pcs is in standby",
            3: "Operating,any pcs is operating",
            4: "Fault, any pcs is faulting"
        }
    },
    {
        "name": "system.powerFactor",
        "address": 122,
        "offset": 1,
        "precision": "0.0001",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "system.apparentPower",
        "address": 123,
        "offset": 2,
        "precision": "0.1",
        "unit": "kVA",
        "valueType": "int32",
        "bitMapping": ""
    },
    {
        "name": "system.activePower",
        "address": 125,
        "offset": 2,
        "precision": "0.1",
        "unit": "kW",
        "valueType": "int32",
        "bitMapping": ""
    },
    {
        "name": "system.reactivePower",
        "address": 127,
        "offset": 2,
        "precision": "0.1",
        "unit": "kVar",
        "valueType": "int32",
        "bitMapping": ""
    },
    {
        "name": "system.acSideFrequency",
        "address": 129,
        "offset": 2,
        "precision": "0.01",
        "unit": "Hz",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "system.dcSidePower",
        "address": 131,
        "offset": 2,
        "precision": "0.1",
        "unit": "kW",
        "valueType": "int32",
        "bitMapping": ""
    },
    {
        "name": "system.dcSideCurrent",
        "address": 133,
        "offset": 2,
        "precision": "0.1",
        "unit": "A",
        "valueType": "int32",
        "bitMapping": ""
    },
    {
        "name": "system.dcSideAverageVoltage",
        "address": 135,
        "offset": 2,
        "precision": "0.1",
        "unit": "V",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "system.acdailyChargeEnergy",
        "address": 145,
        "offset": 2,
        "precision": "0.1",
        "unit": "kWh",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "system.acdailyDischargeEnergy",
        "address": 147,
        "offset": 2,
        "precision": "0.1",
        "unit": "kWh",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "system.actotalChargeEnergy",
        "address": 149,
        "offset": 2,
        "precision": "0.1",
        "unit": "kWh",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "system.actotalDischargeEnergy",
        "address": 151,
        "offset": 2,
        "precision": "0.1",
        "unit": "kWh",
        "valueType": "uint32",
        "bitMapping": ""
    }
]

HOME_VIEW_RESERVER_PARAMS = []
