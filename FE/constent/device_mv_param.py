# ===================== 中压系统相关参数 ====================
# transformer,3个参数
ELECTRA_TRANSFORMER_PARAMS = [
    {
        "name": "mv.transformer.TransformerOilSurfaceTemperatureCircuit1",
        "address": 25000 + 0,
        "offset": 2,
        "precision": "1",
        "unit": "°C",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.transformer.Channel1Temperature",
        "address": 25000 + 4,
        "offset": 2,
        "precision": "1",
        "unit": "°C",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.transformer.Channel1Humidity",
        "address": 25000 + 6,
        "offset": 2,
        "precision": "1",
        "unit": "°C",
        "valueType": "float",
        "bitMapping": ""
    },
]

# meter,37个参数
ELECTRA_METER_PARAMS = [
    {
        "name": "mv.meter.phaseAVoltage",
        "address": 25300 + 0,
        "offset": 2,
        "precision": "1",
        "unit": "V",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.phaseBVoltage",
        "address": 25300 + 2,
        "offset": 2,
        "precision": "1",
        "unit": "V",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.phaseCVoltage",
        "address": 25300 + 4,
        "offset": 2,
        "precision": "1",
        "unit": "V",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.lineVoltageAB",
        "address": 25300 + 6,
        "offset": 2,
        "precision": "1",
        "unit": "V",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.lineVoltageBC",
        "address": 25300 + 8,
        "offset": 2,
        "precision": "1",
        "unit": "V",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.lineVoltageCA",
        "address": 25300 + 10,
        "offset": 2,
        "precision": "1",
        "unit": "V",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.phaseACurrent",
        "address": 25300 + 12,
        "offset": 2,
        "precision": "1",
        "unit": "A",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.phaseBCurrent",
        "address": 25300 + 14,
        "offset": 2,
        "precision": "1",
        "unit": "A",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.phaseCCurrent",
        "address": 25300 + 16,
        "offset": 2,
        "precision": "1",
        "unit": "A",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.neutralCurrent",
        "address": 25300 + 18,
        "offset": 2,
        "precision": "1",
        "unit": "A",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.phaseAActivePower",
        "address": 25300 + 20,
        "offset": 2,
        "precision": "1",
        "unit": "kW",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.phaseBActivePower",
        "address": 25300 + 22,
        "offset": 2,
        "precision": "1",
        "unit": "kW",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.phaseCActivePower",
        "address": 25300 + 24,
        "offset": 2,
        "precision": "1",
        "unit": "kW",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.totalActivePower",
        "address": 25300 + 26,
        "offset": 2,
        "precision": "1",
        "unit": "kW",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.phaseAReactivePower",
        "address": 25300 + 28,
        "offset": 2,
        "precision": "1",
        "unit": "kVar",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.phaseBReactivePower",
        "address": 25300 + 30,
        "offset": 2,
        "precision": "1",
        "unit": "kVar",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.phaseCReactivePower",
        "address": 25300 + 32,
        "offset": 2,
        "precision": "1",
        "unit": "kVar",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.totalReactivePower",
        "address": 25300 + 34,
        "offset": 2,
        "precision": "1",
        "unit": "kVar",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.phaseAApparentPower",
        "address": 25300 + 36,
        "offset": 2,
        "precision": "1",
        "unit": "kVA",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.phaseBApparentPower",
        "address": 25300 + 38,
        "offset": 2,
        "precision": "1",
        "unit": "kVA",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.phaseCApparentPower",
        "address": 25300 + 40,
        "offset": 2,
        "precision": "1",
        "unit": "kVA",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.totalApparentPower",
        "address": 25300 + 42,
        "offset": 2,
        "precision": "1",
        "unit": "kVA",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.phaseAPowerFactor",
        "address": 25300 + 44,
        "offset": 2,
        "precision": "1",
        "unit": "",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.phaseBPowerFactor",
        "address": 25300 + 46,
        "offset": 2,
        "precision": "1",
        "unit": "",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.phaseCPowerFactor",
        "address": 25300 + 48,
        "offset": 2,
        "precision": "1",
        "unit": "",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.totalPowerFactor",
        "address": 25300 + 50,
        "offset": 2,
        "precision": "1",
        "unit": "",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.frequency",
        "address": 25300 + 52,
        "offset": 2,
        "precision": "1",
        "unit": "Hz",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.averagePhaseVoltage",
        "address": 25300 + 54,
        "offset": 2,
        "precision": "1",
        "unit": "V",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.averageLineVoltage",
        "address": 25300 + 56,
        "offset": 2,
        "precision": "1",
        "unit": "V",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.averageCurrent",
        "address": 25300 + 58,
        "offset": 2,
        "precision": "1",
        "unit": "A",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.totalActiveEnergySecondary",
        "address": 25300 + 60,
        "offset": 2,
        "precision": "1",
        "unit": "kWh",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.totalActiveEnergySecondary",
        "address": 25300 + 60,
        "offset": 2,
        "precision": "1",
        "unit": "kWh",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.forwardActiveEnergySecondary",
        "address": 25300 + 62,
        "offset": 2,
        "precision": "1",
        "unit": "kWh",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.reverseActiveEnergySecondary",
        "address": 25300 + 64,
        "offset": 2,
        "precision": "1",
        "unit": "kWh",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.totalReactiveEnergySecondary",
        "address": 25300 + 66,
        "offset": 2,
        "precision": "1",
        "unit": "kVar",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.forwardReactiveEnergySecondary",
        "address": 25300 + 68,
        "offset": 2,
        "precision": "1",
        "unit": "kVar",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.reverseReactiveEnergySecondary",
        "address": 25300 + 70,
        "offset": 2,
        "precision": "1",
        "unit": "kVar",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.meter.apparentEnergySecondary",
        "address": 25300 + 72,
        "offset": 2,
        "precision": "1",
        "unit": "kVA",
        "valueType": "float",
        "bitMapping": ""
    }
]

# HVIP,10个参数
ELECTRA_HVIP_PARAMS = [
    {
        "name": "mv.rmu.phaseCurrentI1",
        "address": 25800 + 0,
        "offset": 2,
        "precision": "1",
        "unit": "A",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.rmu.phaseCurrentI2",
        "address": 25800 + 2,
        "offset": 2,
        "precision": "1",
        "unit": "A",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.rmu.phaseCurrentI3",
        "address": 25800 + 4,
        "offset": 2,
        "precision": "1",
        "unit": "A",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.rmu.earthFaultCurrentI0",
        "address": 25800 + 6,
        "offset": 2,
        "precision": "1",
        "unit": "A",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.rmu.phaseDemandCurrentIm1",
        "address": 25800 + 10,
        "offset": 2,
        "precision": "1",
        "unit": "A",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.rmu.phaseDemandCurrentIm2",
        "address": 25800 + 12,
        "offset": 2,
        "precision": "1",
        "unit": "A",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.rmu.phaseDemandCurrentIm3",
        "address": 25800 + 14,
        "offset": 2,
        "precision": "1",
        "unit": "A",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.rmu.phasePeakDemandCurrentIM1",
        "address": 25800 + 16,
        "offset": 2,
        "precision": "1",
        "unit": "A",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.rmu.phasePeakDemandCurrentIM2",
        "address": 25800 + 18,
        "offset": 2,
        "precision": "1",
        "unit": "A",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.rmu.phasePeakDemandCurrentIM3",
        "address": 25800 + 20,
        "offset": 2,
        "precision": "1",
        "unit": "A",
        "valueType": "float",
        "bitMapping": ""
    }
]

# UPS, 29个参数
ELECTRA_UPS_PARAMS = [
    {
        "name": "mv.ups.batteryCurrent",
        "address": 27100 + 0,
        "offset": 1,
        "precision": "0.1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.ups.lineVoltage",
        "address": 27100 + 1,
        "offset": 1,
        "precision": "0.1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.ups.inputFrequency",
        "address": 27100 + 2,
        "offset": 1,
        "precision": "0.1",
        "unit": "Hz",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.ups.outputVoltage",
        "address": 27100 + 3,
        "offset": 1,
        "precision": "0.1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.ups.outputFrequency",
        "address": 27100 + 4,
        "offset": 1,
        "precision": "0.01",
        "unit": "Hz",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.ups.outputCurrent",
        "address": 27100 + 5,
        "offset": 1,
        "precision": "0.01",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.ups.outputLoadPercent",
        "address": 27100 + 6,
        "offset": 1,
        "precision": "0.1",
        "unit": "%",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.ups.batteryVoltageP",
        "address": 27100 + 7,
        "offset": 1,
        "precision": "0.1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.ups.upsInternalTemperature",
        "address": 27100 + 8,
        "offset": 1,
        "precision": "0.1",
        "unit": "°C",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.ups.upsStatus",
        "address": 27100 + 9,
        "offset": 2,
        "precision": "1",
        "unit": "",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "mv.ups.batteryCapacity",
        "address": 27100 + 11,
        "offset": 1,
        "precision": "0.1",
        "unit": "%",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.ups.batteryRemainTime",
        "address": 27100 + 12,
        "offset": 1,
        "precision": "1",
        "unit": "miniutes",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.ups.upsModeInquiry",
        "address": 27100 + 13,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.ups.unitBatteryCapacity",
        "address": 27100 + 14,
        "offset": 1,
        "precision": "1",
        "unit": "AH",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.ups.faultKind",
        "address": 27100 + 15,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.ups.batteryPieceNumber",
        "address": 27100 + 16,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.ups.inputPhase",
        "address": 27100 + 17,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.ups.outputPhase",
        "address": 27100 + 18,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.ups.nominalInputVoltage",
        "address": 27100 + 19,
        "offset": 1,
        "precision": "1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.ups.nominalOutputVoltage",
        "address": 27100 + 20,
        "offset": 1,
        "precision": "1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.ups.outputRatedVA",
        "address": 27100 + 21,
        "offset": 2,
        "precision": "1",
        "unit": "VA",
        "valueType": "uint32",
        "bitMapping": ""
    },
    {
        "name": "mv.ups.batteryVoltage",
        "address": 27100 + 23,
        "offset": 1,
        "precision": "0.1",
        "unit": "V",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.ups.ratingOutputCurrent",
        "address": 27100 + 24,
        "offset": 1,
        "precision": "1",
        "unit": "A",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.ups.ratingOutputFrequency",
        "address": 27100 + 25,
        "offset": 1,
        "precision": "0.1",
        "unit": "Hz",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.ups.alarmWord1",
        "address": 27100 + 29,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.ups.alarmWord2",
        "address": 27100 + 30,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.ups.alarmWord3",
        "address": 27100 + 31,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.ups.alarmWord4",
        "address": 27100 + 32,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.ups.alarmWord5",
        "address": 27100 + 33,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    }
]

# measure,130个参数
ELECTRA_MC_PARAMS = [
    {
        "name": "mv.measure.tripSummaryTotal",
        "address": 27300 + 0,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.alarmSummaryTotal",
        "address": 27300 + 1,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.realTimeTripTotal",
        "address": 27300 + 2,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.realTimeAlarmTotal",
        "address": 27300 + 3,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.deviceFaultTotal",
        "address": 27300 + 4,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.di1",
        "address": 27300 + 5,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.di2",
        "address": 27300 + 6,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.di3",
        "address": 27300 + 7,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.auxiliaryTransformerOvertemperatureTrip",
        "address": 27300 + 8,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.transformerOilLevelUltraLowTripSignal",
        "address": 27300 + 9,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.transformerHighTemperatureAlarmSignal",
        "address": 27300 + 10,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.transformerOvertemperatureTripSignal",
        "address": 27300 + 11,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.transformerLightGasAlarmSignal",
        "address": 27300 + 12,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.transformerHeavyGasTripSignal",
        "address": 27300 + 13,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.pressureReliefValveActionSignal",
        "address": 27300 + 14,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.highVoltageCabinetOpeningWithoutTripping",
        "address": 27300 + 15,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.smokeAlarmSignal",
        "address": 27300 + 16,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.windingOvertemperatureTripSignalReserve",
        "address": 27300 + 17,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.doorOpeningSignal",
        "address": 27300 + 18,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.g1LoadSwitchClosingSignal",
        "address": 27300 + 19,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.g1LoadSwitchOpeningSignal",
        "address": 27300 + 20,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.g1GroundingSwitchClosingSignal",
        "address": 27300 + 21,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.g3LoadSwitchClosingSignal",
        "address": 27300 + 22,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.g3LoadSwitchOpeningSignal",
        "address": 27300 + 23,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.g3GroundingSwitchClosingSignal",
        "address": 27300 + 24,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.emergencyTrippingSignal",
        "address": 27300 + 25,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.g2CircuitBreakerClosingSignal",
        "address": 27300 + 26,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.g2CircuitBreakerOpeningSignal",
        "address": 27300 + 27,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.g2CircuitBreakerSpringStoredEnergySignal",
        "address": 27300 + 28,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.g2IsolationSwitchClosingSignal",
        "address": 27300 + 29,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.g2CircuitBreakersAllowRemoteOperationSignal",
        "address": 27300 + 30,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.di27",
        "address": 27300 + 31,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.di28",
        "address": 27300 + 32,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.g2IsolationSwitchOpeningSignal",
        "address": 27300 + 33,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.g2GroundingSwitchClosingSignal",
        "address": 27300 + 34,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.rmuLowPressureAlarmSignal",
        "address": 27300 + 35,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.di33",
        "address": 27300 + 37,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.di34",
        "address": 27300 + 38,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.di35",
        "address": 27300 + 39,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.di36",
        "address": 27300 + 40,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.di37",
        "address": 27300 + 41,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.di38",
        "address": 27300 + 42,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    # 预留 空调告警
    {
        "name": "mv.measure.upsInputPowerLoss",
        "address": 27300 + 45,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.transformerLowOilLevelAlarmSignal",
        "address": 27300 + 46,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.di43",
        "address": 27300 + 47,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.di44",
        "address": 27300 + 48,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.g1GroundingSwitchOpeningSignal",
        "address": 27300 + 49,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.di46",
        "address": 27300 + 50,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.g2GroundingSwitchOpeningSignal",
        "address": 27300 + 51,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.g3GroundingSwitchOpeningSignal",
        "address": 27300 + 52,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    # 预留 绕组高温报警信号
    {
        "name": "mv.measure.pcs1FaultSignal",
        "address": 27300 + 55,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.pcs2FaultSignal",
        "address": 27300 + 56,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.pcs3FaultSignal",
        "address": 27300 + 57,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.pcs4FaultSignal",
        "address": 27300 + 58,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.di55",
        "address": 27300 + 59,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.di56",
        "address": 27300 + 60,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.di57",
        "address": 27300 + 61,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.di58",
        "address": 27300 + 62,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.di59",
        "address": 27300 + 63,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.di60",
        "address": 27300 + 64,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.di61",
        "address": 27300 + 65,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.di62",
        "address": 27300 + 66,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.di63",
        "address": 27300 + 67,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.nonCapacity6Action",
        "address": 27300 + 69,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.nonCapacity7Action",
        "address": 27300 + 70,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.nonCapacity8Action",
        "address": 27300 + 71,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.nonCapacity9Action",
        "address": 27300 + 72,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.nonCapacity10Action",
        "address": 27300 + 73,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.nonCapacity11Action",
        "address": 27300 + 74,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.nonCapacity12Action",
        "address": 27300 + 75,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.nonCapacity13Action",
        "address": 27300 + 76,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.nonCapacity1Action",
        "address": 27300 + 77,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.nonCapacity2Action",
        "address": 27300 + 78,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.nonCapacity3Action",
        "address": 27300 + 79,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.nonCapacity4Action",
        "address": 27300 + 80,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.nonCapacity5Action",
        "address": 27300 + 81,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.nonCapacity14Action",
        "address": 27300 + 82,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.nonCapacity15Action",
        "address": 27300 + 83,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.nonCapacity16Action",
        "address": 27300 + 84,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.primarySideOvercurrentStage3",
        "address": 27300 + 85,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.primarySideZeroSequenceOvercurrentStage1",
        "address": 27300 + 86,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.primarySideZeroSequenceOvercurrentStage2",
        "address": 27300 + 87,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.primarySideInverseTimeOvercurrent",
        "address": 27300 + 88,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.primarySideZeroSequenceInverseTimeOvercurrent",
        "address": 27300 + 89,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.primarySideNegativeSequenceOvercurrent",
        "address": 27300 + 90,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.primarySideOvervoltage",
        "address": 27300 + 91,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.primarySideZeroSequenceOvervoltage",
        "address": 27300 + 92,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.differentialCurrentQuickTrip",
        "address": 27300 + 93,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.percentageDifferentialProtection",
        "address": 27300 + 94,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.differentialCurrentExceedingLimitAlarm",
        "address": 27300 + 95,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.ctAbnormalityAlarm",
        "address": 27300 + 96,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.primarySideOvercurrentStage1",
        "address": 27300 + 97,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.primarySideOvercurrentStage2",
        "address": 27300 + 98,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.secondarySideOvercurrentStage1",
        "address": 27300 + 99,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.secondarySideOvercurrentStage2",
        "address": 27300 + 100,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.secondarySideOvercurrentStage3",
        "address": 27300 + 101,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.secondarySideZeroSequenceOvercurrentStage1",
        "address": 27300 + 102,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.secondarySideZeroSequenceOvercurrentStage2",
        "address": 27300 + 103,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.primarySideUndervoltage",
        "address": 27300 + 104,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.primarySidePtCircuitBroken",
        "address": 27300 + 105,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.primarySideCtCircuitBroken",
        "address": 27300 + 106,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.primarySideOverload",
        "address": 27300 + 107,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.primarySideNegativeSequenceOvervoltage",
        "address": 27300 + 108,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.secondarySideOverload",
        "address": 27300 + 109,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.secondarySideNegativeSequenceOvervoltage",
        "address": 27300 + 110,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.secondarySideInverseTimeOvercurrent",
        "address": 27300 + 111,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.secondarySideZeroSequenceInverseTimeOvercurrent",
        "address": 27300 + 112,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.secondarySideNegativeSequenceOvercurrent",
        "address": 27300 + 113,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.secondarySideOvervoltage",
        "address": 27300 + 114,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.secondarySideZeroSequenceOvervoltage",
        "address": 27300 + 115,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.secondarySideUndervoltage",
        "address": 27300 + 116,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.secondarySidePtCircuitBroken",
        "address": 27300 + 117,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.secondarySideCtCircuitBroken",
        "address": 27300 + 118,
        "offset": 1,
        "precision": "1",
        "unit": "",
        "valueType": "uint16",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.pcs12PhaseAVoltage",
        "address": 27300 + 150,
        "offset": 2,
        "precision": "1",
        "unit": "V",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.pcs12PhaseBVoltage",
        "address": 27300 + 152,
        "offset": 2,
        "precision": "1",
        "unit": "V",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.pcs12PhaseCVoltage",
        "address": 27300 + 154,
        "offset": 2,
        "precision": "1",
        "unit": "V",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.pcs12LineVoltageAB",
        "address": 27300 + 156,
        "offset": 2,
        "precision": "1",
        "unit": "V",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.pcs12LineVoltageBC",
        "address": 27300 + 158,
        "offset": 2,
        "precision": "1",
        "unit": "V",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.pcs12LineVoltageCA",
        "address": 27300 + 160,
        "offset": 2,
        "precision": "1",
        "unit": "V",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.systemFrequency",
        "address": 27300 + 162,
        "offset": 2,
        "precision": "1",
        "unit": "Hz",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.pcs34PhaseAVoltage",
        "address": 27300 + 164,
        "offset": 2,
        "precision": "1",
        "unit": "V",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.pcs34PhaseBVoltage",
        "address": 27300 + 166,
        "offset": 2,
        "precision": "1",
        "unit": "V",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.pcs34PhaseCVoltage",
        "address": 27300 + 168,
        "offset": 2,
        "precision": "1",
        "unit": "V",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.pcs34LineVoltageAB",
        "address": 27300 + 170,
        "offset": 2,
        "precision": "1",
        "unit": "V",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.pcs34LineVoltageBC",
        "address": 27300 + 172,
        "offset": 2,
        "precision": "1",
        "unit": "V",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.pcs34LineVoltageCA",
        "address": 27300 + 174,
        "offset": 2,
        "precision": "1",
        "unit": "V",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.phaseADifferentialCurrent",
        "address": 27300 + 176,
        "offset": 2,
        "precision": "1",
        "unit": "A",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.phaseBDifferentialCurrent",
        "address": 27300 + 178,
        "offset": 2,
        "precision": "1",
        "unit": "A",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.phaseCDifferentialCurrent",
        "address": 27300 + 180,
        "offset": 2,
        "precision": "1",
        "unit": "A",
        "valueType": "float",
        "bitMapping": ""
    },
    {
        "name": "mv.measure.pt100TransformerHighTemperature",
        "address": 27300 + 182,
        "offset": 2,
        "precision": "1",
        "unit": "°C",
        "valueType": "float",
        "bitMapping": ""
    }
]
