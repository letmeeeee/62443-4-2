# ===================== PCS 相关参数 ====================
# PCS GROUP
# 默认PPC为电网侧参数
# 21个参数,不维护
DEVICE_PCS_GROUP_PARAMS = [
    {
        "name": "pcsGroup.gridVoltRS",
        "address": 2600 + 103,
        "offset": 1,
        "precision": "1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "pcsGroup.gridVoltST",
        "address": 2600 + 104,
        "offset": 1,
        "precision": "1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "pcsGroup.gridVoltTR",
        "address": 2600 + 105,
        "offset": 1,
        "precision": "1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "pcsGroup.totalACCurrentR",
        "address": 2600 + 107,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "pcsGroup.totalACCurrentS",
        "address": 2600 + 108,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "pcsGroup.totalACCurrentT",
        "address": 2600 + 109,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "pcsGroup.gridTotalActivePower",
        "address": 2600 + 111,
        "offset": 1,
        "precision": "1",
        "unit": "KW",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "pcsGroup.gridTotalReactivePower",
        "address": 2600 + 112,
        "offset": 1,
        "precision": "1",
        "unit": "Kvar",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "pcsGroup.gridPowerFactor",
        "address": 2600 + 114,
        "offset": 1,
        "precision": "0.001",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "pcsGroup.gridFrequency",
        "address": 2600 + 106,
        "offset": 1,
        "precision": "0.01",
        "unit": "Hz",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "pcsGroup.poiVoltRS",
        "address": 2600 + 124,
        "offset": 1,
        "precision": "1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "pcsGroup.poiVoltST",
        "address": 2600 + 125,
        "offset": 1,
        "precision": "1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "pcsGroup.poiVoltTR",
        "address": 2600 + 126,
        "offset": 1,
        "precision": "1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "pcsGroup.poiCurrentR",
        "address": 2600 + 127,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "pcsGroup.poiCurrentS",
        "address": 2600 + 128,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "pcsGroup.poiCurrentT",
        "address": 2600 + 129,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "pcsGroup.poiActivePower",
        "address": 2600 + 119,
        "offset": 1,
        "precision": "1",
        "unit": "KW",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "pcsGroup.poiReactivePower",
        "address": 2600 + 120,
        "offset": 1,
        "precision": "1",
        "unit": "Kvar",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "pcsGroup.poiPowerFactor",
        "address": 2600 + 122,
        "offset": 1,
        "precision": "0.001",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "pcsGroup.poiFrequency",
        "address": 2600 + 123,
        "offset": 1,
        "precision": "0.01",
        "unit": "Hz",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "pcsGroup.batteryTotalPower",
        "address": 2600 + 110,
        "offset": 1,
        "precision": "1",
        "unit": "kW",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "pcsGroup.batteryTotalCurrent",
        "address": 2600 + 115,
        "offset": 1,
        "precision": "1",
        "unit": "A",
        "valueType": "int16",
        "bitMapping": ""
    },
    #后面G3点表都没有
]

# PCS1
# 57个参数
DEVICE_PCS_MASTER_PARAMS = [
    {
        "name": "device.pcs.charge/dischargeStatus",
        "address": 2702,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "valueMapping": {
            0: "status.Charging",
            1: "status.Discharging",
        },
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
        "name": "device.pcs.gridFrequencyPcc",
        "address": 2706,
        "offset": 1,
        "precision": "0.01",
        "unit": "Hz",
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
        "name": "device.pcs.dcPower(total)",
        "address": 2710,
        "offset": 1,
        "precision": "1",
        "unit": "kW",
        "valueType": "int16",
        "bitMapping": ""
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
        "name": "device.pcs.apparentPower(total)Pcc",
        "address": 2713,
        "offset": 1,
        "precision": "1",
        "unit": "kVA",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.powerFactor(total)Pcc",
        "address": 2714,
        "offset": 1,
        "precision": "0.001",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.batteryCurrent(total)",
        "address": 2715,
        "offset": 1,
        "precision": "1",
        "unit": "A",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.dcOffsetOfPhaseRCurrent(total)",
        "address": 2716,
        "offset": 1,
        "precision": "1",
        "unit": "mA",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.dcOffsetOfPhaseSCurrent(total)",
        "address": 2717,
        "offset": 1,
        "precision": "1",
        "unit": "mA",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.dcOffsetOfPhaseTCurrent(total)",
        "address": 2718,
        "offset": 1,
        "precision": "1",
        "unit": "mA",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.activePowerPoi",
        "address": 2719,
        "offset": 1,
        "precision": "1",
        "unit": "kW",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.reactivePowerPoi",
        "address": 2720,
        "offset": 1,
        "precision": "1",
        "unit": "kW",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.apparentPowerPoi",
        "address": 2721,
        "offset": 1,
        "precision": "1",
        "unit": "kW",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.powerFactorPoi",
        "address": 2722,
        "offset": 1,
        "precision": "0.001",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridFrequencyPoi",
        "address": 2723,
        "offset": 1,
        "precision": "0.01",
        "unit": "Hz",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridVoltageRsPoi",
        "address": 2724,
        "offset": 1,
        "precision": "1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridVoltageStPoi",
        "address": 2725,
        "offset": 1,
        "precision": "1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridVoltageTrPoi",
        "address": 2726,
        "offset": 1,
        "precision": "1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridCurrentPhaseRPoi",
        "address": 2727,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridCurrentPhaseSPoi",
        "address": 2728,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridCurrentPhaseTPoi",
        "address": 2729,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridVoltageRsHv",
        "address": 2730,
        "offset": 1,
        "precision": "0.01",
        "unit": "kV",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridVoltageStHv",
        "address": 2731,
        "offset": 1,
        "precision": "0.01",
        "unit": "kV",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridVoltageTrHv",
        "address": 2732,
        "offset": 1,
        "precision": "0.01",
        "unit": "kV",
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
        "name": "device.pcs.busVoltage(j1)",
        "address": 2737,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.inductorCurrentR(j1)",
        "address": 2738,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.inductorCurrentS(j1)",
        "address": 2739,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.inductorCurrentT(j1)",
        "address": 2740,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.batteryPower(j1)",
        "address": 2741,
        "offset": 1,
        "precision": "1",
        "unit": "kW",
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
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.busVoltage(j2)",
        "address": 2744,
        "offset": 1,
        "precision": "0.1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.inductorCurrentR(j2)",
        "address": 2745,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.inductorCurrentS(j2)",
        "address": 2746,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.inductorCurrentT(j2)",
        "address": 2747,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.batteryPower(j2)",
        "address": 2748,
        "offset": 1,
        "precision": "1",
        "unit": "kW",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch1HourlyChargingCapacity",
        "address": 2664,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch1HourlyDischargingCapacity",
        "address": 2666,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch1DailyChargingCapacity",
        "address": 2668,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch1DailyDischargingCapacity",
        "address": 2670,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch1TotalChargingCapacity",
        "address": 2672,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch1TotalDischargingCapacity",
        "address": 2674,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch2HourlyChargingCapacity",
        "address": 2676,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch2HourlyDischargingCapacity",
        "address": 2678,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch2DailyChargingCapacity",
        "address": 2680,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch2DailyDischargingCapacity",
        "address": 2682,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch2TotalChargingCapacity",
        "address": 2684,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch2TotalDischargingCapacity",
        "address": 2686,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
]

# PCS2
# 57个参数
DEVICE_PCS_SLAVE_PARAMS = [
    {
        "name": "device.pcs.charge/dischargeStatus",
        "address": 3002,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "valueMapping": {
            0: "status.Charging",
            1: "status.Discharging",
        },
    },
    {
        "name": "device.pcs.gridVoltageRsPcc",
        "address": 3003,
        "offset": 1,
        "precision": "0.1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridVoltageStPcc",
        "address": 3004,
        "offset": 1,
        "precision": "0.1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridVoltageTrPcc",
        "address": 3005,
        "offset": 1,
        "precision": "0.1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridFrequencyPcc",
        "address": 3006,
        "offset": 1,
        "precision": "0.01",
        "unit": "Hz",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridCurrentPhaseR(total)Pcc",
        "address": 3007,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridCurrentPhaseS(total)Pcc",
        "address": 3008,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridCurrentPhaseT(total)Pcc",
        "address": 3009,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.dcPower(total)",
        "address": 3010,
        "offset": 1,
        "precision": "1",
        "unit": "kW",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.activePower(total)Pcc",
        "address": 3011,
        "offset": 1,
        "precision": "1",
        "unit": "kW",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.reactivePower(total)Pcc",
        "address": 3012,
        "offset": 1,
        "precision": "1",
        "unit": "kVar",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.apparentPower(total)Pcc",
        "address": 3013,
        "offset": 1,
        "precision": "1",
        "unit": "kVA",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.powerFactor(total)Pcc",
        "address": 3014,
        "offset": 1,
        "precision": "0.001",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.batteryCurrent(total)",
        "address": 3015,
        "offset": 1,
        "precision": "1",
        "unit": "A",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.dcOffsetOfPhaseRCurrent(total)",
        "address": 3016,
        "offset": 1,
        "precision": "1",
        "unit": "mA",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.dcOffsetOfPhaseSCurrent(total)",
        "address": 3017,
        "offset": 1,
        "precision": "1",
        "unit": "mA",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.dcOffsetOfPhaseTCurrent(total)",
        "address": 3018,
        "offset": 1,
        "precision": "1",
        "unit": "mA",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.activePowerPoi",
        "address": 3019,
        "offset": 1,
        "precision": "1",
        "unit": "kW",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.reactivePowerPoi",
        "address": 3020,
        "offset": 1,
        "precision": "1",
        "unit": "kW",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.apparentPowerPoi",
        "address": 3021,
        "offset": 1,
        "precision": "1",
        "unit": "kW",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.powerFactorPoi",
        "address": 3022,
        "offset": 1,
        "precision": "0.001",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridFrequencyPoi",
        "address": 3023,
        "offset": 1,
        "precision": "0.01",
        "unit": "Hz",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridVoltageRsPoi",
        "address": 3024,
        "offset": 1,
        "precision": "1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridVoltageStPoi",
        "address": 3025,
        "offset": 1,
        "precision": "1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridVoltageTrPoi",
        "address": 3026,
        "offset": 1,
        "precision": "1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridCurrentPhaseRPoi",
        "address": 3027,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridCurrentPhaseSPoi",
        "address": 3028,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridCurrentPhaseTPoi",
        "address": 3029,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridVoltageRsHv",
        "address": 3030,
        "offset": 1,
        "precision": "0.01",
        "unit": "kV",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridVoltageStHv",
        "address": 3031,
        "offset": 1,
        "precision": "0.01",
        "unit": "kV",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridVoltageTrHv",
        "address": 3032,
        "offset": 1,
        "precision": "0.01",
        "unit": "kV",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.batteryVoltage(j1)",
        "address": 3035,
        "offset": 1,
        "precision": "0.1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.batteryCurrent(j1)",
        "address": 3036,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.busVoltage(j1)",
        "address": 3037,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.inductorCurrentR(j1)",
        "address": 3038,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.inductorCurrentS(j1)",
        "address": 3039,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.inductorCurrentT(j1)",
        "address": 3040,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.batteryPower(j1)",
        "address": 3041,
        "offset": 1,
        "precision": "1",
        "unit": "kW",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.batteryVoltage(j2)",
        "address": 3042,
        "offset": 1,
        "precision": "0.1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.batteryCurrent(j2)",
        "address": 3043,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.busVoltage(j2)",
        "address": 3044,
        "offset": 1,
        "precision": "0.1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.inductorCurrentR(j2)",
        "address": 3045,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.inductorCurrentS(j2)",
        "address": 3046,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.inductorCurrentT(j2)",
        "address": 3047,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.batteryPower(j2)",
        "address": 3048,
        "offset": 1,
        "precision": "1",
        "unit": "kW",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch1HourlyChargingCapacity",
        "address": 2964,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch1HourlyDischargingCapacity",
        "address": 2966,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch1DailyChargingCapacity",
        "address": 2968,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch1DailyDischargingCapacity",
        "address": 2970,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch1TotalChargingCapacity",
        "address": 2972,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch1TotalDischargingCapacity",
        "address": 2974,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch2HourlyChargingCapacity",
        "address": 2976,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch2HourlyDischargingCapacity",
        "address": 2978,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch2DailyChargingCapacity",
        "address": 2980,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch2DailyDischargingCapacity",
        "address": 2982,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch2TotalChargingCapacity",
        "address": 2984,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch2TotalDischargingCapacity",
        "address": 2986,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
]

# PCS寄存器汇总,地址2600~2875 and 12000~12025
# /device/pcs/
DEVICE_PCS_ALL_REGS = [
    {
        "name": "device.pcs.hardwareVersion",
        "address": 2600,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.protocolVersion",
        "address": 2601,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.platformVersion",
        "address": 2602,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.releaseVersion",
        "address": 2603,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.msBoardArmVersion",
        "address": 2604,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.msBoardCdspVersion",
        "address": 2605,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.msBoardFpgaVersion",
        "address": 2606,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.msBoardSdspVersion",
        "address": 2607,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.module1BoardDspVersion",
        "address": 2608,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.module1BoardFpgaVersion",
        "address": 2609,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.module2BoardDspVersion",
        "address": 2610,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.module2BoardFpgaVersion",
        "address": 2611,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.msControlDspFaultInformationTable1",
        "address": 2623,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.msControlDspFaultInformationTable2",
        "address": 2624,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
        # "pointMapping": {
        #     0 : "alarm.ac_level5_overfrequency",
        #     1 : "alarm.ac_level1_underfrequency",
        #     2 : "alarm.ac_level2_underfrequency",
        #     3 : "alarm.ac_level3_underfrequency",
        #     4 : "alarm.ac_level4_underfrequency",
        #     5 : "alarm.ac_level5_underfrequency",
        #     6 : "alarm.freq_change_rate_high",
        #     7 : "alarm.ac_voltage_unbalance",
        #     8 : "alarm.ac_instantaneous_overvoltage",
        #     9 : "alarm.dc_level1_protection",
        #     10: "alarm.dc_level2_protection",
        #     11: "alarm.dc_level3_protection",
        #     12: "alarm.dcv_protection",
        #     13: "alarm.overmodulation_fault",
        #     14: "alarm.j1_board_fault",
        #     15: "alarm.j2_board_fault"
        # }
    },
    {
        "name": "device.pcs.msControlDspFaultInformationTable3",
        "address": 2625,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.msControlDspFaultInformationTable4",
        "address": 2626,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.msControlDspWarningInformationTable1",
        "address": 2627,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.msControlDspWarningInformationTable2",
        "address": 2628,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.msControlDspWarningInformationTable3",
        "address": 2629,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.msControlDspWarningInformationTable4",
        "address": 2630,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.msFpgaFaultInformationTable1",
        "address": 2631,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.msFpgaFaultInformationTable2",
        "address": 2632,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.msFpgaFaultInformationTable3",
        "address": 2633,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.msFpgaFaultInformationTable4",
        "address": 2634,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.msFpgaWarningInformationTable1",
        "address": 2635,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.msFpgaWarningInformationTable2",
        "address": 2636,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.msFpgaWarningInformationTable3",
        "address": 2637,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.msFpgaWarningInformationTable4",
        "address": 2638,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "alarm.arm_ctrl_dsp_comm_fault1",
        "address": 2650,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
        # "pointMapping": {
        #     0 : "alarm.socket_create_fail",
        #     1 : "alarm.bind_port_fail",
        #     2 : "alarm.listen_port_fail",
        #     3 : "alarm.accept_client_fail",
        #     4 : "alarm.connect_break",
        #     5 : "alarm.data_send_fail",
        #     6 : "alarm.data_recv_fail",
        #     7 : "alarm.data_checksum_error",
        #     8 : "alarm.comm_timeout",
        #     9 : "alarm.hardware_fault",
        #     10: "history.table.pcsGroup.reserved",
        #     11: "history.table.pcsGroup.reserved",
        #     12: "history.table.pcsGroup.reserved",
        #     13: "history.table.pcsGroup.reserved",
        #     14: "history.table.pcsGroup.reserved",
        #     15: "history.table.pcsGroup.reserved"
        # }
    },
    {
        "name": "alarm.arm_ctrl_dsp_comm_fault2",
        "address": 2651,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "alarm.arm_sys_dsp_comm_fault1",
        "address": 2652,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "alarm.arm_sys_dsp_comm_fault2",
        "address": 2653,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "alarm.arm_j1_dsp_comm_fault1",
        "address": 2654,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "alarm.arm_j1_dsp_comm_fault2",
        "address": 2655,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "alarm.arm_j2_dsp_comm_fault1",
        "address": 2656,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "alarm.arm_j2_dsp_comm_fault2",
        "address": 2657,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "alarm.arm_remote_mon_comm_fault1",
        "address": 2658,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "alarm.arm_remote_mon_comm_fault2",
        "address": 2659,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "alarm.arm_system_level_fault",
        "address": 2660,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "upgrade.step4",
        "address": 2661,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.upgradeStatus",
        "address": 2662,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "valueMapping": {
            0: "ldle",
            1: "upgrade.state.1",
            2: "upgrade.state.-1",
            3: "upgrade.state.2",
        },
    },
    {
        "name": "device.pcs.branch1HourlyChargingCapacity",
        "address": 2664,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch1HourlyDischargingCapacity",
        "address": 2666,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch1DailyChargingCapacity",
        "address": 2668,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch1DailyDischargingCapacity",
        "address": 2670,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch1TotalChargingCapacity",
        "address": 2672,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch1TotalDischargingCapacity",
        "address": 2674,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch2HourlyChargingCapacity",
        "address": 2676,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch2HourlyDischargingCapacity",
        "address": 2678,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch2DailyChargingCapacity",
        "address": 2680,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch2DailyDischargingCapacity",
        "address": 2682,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch2TotalChargingCapacity",
        "address": 2684,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.branch2TotalDischargingCapacity",
        "address": 2686,
        "offset": 2,
        "precision": "1",
        "unit": "KWH",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.systemRunStatus",
        "address": 2700,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "pointMapping": {
            0: "status.Start",
            1: "status.Shutdown",
            2: "status.Fault",
            3: "pcs.systemFaultWord.epo",
            4: "status.startup",
            5: "status.SoftShutdown",
            6: "status.insLow",
            7: "status.DeratingState"
        }
    },
    {
        "name": "device.pcs.runStage",
        "address": 2701,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "pointMapping": {
            0: "status.DcPrecharge",
            1: "status.DcClosing",
            2: "status.AcPresynchronization",
            3: "status.AcClosing",
            4: "status.ClosedLoop"
        }
    },
    {
        "name": "device.pcs.charge/dischargeStatus",
        "address": 2702,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "valueMapping": {
            0: "status.Charging",
            1: "status.Discharging",
        },
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
        "name": "device.pcs.gridFrequencyPcc",
        "address": 2706,
        "offset": 1,
        "precision": "0.01",
        "unit": "Hz",
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
        "name": "device.pcs.dcPower(total)",
        "address": 2710,
        "offset": 1,
        "precision": "1",
        "unit": "kW",
        "valueType": "int16",
        "bitMapping": ""
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
        "name": "device.pcs.apparentPower(total)Pcc",
        "address": 2713,
        "offset": 1,
        "precision": "1",
        "unit": "kVA",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.powerFactor(total)Pcc",
        "address": 2714,
        "offset": 1,
        "precision": "0.001",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.batteryCurrent(total)",
        "address": 2715,
        "offset": 1,
        "precision": "1",
        "unit": "A",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.dcOffsetOfPhaseRCurrent(total)",
        "address": 2716,
        "offset": 1,
        "precision": "1",
        "unit": "mA",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.dcOffsetOfPhaseSCurrent(total)",
        "address": 2717,
        "offset": 1,
        "precision": "1",
        "unit": "mA",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.dcOffsetOfPhaseTCurrent(total)",
        "address": 2718,
        "offset": 1,
        "precision": "1",
        "unit": "mA",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.activePowerPoi",
        "address": 2719,
        "offset": 1,
        "precision": "1",
        "unit": "kW",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.reactivePowerPoi",
        "address": 2720,
        "offset": 1,
        "precision": "1",
        "unit": "kW",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.apparentPowerPoi",
        "address": 2721,
        "offset": 1,
        "precision": "1",
        "unit": "kW",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.powerFactorPoi",
        "address": 2722,
        "offset": 1,
        "precision": "0.001",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridFrequencyPoi",
        "address": 2723,
        "offset": 1,
        "precision": "0.01",
        "unit": "Hz",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridVoltageRsPoi",
        "address": 2724,
        "offset": 1,
        "precision": "1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridVoltageStPoi",
        "address": 2725,
        "offset": 1,
        "precision": "1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridVoltageTrPoi",
        "address": 2726,
        "offset": 1,
        "precision": "1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridCurrentPhaseRPoi",
        "address": 2727,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridCurrentPhaseSPoi",
        "address": 2728,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridCurrentPhaseTPoi",
        "address": 2729,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridVoltageRsHv",
        "address": 2730,
        "offset": 1,
        "precision": "0.01",
        "unit": "kV",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridVoltageStHv",
        "address": 2731,
        "offset": 1,
        "precision": "0.01",
        "unit": "kV",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridVoltageTrHv",
        "address": 2732,
        "offset": 1,
        "precision": "0.01",
        "unit": "kV",
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
        "name": "device.pcs.busVoltage(j1)",
        "address": 2737,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.inductorCurrentR(j1)",
        "address": 2738,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.inductorCurrentS(j1)",
        "address": 2739,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.inductorCurrentT(j1)",
        "address": 2740,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.batteryPower(j1)",
        "address": 2741,
        "offset": 1,
        "precision": "1",
        "unit": "kW",
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
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.busVoltage(j2)",
        "address": 2744,
        "offset": 1,
        "precision": "0.1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.inductorCurrentR(j2)",
        "address": 2745,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.inductorCurrentS(j2)",
        "address": 2746,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.inductorCurrentT(j2)",
        "address": 2747,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.batteryPower(j2)",
        "address": 2748,
        "offset": 1,
        "precision": "1",
        "unit": "kW",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.dspFaultInformationTable1",
        "address": 2752,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.dspFaultInformationTable2",
        "address": 2753,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.dspFaultInformationTable3",
        "address": 2754,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.dspFaultInformationTable4",
        "address": 2755,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.fpgaFaultInformationTable1",
        "address": 2756,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.fpgaFaultInformationTable2",
        "address": 2757,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.fpgaFaultInformationTable3",
        "address": 2758,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.fpgaFaultInformationTable4",
        "address": 2759,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.fpga2FaultInformationTable1",
        "address": 2760,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.fpga2FaultInformationTable2",
        "address": 2761,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.fpga2FaultInformationTable3",
        "address": 2762,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.fpga2FaultInformationTable4",
        "address": 2763,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.dspWarningInformationTable1",
        "address": 2764,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.dspWarningInformationTable2",
        "address": 2765,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.dspWarningInformationTable3",
        "address": 2766,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.dspWarningInformationTable4",
        "address": 2767,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.fpgaWarningInformationTable1",
        "address": 2768,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.fpgaWarningInformationTable2",
        "address": 2769,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.fpgaWarningInformationTable3",
        "address": 2770,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.fpgaWarningInformationTable4",
        "address": 2771,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.CircuitBreakerStatus",
        "address": 2772,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.dryContact1",
        "address": 2773,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.dryContact2",
        "address": 2774,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.dryContact3",
        "address": 2775,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.dryContact4",
        "address": 2776,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.IMD SoftwareVersion",
        "address": 2777,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.inductorCurrentR-phase",
        "address": 2800,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.inductorCurrentS-phase",
        "address": 2801,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.inductorCurrentT-phase",
        "address": 2802,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.batteryCurrent",
        "address": 2803,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.positiveBusVoltage",
        "address": 2804,
        "offset": 1,
        "precision": "0.1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.negativeBusVoltage",
        "address": 2805,
        "offset": 1,
        "precision": "0.1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.batteryVoltage",
        "address": 2806,
        "offset": 1,
        "precision": "0.1",
        "unit": "V",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.mainFanCurrent",
        "address": 2807,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.disturbanceFanCurrent",
        "address": 2808,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.capacitorFanCurrent",
        "address": 2809,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.capacitorCurrentR-phase",
        "address": 2810,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.capacitorCurrentT-phase",
        "address": 2811,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridCurrentR-phase",
        "address": 2812,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.gridCurrentT-phase",
        "address": 2813,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.dcBusVoltage",
        "address": 2814,
        "offset": 1,
        "precision": "0.1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.dcPower",
        "address": 2815,
        "offset": 1,
        "precision": "1",
        "unit": "KW",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.iso1rp",
        "address": 2816,
        "offset": 1,
        "precision": "1",
        "unit": "k",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.iso1rn",
        "address": 2817,
        "offset": 1,
        "precision": "1",
        "unit": "k",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.iso2rp",
        "address": 2818,
        "offset": 1,
        "precision": "1",
        "unit": "k",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.iso2rn",
        "address": 2819,
        "offset": 1,
        "precision": "1",
        "unit": "k",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.r-phaseModuleFanSpeed",
        "address": 2830,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.s-phaseModuleFanSpeed",
        "address": 2831,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.t-phaseModuleFanSpeed",
        "address": 2832,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.internalAmbientTemperature",
        "address": 2833,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.externalAmbientTemperature",
        "address": 2834,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.acCapacitorTemperature",
        "address": 2835,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.dcCapacitorTemperature",
        "address": 2836,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.dcFuseTemperature",
        "address": 2837,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.maximumIgbtTemperature",
        "address": 2838,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.ntcTemperatureOfJBoard",
        "address": 2839,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfR-phaseIgbt1",
        "address": 2840,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfR-phaseIgbt2",
        "address": 2841,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfR-phaseIgbt3",
        "address": 2842,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfR-phaseIgbt4",
        "address": 2843,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfR-phaseIgbt5",
        "address": 2844,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfR-phaseIgbt6",
        "address": 2845,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfR-phaseIgbt7",
        "address": 2846,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfR-phaseIgbt8",
        "address": 2847,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfR-phaseIgbt9",
        "address": 2848,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfR-phaseIgbt10",
        "address": 2849,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfR-phaseIgbt11",
        "address": 2850,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfR-phaseIgbt12",
        "address": 2851,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfS-phaseIgbt1",
        "address": 2852,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfS-phaseIgbt2",
        "address": 2853,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfS-phaseIgbt3",
        "address": 2854,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfS-phaseIgbt4",
        "address": 2855,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfS-phaseIgbt5",
        "address": 2856,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfS-phaseIgbt6",
        "address": 2857,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfS-phaseIgbt7",
        "address": 2858,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfS-phaseIgbt8",
        "address": 2859,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfS-phaseIgbt9",
        "address": 2860,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfS-phaseIgbt10",
        "address": 2861,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfS-phaseIgbt11",
        "address": 2862,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfS-phaseIgbt12",
        "address": 2863,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfT-phaseIgbt1",
        "address": 2864,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfT-phaseIgbt2",
        "address": 2865,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfT-phaseIgbt3",
        "address": 2866,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfT-phaseIgbt4",
        "address": 2867,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfT-phaseIgbt5",
        "address": 2868,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfT-phaseIgbt6",
        "address": 2869,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfT-phaseIgbt7",
        "address": 2870,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfT-phaseIgbt8",
        "address": 2871,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfT-phaseIgbt9",
        "address": 2872,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfT-phaseIgbt10",
        "address": 2873,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfT-phaseIgbt11",
        "address": 2874,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.temperatureOfT-phaseIgbt12",
        "address": 2875,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "int16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.parallelMode",
        "address": 12000,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.power-onCommand",
        "address": 12001,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.on-grid/Off-gridConfiguration",
        "address": 12002,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.operationMode",
        "address": 12003,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.activePowerSetpoint",
        "address": 12004,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.dischargeEnable",
        "address": 12005,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.chargeEnable",
        "address": 12006,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.faultClear",
        "address": 12007,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.reset",
        "address": 12008,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.master-slaveModeSetting",
        "address": 12009,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.singleBusEnable",
        "address": 12010,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.maximumChargingVoltage",
        "address": 12011,
        "offset": 1,
        "precision": "0.1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.minimumDischargingVoltage",
        "address": 12012,
        "offset": 1,
        "precision": "0.1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.maximumChargingCurrent",
        "address": 12013,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.maximumDischargingCurrent",
        "address": 12014,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.vfVoltageSetpoint",
        "address": 12015,
        "offset": 1,
        "precision": "0.1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.vfFrequencySetpoint",
        "address": 12016,
        "offset": 1,
        "precision": "0.01",
        "unit": "Hz",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.vsgVoltageSetpoint",
        "address": 12017,
        "offset": 1,
        "precision": "0.1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.vsgFrequencySetpoint",
        "address": 12018,
        "offset": 1,
        "precision": "0.01",
        "unit": "Hz",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.vsgActivePowerSetpoint",
        "address": 12019,
        "offset": 1,
        "precision": "1",
        "unit": "kW",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.vsgReactivePowerSetpoint",
        "address": 12020,
        "offset": 1,
        "precision": "1",
        "unit": "kVar",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.cp_dcPowerSetpoint",
        "address": 12021,
        "offset": 1,
        "precision": "1",
        "unit": "kW",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.cc_dcCurrentSetpoint",
        "address": 12022,
        "offset": 1,
        "precision": "1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.cv_dcVoltageSetpoint",
        "address": 12023,
        "offset": 1,
        "precision": "0.1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.afeVoltageSetpoint",
        "address": 12024,
        "offset": 1,
        "precision": "0.1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "device.pcs.short-circuitLoopSetpoint",
        "address": 12025,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    }
]
