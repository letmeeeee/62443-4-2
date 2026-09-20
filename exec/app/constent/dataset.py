from constent.device_info import DEVICE_TYPE
#  ========================= MySQL设备字段映射表 ========================
TABLE_PREFIX_MAP = {
    DEVICE_TYPE.get("G3_PCS"): "pcsmodel",
    DEVICE_TYPE.get("MV"): "mv",
    DEVICE_TYPE.get("BMS_BANK"): "bms"
}


# mysql数据类型映射
def mysql_mapping(row):
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    else:
        try:
            return dict(row)
        except Exception:
            return {}