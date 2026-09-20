
# 设备id映射表,程序生成
"""
DEVICE_MAP": {
    "deviceList": [
        {
            "deviceType": 2,
            "id": 1,
            "name": "PCS_SKID",
            "sort": 1
        },
        {
            "deviceType": 5,
            "id": 2,
            "name": "G3_PCS_GROUP",
            "sort": 1
        },
        {
            "deviceType": 6,
            "id": 3,
            "name": "G3_PCS",
            "sort": 1
        },
        {
            "deviceType": 6,
            "id": 4,
            "name": "G3_PCS",
            "sort": 2
        },
        {
            "deviceType": 7,
            "id": 5,
            "name": "MV",
            "sort": 1
        },
        {
            "deviceType": 8,
            "id": 6,
            "name": "METER",
            "sort": 1
        },
        {
            "deviceType": 9,
            "id": 7,
            "name": "BMS_BANK",
            "sort": 1
        },
        {
            "deviceType": 9,
            "id": 8,
            "name": "BMS_BANK",
            "sort": 2
        },
        {
            "deviceType": 9,
            "id": 9,
            "name": "BMS_BANK",
            "sort": 3
        },
        {
            "deviceType": 9,
            "id": 10,
            "name": "BMS_BANK",
            "sort": 4
        }
    ]
}




"""

DEVICE_MAP = None

# ================== 根据新Web协议添加 ==================
   # ================== 设备列表 API ==================
DEVICE_TYPE = {
    "PCS_SKID": 2,        # PCS SKID：箱式储能中压变流器
    "G2_PCS_GROUP": 3,   # G2-PCS GROUP：台达PCS
    "G2_PCS": 4,         # G2-PCS：台达PCS
    "G3_PCS_GROUP": 5,   # G3-PCS GROUP：自研PCS
    "G3_PCS": 6,         # G3-PCS：自研PCS
    "MV": 7,             # MV：中压系统
    "METER": 8,          # METER：电表
    "BMS_BANK": 9,       # BMS BANK：电池堆
}

PCS_BRAND = {
    "G2_DELTA": 6,        # pcs*_brand = 6：G2-PCS，台达PCS
    "G3_SELF": 2,         # pcs*_brand = 2：G3-PCS，自研PCS
}

BMS_BRAND = {
    "G3_BMS": 3,         # pcs*_brand = 3：G3-BMS,上能
}

#  ========================= 系统一致性检查汇总 ========================
PCS_VERSION_VERIFICATION = 223
PCS_SAFETY_STANDARDS_VERIFICATION = 224
PCS_MODE_VERIFICATION = 225

SYSTEM_CONSISTENCY_CHECK = {
    PCS_VERSION_VERIFICATION: {
        0 : "history.table.pcsGroup.reserved",
        1 : "history.table.pcsGroup.reserved",
        2 : "history.table.pcsGroup.reserved",
        3 : "history.table.pcsGroup.reserved",
        4 : "history.table.pcsGroup.reserved",
        5 : "history.table.pcsGroup.reserved",
        6 : "history.table.pcsGroup.reserved",
        7 : "history.table.pcsGroup.reserved",
        8 : "alarm.HardwareVersionVerificationAlarm",
        9 : "alarm.ProtocolVersionVerificationAlarm",
        10: "alarm.PlatformVersionVerificationAlarm",
        11: "alarm.SoftwarePackageVersionVerificationAlarm",
        12: "alarm.ReleaseDateAlarm",
        13: "history.table.pcsGroup.reserved",
        14: "history.table.pcsGroup.reserved",
        15: "history.table.pcsGroup.reserved"
    },
    PCS_SAFETY_STANDARDS_VERIFICATION: {
        0 : "history.table.pcsGroup.reserved",
        1 : "history.table.pcsGroup.reserved",
        2 : "history.table.pcsGroup.reserved",
        3 : "history.table.pcsGroup.reserved",
        4 : "history.table.pcsGroup.reserved",
        5 : "history.table.pcsGroup.reserved",
        6 : "history.table.pcsGroup.reserved",
        7 : "history.table.pcsGroup.reserved",
        8 : "alarm.SafetyVersionVerificationAlarm",
        9 : "alarm.RegionCodeVerificationAlarm",
        10: "history.table.pcsGroup.reserved",
        11: "history.table.pcsGroup.reserved",
        12: "history.table.pcsGroup.reserved",
        13: "history.table.pcsGroup.reserved",
        14: "history.table.pcsGroup.reserved",
        15: "history.table.pcsGroup.reserved"
    },
    PCS_MODE_VERIFICATION: {
        0 : "alarm.BusModeVerificationAlarm",
        1 : "alarm.On-grid/Off-grid SwitchVerificationAlarm",
        2 : "alarm.OperationModeVerificationAlarm",
        3 : "alarm.Master/Slave ModeVerification",
        4 : "history.table.pcsGroup.reserved",
        5 : "history.table.pcsGroup.reserved",
        6 : "history.table.pcsGroup.reserved",
        7 : "history.table.pcsGroup.reserved",
        8 : "history.table.pcsGroup.reserved",
        9 : "history.table.pcsGroup.reserved",
        10: "history.table.pcsGroup.reserved",
        11: "history.table.pcsGroup.reserved",
        12: "history.table.pcsGroup.reserved",
        13: "history.table.pcsGroup.reserved",
        14: "history.table.pcsGroup.reserved",
        15: "history.table.pcsGroup.reserved"
    },
}

SYSTEM_CONSISTENCY_CHECK_LIST = [
    PCS_VERSION_VERIFICATION,
    PCS_SAFETY_STANDARDS_VERIFICATION,
    PCS_MODE_VERIFICATION
]
