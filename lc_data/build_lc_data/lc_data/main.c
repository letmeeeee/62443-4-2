/*
 * Copyright (C) 2023
 * File Name: main.c
 * Project:
 * Description:
 * File Created:
 * Author:
 * -----
 * Last Modified:
 * Modified By: lj
 * -----
 * HISTORY:
 */

#include "main.h"
#include "subsystem.h"
#include "timed_check.h"
#include "timed_work.h"
#include "db_work.h"
#include "other_work.h"
#include "share_ram.h"
#include "modbus_ems_server.h"



// 线程序号
static int pthread_index[MAX_DEVICE_NUM] = {0};







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
bool do_system(char *cmd, int times)
{
    bool res = false;
    int ret = 0;
    int i;
    res = false;
    for (i = 0; i < times; i++)
    {
        ret = system(cmd);
        if (1 == ret)
        {
            printf("do_system:程序命令为空\n");
            printf("do_system:system ret =%d\n", ret);
        }
        else if (-1 == ret)
        {
            printf("do_system:创建命令子进程失败\n");
            printf("do_system:system ret =%d\n", ret);
        }
        else if (0x7f00 == ret)
        {
            printf("do_system:命令错误，无法执行\n");
            printf("do_system:system ret =%d\n", ret);
        }
        else
        {
            if (WIFEXITED(ret))
            {
                if (WEXITSTATUS(ret) != 0)
                {
                    printf("do_system:程序结束，返回值:%d\n", WEXITSTATUS(ret));
                    printf("do_system:system ret =%d\n", ret);
                }
                else
                {
                    res = true;
                    break;
                }
            }
            else if (WIFSIGNALED(ret))
            {
                printf("do_system:程序被信号杀死，信号值:%d\n", WTERMSIG(ret));
                printf("do_system:system ret =%d\n", ret);
            }
            else if (WSTOPSIG(ret))
            {
                printf("do_system:程序被信号暂停，信号值:%d\n", WSTOPSIG(ret));
                printf("do_system:system ret =%d\n", ret);
            }
        }
    }
    return res;
}
/**
 * @brief   zlog初始化
 * @retval 0 成功，-1 失败
 */
static int log_Init()
{
    int rc = 0;
    char fileName[50];

    sprintf(fileName, LOG_CONFIG ".conf");
    rc = dzlog_init(fileName, "my_cat"); // 0=ok,-1=err
    if (rc)
    {
        zlog_fini();
        return -1;
    }

    return 0;
}

/**
 * @brief 以log形式输出init文件的内容
 */
static void Output_Init_Log()
{
    sysPara *sys_cfg = SysConf_GetInfo();
    int i = 0;
    //[SYSTEM]
    LOG_INFO("lc_slave_addr: %d", sys_cfg->lc_slave_addr);
    LOG_INFO("EMS enable: %d", sys_cfg->emsEnable);
    LOG_INFO("Local EMS port: %d", sys_cfg->localEmsPort);
    LOG_INFO("EMSP1 enable: %d", sys_cfg->emsP1Enable);
    LOG_INFO("Local EMSP1 port: %d", sys_cfg->localEmsP1Port);
    LOG_INFO("Local SCADA port: %d", sys_cfg->localScadaPort);//数据中心链接主控程序的端口
    LOG_INFO("BMS num: %d", sys_cfg->bmsNum);
    LOG_INFO("dbHoldDays: %d", sys_cfg->dbHoldDays);
    LOG_INFO("dbSaveTime: %d s", sys_cfg->dbSaveTime);
    LOG_INFO("EMU num: %d", sys_cfg->emuNum);
    LOG_INFO("pcsModel num: %d", sys_cfg->pcsModelNum);
    LOG_INFO("pcsGroup num: %d", sys_cfg->pcsGroupNum);
    LOG_INFO("meter num: %d", sys_cfg->meterNum);
    LOG_INFO("sydy num: %d", sys_cfg->sydyNum);
    for (i = 0; (i < sys_cfg->bmsNum) && (i < MAX_BMS_NUM); i++)
    {
        LOG_INFO("bms-%d --> brand: %d, ip: %s, port: %d, slave_addr: %d, bms_cluster: %d,bms_temp_num: %d,bms_vol_num: %d,bms_cooler_num: %d",
        i, sys_cfg->bms_brand[i], sys_cfg->bms_ip[i], sys_cfg->bms_port[i], sys_cfg->bms_slave_addr[i], 
        sys_cfg->bms_cluster[i], sys_cfg->bms_temp_num[i], sys_cfg->bms_vol_num[i], sys_cfg->bms_cooler_num[i]);
    }
}
/**
 * @brief 入口主程序
 */
int main(int argc, char *argv[])
{
    UNUSED_PARAM(argc);
    UNUSED_PARAM(argv);
    static int i = 0;

    // zlog初始化
    int ret = 0;
    u32_conv Datatemp1;

    // zlog初始化
    ret = access(LOG_CONFIG, 0); // 如果文件存在，返回0，不存在，返回-1
    if (ret == -1)
    {
        printf("%s is nt exist, create new!\n", LOG_CONFIG);
        mkdir(LOG_CONFIG, 777);
    }
    else
    {
        printf("ZLOG: %s exist!\n", LOG_CONFIG);
    }

    /* zlog日志初始化 */
    if (log_Init() == -1)
    {
        printf("zlog init failed!\n");
        return -1;
    }
    LOG_INFO("Welcome to the local controller program ");
    
    // 读取配置文件init的内容
    AppConf_Init();
    //以log形式输出init文件的内容
    Output_Init_Log();
    sysPara *sys_cfg = SysConf_GetInfo();
   
 

    for (i = 0; i < MAX_DEVICE_NUM; i++)
    {
        pthread_index[i] = i;
    }


    // 设置分离式线程属性
    pthread_attr_t thread_attr;
    pthread_attr_init(&thread_attr);
    pthread_attr_setdetachstate(&thread_attr, PTHREAD_CREATE_DETACHED);
#ifndef ISDEBUG_SHARE_
    // 建立EMS线程
    pthread_t thread_ems_server = 0;
    if (sys_cfg->emsEnable > 0)
    {
        // 建立EMS服务端线程
        // pthread_create(&thread_ems_server, &thread_attr, (void *)Task_EMS_Server, NULL);
        // usleep(1000);
    }
   
 
#endif
    // 初始化定时器，Linux系统一个进程一个定时器
    Timer_Init();
    // 复位所有定时器
    Rset_All_Timer();
    // 共享内存线程
    pthread_t thread_share_ram = 0;
    pthread_create(&thread_share_ram, &thread_attr, (void *)Task_share_ram, NULL);
    usleep(1000);
#ifndef ISDEBUG_SHARE_
    

    // 建立定时检查线程
    pthread_t thread_timed_check = 0;
    pthread_create(&thread_timed_check, &thread_attr, (void *)Task_Timed_Check, NULL);
    usleep(1000);

    // 建立定时工作线程
    pthread_t thread_timed_work = 0;
    pthread_create(&thread_timed_work, &thread_attr, (void *)Task_Timed_Work, NULL);
    usleep(1000);

#ifdef USE_DB 
    pthread_t database_record_pthread;
    pthread_create(&database_record_pthread, NULL, db_task, NULL); // 创建数据库记录线程
    usleep(1000);
#endif
    pthread_t other_work_pthread;
    pthread_create(&other_work_pthread, NULL, other_task, NULL); // 创建数据库记录线程
    usleep(1000);
#endif
    while (1)
    {
        sleep(1); // 延时无效
    }

    exit(0);
}
