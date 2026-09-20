/* ------------------------------------------------------------
 * Copyright (C) 2023
 * File Name : main.h
 * Project :
 * Description : 数据中心程序
 * File Created :
 * Author : lj
 * ------------------------------------------------------------
 * Last Modified :
 * Modified By :  lj
 * ------------------------------------------------------------
 * HISTORY :
 */

#ifndef MAIN_H
#define MAIN_H

#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <netdb.h>
#include <pthread.h>
#include <termios.h>
#include <time.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <signal.h>
#include <unistd.h>
#include <stdbool.h>
#include <arpa/inet.h>
#include <linux/if.h>
#include <linux/reboot.h>
#include <linux/rtc.h>
#include <linux/sockios.h>
#include <netinet/in.h>
#include <sys/ioctl.h>
#include <sys/reboot.h>
#include <sys/sem.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/timeb.h>
#include <sys/types.h>

#include "app_config.h"
#include "assist_func.h"
#include "ini.h"
#include "modbus_protocol.h"

#include "dio_zlg.h"

#include "system.h"
#include "tcp_socket.h"
#include "timer.h"
#include "log.h"

#include "address_map.h"
#define PRO_NAME         "lc_data"  
#define USE_DB              //数据库开关 
#define USE_CSV             //CSV开关 
// #define ISDEBUG_          //调试打印开关
//#define ISDEBUG_SHARE_    //共享内存调试打印开关

#ifdef USE_DB
#include "mysql.h"
#endif
#ifdef USE_CSV
#define CSV_DIR           "/root/csvfile"
#endif
//开关标志
#define ON  (1)
#define OFF (0)

//执行结果
#define EXEC_OK    (1)   //成功
#define EXEC_FAIL  (-1)  //失败
#define FALSE      (0)   //错误
#define TRUE       (1)   //正确

//系统的数据总长度
#define MAX_SYSTEM_TOTAL_DATA_NUM  (60000)  //点表数据长度
#define MAX_NETWORK_DATA_NUM       (1000)   //网址数据长度

//上传寄存器数据类型
typedef enum
{
	TpyeUnknow,      //未知无效类型
    TpyeUnDeal,      //不做处理
    TpyeLongStr,     //有符号32字节
    TpyeShortStr,    //有符号16字节
    TpyeContralVerStr, //有符号16字节
    TpyeLcDataVerStr,  //有符号16字节

    TpyeCangIDStr,    //有符号32字节
    TpyeBankID,       //无符号2字节 
    TpyeRackID,       //无符号2字节 
    TpyeXie_h_vol_pos,   //协能有符号16字节
    TpyeXie_l_vol_pos,   //协能有符号16字节
    TpyeXie_h_tem_pos,   //协能有符号16字节
    TpyeXie_l_tem_pos,   //协能有符号16字节

    TpyeTrinaB_h_vol_pos,   //天合Bms有符号16字节
    TpyeTrinaB_l_vol_pos,   //天合Bms有符号16字节
    TpyeTrinaB_h_tem_pos,   //天合Bms有符号16字节
    TpyeTrinaB_l_tem_pos,   //天合Bms有符号16字节

    TpyeGold_h_vol_pos,   //高特Bms有符号16字节
    TpyeGold_l_vol_pos,   //高特Bms有符号16字节
    TpyeGold_h_tem_pos,   //高特Bms有符号16字节
    TpyeGold_l_tem_pos,   //高特Bms有符号16字节

    TpyeStamp,        //时间戳
	
	TpyeXieUnShort,     //协能无符号2字节
	TpyeXieShort,       //协能有符号2字节
	TpyeXieUnInt_H,   
    TpyeXieUnInt_L,    
	TpyeXieInt_H,      
    TpyeXieInt_L,      
    TpyeXieFloat_H,       
    TpyeXieFloat_L, 

    TpyeGoldUnShort,     //高特无符号2字节
	TpyeGoldShort,       //高特有符号2字节
	TpyeGoldUnInt,       //高特无符号4字节
	TpyeGoldInt,         //高特有符号4字节 

    TpyeTrinaBUnShort,     //天合Bms无符号2字节
	TpyeTrinaBShort,       //天合Bms有符号2字节
	TpyeTrinaBUnInt,       //天合Bms无符号4字节
	TpyeTrinaBInt,         //天合Bms有符号4字节 

    TpyeKeUnShort,          //科华无符号2字节
	TpyeKeShort,            //科华有符号2字节
	TpyeKeUnInt,            //科华无符号4字节
	TpyeKeInt,              //科华有符号4字节 

    TpyeXuUnShort,          //许继无符号2字节
	TpyeXuShort,            //许继有符号2字节
	TpyeXuUnInt,            //许继无符号4字节
	TpyeXuInt,              //许继有符号4字节 

    TpyeTrinaPUnShort,     //天合Pcs无符号2字节
	TpyeTrinaPShort,       //天合Pcs有符号2字节
	TpyeTrinaPUnInt,       //天合Pcs无符号4字节
	TpyeTrinaPInt,         //天合Pcs有符号4字节 

    TpyeLcUnShort,          //LC无符号2字节
	TpyeLcShort,            //LC有符号2字节
	TpyeLcUnInt_H,   
    TpyeLcUnInt_L,    
	TpyeLcInt_H,      
    TpyeLcInt_L,      
    TpyeLcFloat_H,       
    TpyeLcFloat_L,


    TpyeCustom,             //自定义
    TpyeTrinaBCustom,         //自定义
    TpyeGoldCustom,          //自定义
    TpyeXieIR,                //协能绝缘4字节
    TpyeTrinaBIR,             //协能绝缘4字节
    TpyeGoldIR,              //协能绝缘4字节
    TpyeEnd,                  //枚举结束符，不使用该类型
   
} UploadInfoTpye;

enum enumIOFaultFlag
{
    IsNoFault = 0,
    IsFault,
    IsStandby,
    IsWarn,
};
typedef struct
{
	INT16U Type; 		//类型
    INT16U RegAdd; 		//协议中寄存器地址
	u16_conv Dat;		//数据内容
} reg_st;


typedef struct
{
    INT16U RegAdd; 		//协议中寄存器地址
    INT16U Type; 		//类型
} reg_type_st;

typedef struct
{
    INT16U startAdd; 	
    INT16U startEnd; 	
    INT16U Type; 		//类型
} reg_type_zone;

typedef struct
{
    INT16U index; 		//序号
	u32_conv Dat;		//数据内容
} compute_st;













#ifdef __cplusplus
extern "C"
{
#endif
/**
 * @brief  每条通讯线的线程任务
 * @note MC连接（NET）的任务，命令发送、数据处理
 * @param[in] void *arg
 * @return 返回结果 无
 */
void *client_task_NET(void *arg);

#ifdef __cplusplus
}

#endif 

/**
 * @brief   system函数封装
 * @note
 * 		cmd :指令内容
 *      times :执行次数
 *      当同时满足下面三个条件时才是执行成功
 * 			 （1）-1 != status
 *           （2）WIFEXITED(status)为真
 *           （3）0 == WEXITSTATUS(status)
 * @retval true 成功，false 失败
 */
bool do_system(char *cmd,int times);
#endif //MAIN_H
