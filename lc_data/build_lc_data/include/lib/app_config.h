/* ------------------------------------------------------------
 * Copyright (C) 2019
 * File Name: appConf.h
 * Project:
 * Description: ini文件配置内容读写，本进程的配置
 * File Created:
 * Author: wujinjin
 * ------------------------------------------------------------
 * Last Modified:
 * Modified By:
 * ------------------------------------------------------------
 * HISTORY:
 */

#ifndef APPCONF_H_
#define APPCONF_H_

/* Make this header file easier to include in C++ code */
#ifdef __cplusplus
extern "C" {
#endif

//单个设备可能的最大数量
#define MAX_DEVICE_NUM (500) //设备的最大数量
#define MAX_IP_STR_LEN (16)  // ip字符串的长度

//相关设备的最大数量，GROUP、PCS、BMS这三个值保持一致
#define MAX_GROUP_NUM (8)       //子系统数量
#define MAX_PCS_NUM (8)         // PCS设备数量
#define MAX_BMS_NUM (8)         // BMS设备数量
#define MAX_DI_NUM (5)           // DI1210设备数量
#define MAX_DIDO_NUM (5)         // DIDO1214设备数量
#define MAX_GATEWAY_NUM (5)           //网关设备数量
#define MAX_DC_METER_NUM (20)    //直流电表设备数量
#define MAX_AC_METER_NUM (20)    //交流电表设备数量
#define MAX_UPS_NUM (10)         // UPS设备数量
#define MAX_AIR_NUM (50)         //空调设备数量
#define MAX_TEMP_NUM (50)        //温度传感器设备数量
#define MAX_MEASU_NUM (10)       //测控设备数量
#define MAX_GAS_NUM (10)         //气体传感器设备数量
#define MAX_PERIOD_NUM (24)      //串口数量
#define MAX_ETH485_NUM (12)      // ETH485口，以太网转485口
#define MAX_SERIAL_NUM (10)      //包含485口和232口
#define MAX_DEV_GROUP_NUM   (8)    //串口上连接的设备分组数量
#define MAX_SERIAL_DEV_NUM (127) //串口上连接的设备数量
#define MAX_DISIG_NUM (300)      // 300个输入信号
#define MAX_DOSIG_NUM (100)      // 100个输出信号
#define MAX_MEASURE_NUM (10)     //测控装置
#define MAX_ETH_NUM         (8)    //设备网口数量
#define MAX_CLIENT_NUM      (9)    //同时最多链接客户端数量

//运行模式
#define REMOTE_HANDLE       (0)    //手动遥控
#define LOCAL_AUTO          (1)    //本地自动
#define REMOTE_AUTO         (2)    //远程自动
#define LOCAL_HANDLE        (3)    //本地手动

//子系统类型
#define SUB_SYSTEM_BASE     (0)    //基础版子系统
#define SUB_SYSTEM_V1       (1)    //中核版子系统

//PCS品牌标识
#define PCS_XUJI_CBL220     (1)    //许继PCS CBL220-2500
#define PCS_TRINA_500       (2)    //天合自研PCS 500
#define PCS_KEHUA_BCS1725K  (3)    //科华PCS BCS1725K_B_HUB

//BMS品牌标识
#define BMS_TRINA_V1        (1)    //天合自研BMS
#define BMS_GOLD_V27        (2)    //高特BMS
#define BMS_XIENENG         (3)    //协能BMS

//特殊设备标志
#define U3_EC               (1)    //英维克E3空调
#define RS_WS_N01           (2)    //建大仁科温湿度传感器
#define MHC_UPS             (3)    //山特UPS
#define ACREL_PZ            (4)    //安科瑞PZ系列交流电能表
#define SGA                 (5)    //深国安气体传感器

//通信方式标志
#define RS232               (0)    //232通信方式
#define RS485               (1)    //485通信方式
#define RS485SERVER         (2)    //485通信服务器

// DI的项目类型
#define DI_ITEM_ZHONGHE (1)  //中核项目DI处理模式
#define DI_ITEM_ZHONGCHE (2) //中车雄里坡项目DI处理模式
#define DI_ITEM_SHAHE (3)    //沙河项目DI处理模式

// DIDO的项目类型
#define DIDO_ITEM_ZHONGHE1 (1) //中核项目1号E1214设备DIDO处理模式
#define DIDO_ITEM_ZHONGHE2 (2) //中核项目2号E1214设备DIDO处理模式
#define DIDO_ITEM_ZHONGCHE (3) //中车雄里坡项目DIDO处理模式
#define DIDO_ITEM_YELENG (4)   //国内液冷项目DIDO处理模式
#define DIDO_ITEM_SHAHE1 (7)   //沙河项目1号E1214设备DIDO处理模式
#define DIDO_ITEM_SHAHE2 (8)   //沙河项目2号E1214设备DIDO处理模式

// 按字节对齐
#pragma pack(push, 1)

//时段设置
typedef struct
{
    unsigned short bh;
    unsigned short bm;
    unsigned short eh;
    unsigned short em;
    int active_power;
    int reactive_power;
}period;

//串口通信设备参数列表
typedef struct
{
    unsigned char device[MAX_SERIAL_DEV_NUM];
}SERIAL_LIST_T;

//串口通信设备组属性
typedef struct
{
    unsigned char dev_type;   //设备类型
    unsigned char dev_saddr;  //设备起始从地址
    unsigned char dev_num;    //顺序设备数量
    unsigned char dev_port;   //设备port口序号
}DEVICE_GROUP_T;


//参数设置
typedef struct
{
//[SYSTEM]
    unsigned char lc_slave_addr;
    unsigned char emsEnable;
    unsigned int localEmsPort;
  
    unsigned char emsP1Enable;
    unsigned int localEmsP1Port;
    unsigned int localScadaPort;
    unsigned char subSysNum;
    unsigned char subSysType;
    unsigned char bmsNum;
    unsigned char pcsNum;
    unsigned char sysNum;
    unsigned char emuNum;
    unsigned char pcsModelNum;
    unsigned char pcsGroupNum;
    unsigned char meterNum;
    unsigned char sydyNum;
    unsigned int  dbHoldDays; //
    unsigned int  dbSaveTime;
    unsigned int  CSVHoldDays;
    unsigned int  CSVSaveTime;

    //[NETWORK]
    unsigned char bms_ip[MAX_BMS_NUM][MAX_IP_STR_LEN];
    unsigned int bms_port[MAX_BMS_NUM];
    unsigned int bms_brand[MAX_BMS_NUM];
    unsigned int bms_slave_addr[MAX_BMS_NUM];
    unsigned int bms_cluster[MAX_BMS_NUM]; //簇个数
    unsigned int bms_vol_num[MAX_BMS_NUM];
    unsigned int bms_temp_num[MAX_BMS_NUM];
    unsigned int bms_pole_num[MAX_BMS_NUM];
    unsigned int bms_cooler_num[MAX_BMS_NUM];
    
} sysPara;

// 按字节对齐
#pragma pack(pop)


/**
 * @brief App配置的取得
 * @return App配置
 */
sysPara* SysConf_GetInfo();

/**
 * @brief App配置数据初始化
 * @return 结果，1是成功
 */
int AppConf_Init();

/**
 * @brief 释放App配置空间
 */
void AppConf_UnInit();

#ifdef __cplusplus
}
#endif

#endif //APPCONF_H_
