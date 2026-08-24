

# ========================== PARAM CONFIG ===========================
PCS_CONFIG_PARAM_GAP = 700
# 特殊点位,按钮和文本共享一个寄存器
PCS_REACTIVE_POWER_MODE_ADDR = 12261
# ================ #
#     HOLDPUT      #
# ================ #
SYSTECMCTL_POWER = [
  {
    "moduleName": "Systecm Control",
    "params": {
      "buttom": [
       {
        "address": 6,
        "name": "Power on",
        "sort": "1",
        "eValue": "3",
        "rule": []
        },
       {
        "address": 6,
        "name": "Power off",
        "sort": "2",
        "eValue": "4",
        "rule": []
        },
      ],
      "text": [
        {
          "address": 1010,
          "name": "ActivePower",
          "sort": "1",
          "maxValue": "11000",
          "minValue": "-11000",
          "precision": "1",
          "unit": "kW",
          "valueType": "int16"
        },
        {
          "address": 1011,
          "name": "ReactivePower",
          "sort": "2",
          "maxValue": "11000",
          "minValue": "-11000",
          "precision": "1",
          "unit": "kVar",
          "valueType": "int16"
        },
      ]
    }
  }
]

RUNPARASETTING_PCSSETTING = [
    # 模块
  {
    "moduleName": "module.deviceControl",
    "params": {
      "buttom": [
       {
        "address": 12001,
        "name": "commands.pcs.power-off",
        "sort": "1",
        "eValue": "0",
        "rule": [12001]
        },
       {
        "address": 12001,
        "name": "commands.pcs.power-on",
        "sort": "2",
        "eValue": "1",
        "rule": [12001, 12008]
        },
       {
        "address": 12001,
        "name": "commands.pcs.standby",
        "sort": "3",
        "eValue": "2",
        "rule": [12001]
        },
       {
        "address": 12007,
        "name": "commands.pcs.faultClear",
        "sort": "4",
        "eValue": "1",
        "rule": [12008]
        },
       {
        "address": 12008,
        "name": "commands.pcs.reset",
        "sort": "5",
        "eValue": "1",
        "rule": [12007, 12001]
        }
      ]
    }
  },
  {
    "moduleName": "module.PowerControl",
    "params": {
      "buttom": [
       {
        "address": 12003,
        "name": "commands.pcs.PQmodel",
        "sort": "1",
        "eValue": "3",
        "rule": [12261]
        },
        # PCS方暂未确定
       {
        "address": 12261,
        "name": "commands.pcs.PFmode",
        "sort": "2",
        "eValue": "1",
        "rule": []
        },
      ],
      "text": [
        {
          "address": 12004,
          "name": "device.pcs.activePowerSetpoint",
          "sort": "1",
          "maxValue": "5175",
          "minValue": "-5175",
          "precision": "1",
          "unit": "kW",
          "valueType": "int16"
        },
        # G3 PCS没有开放无功功率给定,通过功率因数下发
        {
          "address": 12263,
          "name": "device.pcs.FixedCosphi",
          "sort": "2",
          "maxValue": "1000",
          "minValue": "-1000",
          "precision": "0.001",
          "unit": "",
          "valueType": "uint16"
        },
        {
          "address": 12033,
          "name": "device.pcs.Battery1DischargeDistributionCoefficient",
          "sort": "3",
          "maxValue": "1000",
          "minValue": "0",
          "precision": "0.001",
          "unit": "",
          "valueType": "uint16"
        },
        {
          "address": 12034,
          "name": "device.pcs.Battery1ChargeDistributionCoefficient",
          "sort": "4",
          "maxValue": "1000",
          "minValue": "0",
          "precision": "0.001",
          "unit": "",
          "valueType": "uint16"
        },
        {
          "address": 12035,
          "name": "device.pcs.Battery2DischargeDistributionCoefficient",
          "sort": "5",
          "maxValue": "1000",
          "minValue": "0",
          "precision": "0.001",
          "unit": "",
          "valueType": "uint16"
        },
        {
          "address": 12036,
          "name": "device.pcs.Battery2ChargeDistributionCoefficient",
          "sort": "6",
          "maxValue": "1000",
          "minValue": "0",
          "precision": "0.001",
          "unit": "",
          "valueType": "uint16"
        }
      ]
    }
  },
  {
    "moduleName": "module.function",
    "params": {
      "buttom": [
       {
        "address": 12028,
        "name": "commands.pcs.ZeroPowerStandbyEnable",
        "sort": "1",
        "eValue": "1",
        "rule": [12028]
        },
       {
        "address": 12028,
        "name": "commands.pcs.ZeroPowerStandbyDisable",
        "sort": "2",
        "eValue": "0",
        "rule": [12028]
        },
       {
        "address": 12027,
        "name": "commands.pcs.BlackStartEnable",
        "sort": "3",
        "eValue": "1",
        "rule": [PCS_REACTIVE_POWER_MODE_ADDR]
        },
        # 无功模式 bit0
       {
        "address": PCS_REACTIVE_POWER_MODE_ADDR,
        "name": "commands.pcs.ReactivePowerEnable",
        "sort": "4",
        "eValue": "1",
        "rule": [12027]
        }
      ],
      # 无功模式 bit1~bit3
      "text": [
        {
          "address": PCS_REACTIVE_POWER_MODE_ADDR,
          "name": "device.pcs.activePowerSetpoint",
          "sort": "1",
          "maxValue": "14",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "uint16"
        }
        ]
    }
  },
  {
    "moduleName": "module.ProtectionParam",
    "params": {
      "buttom": [
       {
        "address": 12006,
        "name": "commands.pcs.ChargeEnable",
        "sort": "1",
        "eValue": "1",
        "rule": [12005]
        },
       {
        "address": 12005,
        "name": "commands.pcs.DischargeEnable",
        "sort": "2",
        "eValue": "1",
        "rule": [12006]
        }
      ]
    }
  },
  # 其他
  {
    "moduleName": "module.ProtectionParam",
    "params": {
      "buttom": [
       {
        "address": 12167,
        "name": "commands.pcs.RoCoFDisable",
        "sort": "1",
        "eValue": "0",
        "rule": [12167]
        }
      ]
      # G3点表没有这个模块的文本参数
    }
  },
]

RUNPARASETTING_PARAGALIBRATION = [
  {
    "moduleName": "module.deviceControl",
    "params": {
      "buttom": [
       {
        "address": 12009,
        "name": "commands.pcs.MasterModeSetting",
        "sort": "1",
        "eValue": "0",
        "rule": [12009]
        },
       {
        "address": 12009,
        "name": "commands.pcs.SlaveModeSetting",
        "sort": "2",
        "eValue": "1",
        "rule": [12009]
        }
      ]
    }
  },
  {
    "moduleName": "module.ParameterCalibration",
    "params": {
      "text": [
        {
          "address": 12396,
          "name": "device.pcs.PCCDischargeActivePowerCalibrationK",
          "sort": "1",
          "maxValue": "11000",
          "minValue": "9000",
          "precision": "0.0001",
          "unit": "",
          "valueType": "uint16"
        },
        {
          "address": 12397,
          "name": "device.pcs.PCCDischargeReactivePowerCalibrationK",
          "sort": "2",
          "maxValue": "11000",
          "minValue": "9000",
          "precision": "0.0001",
          "unit": "",
          "valueType": "uint16"
        },
        {
          "address": 12398,
          "name": "device.pcs.PCCChargeActivePowerCalibrationK",
          "sort": "3",
          "maxValue": "11000",
          "minValue": "9000",
          "precision": "0.0001",
          "unit": "",
          "valueType": "uint16"
        },
        {
          "address": 12399,
          "name": "device.pcs.PCCChargeReactivePowerCalibrationK",
          "sort": "4",
          "maxValue": "11000",
          "minValue": "9000",
          "precision": "0.0001",
          "unit": "",
          "valueType": "uint16"
        },
        {
          "address": 12400,
          "name": "device.pcs.PCCActivePowerCalibrationB",
          "sort": "5",
          "maxValue": "500",
          "minValue": "-500",
          "precision": "1",
          "unit": "kW",
          "valueType": "int16"
        },
        {
          "address": 12401,
          "name": "device.pcs.PCCReactivePowerCalibrationB",
          "sort": "6",
          "maxValue": "500",
          "minValue": "-500",
          "precision": "1",
          "unit": "kVar",
          "valueType": "int16"
        },
        {
          "address": 12402,
          "name": "device.pcs.POIDischargeActivePowerCalibrationK",
          "sort": "7",
          "maxValue": "11000",
          "minValue": "9000",
          "precision": "0.0001",
          "unit": "",
          "valueType": "uint16"
        },
        {
          "address": 12403,
          "name": "device.pcs.POIDischargeReactivePowerCalibrationK",
          "sort": "8",
          "maxValue": "11000",
          "minValue": "9000",
          "precision": "0.0001",
          "unit": "",
          "valueType": "uint16"
        },
        {
          "address": 12404,
          "name": "device.pcs.POIChargeActivePowerCalibrationK",
          "sort": "9",
          "maxValue": "11000",
          "minValue": "9000",
          "precision": "0.0001",
          "unit": "",
          "valueType": "uint16"
        },
        {
          "address": 12405,
          "name": "device.pcs.POIChargeReactivePowerCalibrationK",
          "sort": "10",
          "maxValue": "11000",
          "minValue": "9000",
          "precision": "0.0001",
          "unit": "",
          "valueType": "uint16"
        },
        {
          "address": 12406,
          "name": "device.pcs.POIActivePowerCalibrationB",
          "sort": "11",
          "maxValue": "500",
          "minValue": "-500",
          "precision": "1",
          "unit": "kW",
          "valueType": "int16"
        },
        {
          "address": 12407,
          "name": "device.pcs.POIReactivePowerCalibrationB",
          "sort": "12",
          "maxValue": "500",
          "minValue": "-500",
          "precision": "1",
          "unit": "kVar",
          "valueType": "int16"
        }
      ]
    }
  },
]

# ================ #
#    INI config    #
# ================ #
# 该页面参数均为虚拟地址,从65536开始
MV_PCS_PARAM_CONFIG = [
  {
    "moduleName": "module.pcsConfig",
    "params": {
      "text": [
        {
          "address": 65536,
          "name": "device.pcs.PCS_NETWORK.pcs_brand",
          "sort": "1",
          "maxValue": "20",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "uint16"
        },
        {
          "address": 65537,
          "name": "device.pcs.SYSTEM.pcsReactiveLimit",
          "sort": "2",
          "maxValue": "100",
          "minValue": "0",
          "precision": "1",
          "unit": "%",
          "valueType": "uint16"
        },
        {
          "address": 65538,
          "name": "device.pcs.SYSTEM.pcsNum",
          "sort": "3",
          "maxValue": "4",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "uint16"
        },
        {
          "address": 65539,
          "name": "device.pcs.PCS_NETWORK.pcs1_ip",
          "sort": "4",
          "maxValue": "255",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "string"
        },
        {
          "address": 65540,
          "name": "device.pcs.PCS_NETWORK.pcs1_port",
          "sort": "5",
          "maxValue": "65535",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "uint16"
        },
        {
          "address": 65541,
          "name": "device.pcs.PCS_NETWORK.pcs2_ip",
          "sort": "6",
          "maxValue": "255",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "string"
        },
        {
          "address": 65542,
          "name": "device.pcs.PCS_NETWORK.pcs2_port",
          "sort": "7",
          "maxValue": "65535",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "uint16"
        },
        {
          "address": 65543,
          "name": "device.pcs.PCS_NETWORK.pcs3_ip",
          "sort": "8",
          "maxValue": "255",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "string"
        },
        {
          "address": 65544,
          "name": "device.pcs.PCS_NETWORK.pcs3_port",
          "sort": "9",
          "maxValue": "65535",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "uint16"
        },
        {
          "address": 65545,
          "name": "device.pcs.PCS_NETWORK.pcs4_ip",
          "sort": "10",
          "maxValue": "255",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "string"
        },
        {
          "address": 65546,
          "name": "device.pcs.PCS_NETWORK.pcs4_port",
          "sort": "11",
          "maxValue": "65535",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "uint16"
        },
      ]
    }
  }
]

# 该页面参数均为虚拟地址,从65543开始
MV_BMS_PARAM_CONFIG = [
  {
    "moduleName": "module.bmsConfig",
    "params": {
      "text": [
        {
          "address": 65547,
          "name": "device.bms.BMS_NETWORK.bms_brand",
          "sort": "1",
          "maxValue": "20",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "uint16"
        },
        {
          "address": 65548,
          "name": "device.bms.SYSTEM.bmsNum",
          "sort": "2",
          "maxValue": "8",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "uint16"
        },
        {
          "address": 65549,
          "name": "device.bms.BMS_NETWORK.bms1_ip",
          "sort": "3",
          "maxValue": "255",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "string"
        },
        {
          "address": 65550,
          "name": "device.bms.BMS_NETWORK.bms1_port",
          "sort": "4",
          "maxValue": "65535",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "uint16"
        },
        {
          "address": 65551,
          "name": "device.bms.BMS_NETWORK.bms2_ip",
          "sort": "5",
          "maxValue": "255",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "string"
        },
        {
          "address": 65552,
          "name": "device.bms.BMS_NETWORK.bms2_port",
          "sort": "6",
          "maxValue": "65535",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "uint16"
        },
        {
          "address": 65553,
          "name": "device.bms.BMS_NETWORK.bms3_ip",
          "sort": "7",
          "maxValue": "255",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "string"
        },
        {
          "address": 65554,
          "name": "device.bms.BMS_NETWORK.bms3_port",
          "sort": "8",
          "maxValue": "65535",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "uint16"
        },
        {
          "address": 65555,
          "name": "device.bms.BMS_NETWORK.bms4_ip",
          "sort": "9",
          "maxValue": "255",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "string"
        },
        {
          "address": 65556,
          "name": "device.bms.BMS_NETWORK.bms4_port",
          "sort": "10",
          "maxValue": "65535",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "uint16"
        },
        {
          "address": 65557,
          "name": "device.bms.BMS_NETWORK.bms5_ip",
          "sort": "11",
          "maxValue": "255",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "string"
        },
        {
          "address": 65558,
          "name": "device.bms.BMS_NETWORK.bms5_port",
          "sort": "12",
          "maxValue": "65535",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "uint16"
        },
        {
          "address": 65559,
          "name": "device.bms.BMS_NETWORK.bms6_ip",
          "sort": "13",
          "maxValue": "255",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "string"
        },
        {
          "address": 65560,
          "name": "device.bms.BMS_NETWORK.bms6_port",
          "sort": "14",
          "maxValue": "65535",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "uint16"
        },
        {
          "address": 65561,
          "name": "device.bms.BMS_NETWORK.bms7_ip",
          "sort": "15",
          "maxValue": "255",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "string"
        },
        {
          "address": 65562,
          "name": "device.bms.BMS_NETWORK.bms7_port",
          "sort": "16",
          "maxValue": "65535",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "uint16"
        },
        {
          "address": 65563,
          "name": "device.bms.BMS_NETWORK.bms8_ip",
          "sort": "17",
          "maxValue": "255",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "string"
        },
        {
          "address": 65564,
          "name": "device.bms.BMS_NETWORK.bms8_port",
          "sort": "18",
          "maxValue": "65535",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "uint16"
        }
      ]
    }
  }
]

# 该页面参数均为虚拟地址,从65565开始
MV_MC_PARAM_CONFIG = [
  {
    "moduleName": "module.mcConfig",
    "params": {
      "text": [
        {
          "address": 65565,
          "name": "device.mc.MEASURE_NETWORK.measure1_ip",
          "sort": "1",
          "maxValue": "255",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "string"
        },
        {
          "address": 65566,
          "name": "device.mc.MEASURE_NETWORK.measure1_port",
          "sort": "2",
          "maxValue": "65535",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "uint16"
        }
      ]
    }
  }
]

# 该页面参数均为虚拟地址,从65567开始
MV_P2P_PARAM_CONFIG = [
  {
    "moduleName": "module.P2P_EN",
    "params": {
      "buttom": [
       {
        "address": 65567,
        "name": "commands.pcs.SYSTEM.P2P_EN",
        "sort": "1",
        "eValue": "1",
        "rule": [65567]
        }
      ]
    }
  }
    
]

# 该页面参数均为虚拟地址,从65568开始
MV_LC_PARAM_CONFIG = [
  {
    "moduleName": "module.lcConfig",
    "params": {
      "text": [
        {
          "address": 65568,
          "name": "device.lc.NETWORK_net1.ip",
          "sort": "1",
          "maxValue": "255",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "string"
        },
        {
          "address": 65569,
          "name": "device.lc.NETWORK_net1.netmask",
          "sort": "2",
          "maxValue": "255",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "uint16"
        },
        {
          "address": 65570,
          "name": "device.lc.NETWORK_net1.gateway",
          "sort": "3",
          "maxValue": "255",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "string"
        },
        {
          "address": 65571,
          "name": "device.lc.NETWORK_net2.ip",
          "sort": "4",
          "maxValue": "255",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "string"
        },
        {
          "address": 65572,
          "name": "device.lc.NETWORK_net2.netmask",
          "sort": "5",
          "maxValue": "255",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "uint16"
        },
        {
          "address": 65573,
          "name": "device.lc.NETWORK_net2.gateway",
          "sort": "6",
          "maxValue": "255",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "string"
        },
        {
          "address": 65574,
          "name": "device.lc.NETWORK_net3.ip",
          "sort": "7",
          "maxValue": "255",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "string"
        },
        {
          "address": 65575,
          "name": "device.lc.NETWORK_net3.netmask",
          "sort": "8",
          "maxValue": "255",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "uint16"
        },
        {
          "address": 65576,
          "name": "device.lc.NETWORK_net3.gateway",
          "sort": "9",
          "maxValue": "255",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "string"
        },
        {
          "address": 65577,
          "name": "device.lc.NETWORK_net4.ip",
          "sort": "10",
          "maxValue": "255",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "string"
        },
        {
          "address": 65578,
          "name": "device.lc.NETWORK_net4.netmask",
          "sort": "11",
          "maxValue": "255",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "uint16"
        },
        {
          "address": 65579,
          "name": "device.lc.NETWORK_net4.gateway",
          "sort": "12",
          "maxValue": "255",
          "minValue": "0",
          "precision": "1",
          "unit": "",
          "valueType": "string"
        }
      ]
    }
  }
]

# ================ #
#   ALL DATATYPE   #
# ================ #
CONFIG_PARAMS_BY_DATA_TYPE = {
    "systemctl-power": SYSTECMCTL_POWER,
    "runParaSetting-pcsSetting": RUNPARASETTING_PCSSETTING,
    "runParaSetting-ParaCalibration": RUNPARASETTING_PARAGALIBRATION,
    # "mv-pcsGroup": MV_PCS_PARAM_CONFIG,
    "mv-pcs": MV_PCS_PARAM_CONFIG,
    "mv-bms": MV_BMS_PARAM_CONFIG,
    "mv-mc": MV_MC_PARAM_CONFIG,
    "mv-p2p": MV_P2P_PARAM_CONFIG,
    "mv-lc": MV_LC_PARAM_CONFIG,
}

# 配置参数缓存区
ADDR_CONFIG_CACHE = {}

