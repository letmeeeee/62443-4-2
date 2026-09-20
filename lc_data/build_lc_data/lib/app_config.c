/* ------------------------------------------------------------
 * Copyright (C) 2019
 * File Name : app_config.c
 * Project :
 * Description : ini文件配置内容读写，本进程的配置
 * File Created :
 * Author : wujinjin
 * ------------------------------------------------------------
 * Last Modified : 2022/12/05
 * Modified By : jinxue.zhao
 * ------------------------------------------------------------
 * HISTORY : 2022/12/05 修改宏定义，调整配置文件读取结构
 * ------------------------------------------------------------
 * HISTORY : 2022/11/11 修改解析的内容 - server改成scada
 * ------------------------------------------------------------
 * HISTORY : 2022/10/26 修改解析的内容
 */

#include "main.h"
#include "ini.h"
#include "app_config.h"

/* 配置变量 */
static sysPara sysConf = {0};

/* 默认配置文件名 */
#define MATCH_SECTION(s)  (strcmp(section, s) == 0)                         //匹配段名宏
#define MATCH(s, n)  ((strcmp(section, s) == 0) && (strcmp(name, n) == 0))  //匹配段名和项名宏

/**
 * @brief 时段设置
 * @param[in] str - 时段字符串
 * @param[out] period - 需要赋值的时段
 * @return -1-赋值失败; 0-赋值成功
 */
int fill_period(const char* str, period* p_period)
{
    unsigned short bh;
    unsigned short bm;
    unsigned short eh;
    unsigned short em;
    int active_power;
    int reactive_power;
    int ret = 0;
    ret = sscanf(str, "%hd:%hd:%hd:%hd:%d:%d", &bh, &bm, &eh, &em, &active_power, &reactive_power);
    if(ret != 6)
    {
        return -1;
    }

    p_period->bh = bh;
    p_period->bm = bm;
    p_period->eh = eh;
    p_period->em = em;
    p_period->active_power = active_power;
    p_period->reactive_power = reactive_power;

    return 0;
}

/**
 * @brief 系统配置内容解析
 * @param[in] pconfig 配置表
 * @param[in] section 配置段标识
 * @param[in] name 配置项名称
 * @param[in] value 配置项数值
 * @return 结果，-1错误，0未匹配，1匹配成功
 */
static int System_parsing(sysPara* pconfig, const char* section, const char* name, const char* value)
{
    int match_res = 1;
    //本地控制器从地址
    if(MATCH("SYSTEM", "lc_slave_addr"))
    {
        pconfig->lc_slave_addr = atoi(value);
    }
    //EMS服务器使能
    else if(MATCH("SYSTEM", "emsEnable"))
    {
        pconfig->emsEnable = atoi(value);
    }
    //EMSP1服务器port值
    else if(MATCH("SYSTEM", "localEmsPort"))
    {
        pconfig->localEmsPort = atoi(value);
    }
    //EMSP1服务器使能
    else if(MATCH("SYSTEM", "emsP1Enable"))
    {
        pconfig->emsP1Enable = atoi(value);
    }
    //EMS服务器port值
    else if(MATCH("SYSTEM", "localEmsP1Port"))
    {
        pconfig->localEmsP1Port = atoi(value);
    }
    //数据中心链接主控程序的端口port值
    else if(MATCH("SYSTEM", "localScadaPort"))
    {
        pconfig->localScadaPort = atoi(value);
    }
    //子系统个数
    else if(MATCH("SYSTEM", "subSysNum"))
    {
        pconfig->subSysNum = atoi(value);
    }
    //子系统类型
    else if(MATCH("SYSTEM", "subSysType"))
    {
        pconfig->subSysType = atoi(value);
    }
    //BMS个数
    else if (MATCH("SYSTEM", "bmsNum"))
    {
        pconfig->bmsNum = atoi(value);
    }
        //pcs个数
    else if (MATCH("SYSTEM", "pcsNum"))
    {
        pconfig->pcsNum = atoi(value);
    }
     else if (MATCH("SYSTEM", "sysNum"))
    {
        pconfig->sysNum = atoi(value);
    }
    else if (MATCH("SYSTEM", "emuNum"))
    {
        pconfig->emuNum = atoi(value);
    }
    else if (MATCH("SYSTEM", "pcsModelNum"))
    {
        pconfig->pcsModelNum = atoi(value);
    }
    else if (MATCH("SYSTEM", "pcsGroupNum"))
    {
        pconfig->pcsGroupNum= atoi(value);
    }
    else if (MATCH("SYSTEM", "meterNum"))
    {
        pconfig->meterNum = atoi(value);
    }
    else if (MATCH("SYSTEM", "sydyNum"))
    {
        pconfig->sydyNum = atoi(value);
    }
    //数据库存储时间
    else if (MATCH("SYSTEM", "dbHoldDays"))
    {
        pconfig->dbHoldDays = atoi(value);
    }
    //数据库存储周期
    else if (MATCH("SYSTEM", "dbSaveTime"))
    {
        pconfig->dbSaveTime = atoi(value);
    }
    //所有系统项都没匹配成功
    else
    {
        match_res = 0;
    }

    return match_res;
}

/**
 * @brief BMS网络配置内容解析
 * @note 参考函数System_parsing的参数说明
 */
static int BMS_Network_parsing(sysPara* pconfig, const char* section, const char* name, const char* value)
{
    char match_str[64] = {0};
    for(int i = 0; i < MAX_BMS_NUM; i++)
    {
        //BMS类型
        memset(match_str, 0, sizeof(match_str));
        sprintf(match_str, "bms%d_brand", i + 1);
        if(MATCH("BMS_NETWORK", match_str))
        {
            pconfig->bms_brand[i] = atoi(value);
            return 1;
        }
        //BMS网络地址
        memset(match_str, 0, sizeof(match_str));
        sprintf(match_str, "bms%d_ip", i + 1);
        if(MATCH("BMS_NETWORK", match_str))
        {
            memset(pconfig->bms_ip[i], 0, MAX_IP_STR_LEN);
            memcpy(pconfig->bms_ip[i], value, strlen(value));
            return 1;
        }
        //BMS网络端口
        memset(match_str, 0, sizeof(match_str));
        sprintf(match_str, "bms%d_port", i + 1);
        if(MATCH("BMS_NETWORK", match_str))
        {
            pconfig->bms_port[i] = atoi(value);
            return 1;
        }
        //BMS从站地址
        memset(match_str, 0, sizeof(match_str));
        sprintf(match_str, "bms%d_slave_addr", i + 1);
        if(MATCH("BMS_NETWORK", match_str))
        {
            pconfig->bms_slave_addr[i] = atoi(value);
            return 1;
        }
        //BMS簇数量
        memset(match_str, 0, sizeof(match_str));
        sprintf(match_str, "bms%d_cluster", i + 1);
        if(MATCH("BMS_NETWORK", match_str))
        {
            pconfig->bms_cluster[i] = atoi(value);
            return 1;
        }
        //单体电压数量
        memset(match_str, 0, sizeof(match_str));
        sprintf(match_str, "bms%d_vol_num", i + 1);
        if(MATCH("BMS_NETWORK", match_str))
        {
            pconfig->bms_vol_num[i] = atoi(value);
            return 1;
        }

        //单体温度数量
        memset(match_str, 0, sizeof(match_str));
        sprintf(match_str, "bms%d_temp_num", i + 1);
        if(MATCH("BMS_NETWORK", match_str))
        {
            pconfig->bms_temp_num[i] = atoi(value);
            return 1;
        }

        memset(match_str, 0, sizeof(match_str));
        sprintf(match_str, "bms%d_pole_num", i + 1);
        if(MATCH("BMS_NETWORK", match_str))
        {
            pconfig->bms_pole_num[i] = atoi(value);
            return 1;
        }
        //液冷机数量
        memset(match_str, 0, sizeof(match_str));
        sprintf(match_str, "bms%d_cooler_num", i + 1);
        if(MATCH("BMS_NETWORK", match_str))
        {
            pconfig->bms_cooler_num[i] = atoi(value);
            return 1;
        }
    }

    return 0;
}





/**
 * @brief config.ini文件分析回调函数，每一行调用一次
 * @param[in] user - 用户数据(未使用)
 * @param[in] section - config.ini中段标识[]里的内容
 * @param[in] name - 变量名
 * @param[in] value -  变量值
 * @return -1-赋值失败; 0-赋值成功
 */
static int handler(void* user, const char* section, const char* name, const char* value)
{
    sysPara* pconfig = (sysPara*)user;
    if(pconfig == NULL || section == NULL || name == NULL || value == NULL)
    {
        return -1;
    }

    int parsing_res = 1;
    //系统配置内容解析
    if(MATCH_SECTION("SYSTEM"))
    {
        parsing_res = System_parsing(pconfig, section, name, value);
    }
    //BMS网络配置内容解析
    else if(MATCH_SECTION("BMS_NETWORK"))
    {
        parsing_res = BMS_Network_parsing(pconfig, section, name, value);
    }
    else
    {
        LOG_DBG("unknown section:%s", section);
        return 0; /* unknown section/name, error */
    }

    if(parsing_res == 0)
    {
        LOG_DBG("unknown section:%s  name:%s", section, name);
        return 0; /* unknown section/name, error */
    }

    return 1;
}

int AppConf_Init()
{
    sysPara* config = &sysConf;
    memset(config, '\0', sizeof(sysPara));

    char fileName[50];
    memset(fileName, 0, sizeof(fileName));
    sprintf(fileName, CONFIG_PATH);

    if(ini_parse(fileName, handler, config) < 0)
    {
        LOG_ERR("Can't load '%s', please check the synax.", fileName);
        AppConf_UnInit();
        return -1;
    }

    return 0;
}

void AppConf_UnInit()
{
    sysPara* config = &sysConf;
    memset(config, '\0', sizeof(sysPara));
}

sysPara* SysConf_GetInfo()
{
    return &sysConf;
}

