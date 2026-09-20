/* ------------------------------------------------------------
 * Copyright (C) 2022
 * File Name : system.c
 * Project :
 * Description : 系统相关的设定
 * File Created :
 * Author : jinjin.wu
 * ------------------------------------------------------------
 * Last Modified :
 * Modified By :
 * ------------------------------------------------------------
 * HISTORY:
 */

#ifndef SYSTEM_H
#define SYSTEM_H
#define MOXA8410A   0
#define EM500       1

#define SEL_DEV   MOXA8410A
//无效参数宏函数
#define UNUSED_PARAM(a)  (void)(a)

//Modbus缓存打印宏函数
//#define DEBUG_MACRO_NAME 1
#ifdef DEBUG_MACRO_NAME
#define DebugModbusBuf(string, ptr_buf, len) do { \
    printf("[%s:%d]  "string, __FUNCTION__, __LINE__); \
    for (int j = 0; j < len; j++) \
    { \
         printf("%02x ", ptr_buf[j]); \
    } \
    printf("\n"); \
} while(0)
#define DebugPrint(fmt, ...)  printf("Debug INFO [%s:%d]  "fmt, __FUNCTION__, __LINE__, ##__VA_ARGS__)
#else
#define DebugModbusBuf(string, ptr_buf, len) (void)NULL
#define DebugPrint(fmt, ...)  (void)NULL
#endif




#define CONFIG_PATH         "./lc_data_set.ini"                   //系统配置文件
#define LOG_CONFIG          "./mysqlzlog"                      //系统日志文件

#define NET_PATH            "/etc/network/interfaces"              //系统网络接口定义文件
#define NET_PATH_BAK        "/etc/network/interfaces.bak"          //系统网络接口定义文件的备份文件







#define SYS_SYNC_TIEM_ADDR        (222)   //系统对时





//通用类型
typedef unsigned char  BOOLEAN;
typedef unsigned char  INT8U;
typedef signed   char  INT8S;
typedef unsigned short INT16U;
typedef signed   short INT16S;
typedef unsigned int   INT32U;
typedef signed   int   INT32S;
typedef float          FP32;
typedef double         FP64;
typedef long long int  INT64U;


//16位2进制表示方式
typedef union
{
    struct
    {
        INT16U b0:1;
        INT16U b1:1;
        INT16U b2:1;
        INT16U b3:1;
        INT16U b4:1;
        INT16U b5:1;
        INT16U b6:1;
        INT16U b7:1;
        INT16U b8:1;
        INT16U b9:1;
        INT16U b10:1;
        INT16U b11:1;
        INT16U b12:1;
        INT16U b13:1;
        INT16U b14:1;
        INT16U b15:1;
    }bit;
    INT16U data;
} u16_bit_conv;

//16位高低位表示方式
typedef union
{
     INT8U D8[2];
     INT16U D16;
     INT16S DS16;
} u16_conv;

//32位ABCD或高低位表示方式
typedef union
{
    INT8U D8[4];
    INT16U D16[2];
    INT16S DS16[2];
    INT32U D32;
    INT32S DS32;
    float F32;
}u32_conv;

//烟感高低报警值
enum enumRow
{
    FireFailure       = 55002,
    Fire1Failure,
    Fire2Failure,
    Flooding1Failure,
    Flooding2Failure,
    H2_COLowFailure   = 55012,
    H2_COHighFailure,
};

//////////////软件版本号，分别为年、月、日、当日第几版////////////////
#define software_year           (0x22)
#define software_month          (0x01)
#define software_day            (0x23)
#define software_num            (0x01)

//////////////软件版本号，分别为年、月、日、当日第几版  出厂版本V1.00////////////////
#define software1               (0x56)
#define software2               (0x31)
#define software3               (0x2e)
#define software4               (0x30)
#define software5               (0x30)

//////////////协议版本号 ，分别为年、月、日、当日第几版////////////////
#define protocol_year           (0x21)
#define protocol_month          (0x06)
#define protocol_day            (0x30)
#define protocol_num            (0x01)

#endif //SYSTEM_H
