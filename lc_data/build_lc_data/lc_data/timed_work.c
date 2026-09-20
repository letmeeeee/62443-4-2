/* ------------------------------------------------------------
 * Copyright (C) 2022
 * File Name : timed.c
 * Project :
 * Description : 定时器、超时判定
 * File Created :
 * Author : wujinjin
 * ------------------------------------------------------------
 * Last Modified :
 * Modified By :
 * ------------------------------------------------------------
 * HISTORY :
 */

#include "main.h"
#include "timed_work.h"
#include "db_work_ex.h"

/**
 * @brief  time_section_test() -  检测当前时间所在时段
 * @param[in] h  - 当前时间小时
 * @param[in] m  - 当前时间分钟
 * @param[in] p  - 时段设置
 * @return 当前时间在开始时间和结束时间之间时返回1，否则返回0
 */
static unsigned char time_section_test(unsigned short h, unsigned short m, period* p)
{
    //当前小时和分钟,根据实际给出
    unsigned short strDateH = h;
    unsigned short strDateM = m;

    //开始时间
    unsigned short strDateBeginH = p->bh;      //开始小时
    unsigned short strDateBeginM = p->bm;      //开始分钟

    //结束时间
    unsigned short strDateEndH = p->eh;        //结束小时
    unsigned short strDateEndM = p->em;        //结束分钟

    //跨天
    if(strDateEndH < strDateBeginH)
    {
        if((strDateH > strDateEndH) && (strDateH < strDateBeginH))
        {
            return 0;
        }
        else if((strDateH == strDateEndH) && (strDateH < strDateBeginH) && (strDateM > strDateEndM))
        {
            return 0;
        }
        else if((strDateH > strDateEndH) && (strDateH == strDateBeginH)    && (strDateM < strDateBeginM))
        {
            return 0;
        }
        else
        {
            return 1;
        }
    }
    else
    {
        if((strDateH > strDateBeginH) && (strDateH < strDateEndH))
        {
            return 1;
        }
        else if((strDateH == strDateBeginH) && (strDateH < strDateEndH) && (strDateM >= strDateBeginM))
        {
            return 1;
        }
        else if((strDateH > strDateBeginH) && (strDateH == strDateEndH) && (strDateM <= strDateEndM))
        {
            return 1;
        }
        else if((strDateH == strDateBeginH) && (strDateH == strDateEndH) && (strDateM >= strDateBeginM) && (strDateM <= strDateEndM))
        {
            return 1;
        }
        else
        {
            return 0;
        }
    }

    return 0;
}
static long MSecs = 0;
/**
 * @brief 获取时间戳
 */
long GetMSecsSinceEpoch()
{
    return MSecs;
}
/**
 * @brief 计算时间戳
 */
long GetMSecsSinceloop()
{
    struct timeb timestamp = {};

    if (0 == ftime(&timestamp))
        return timestamp.time * 1000 + timestamp.millitm;
    else
        return 0;
}
/**
 * @brief 定时任务集合
 */
void Task_Timed_Work(void)
{
    int i = 0, ret = 0;
    char longBuf[64] = {0}, shortBuf[16] = {0};
    time_t timer = 0;
    static unsigned short second_cnt = 0; 
    struct tm* tblock = NULL;
    static unsigned char current_period = 0, current_period_pre = 0;
    u32_conv Datatemp1;
    sysPara* sys_cfg = SysConf_GetInfo();
    LOG_INFO("system timed task start");
    while(1)
    {
        //系统心跳，1s周期
        if((Timer_GetTick() - TIMEOUT_TIMER[SYSTEM_TIMER]) >= SYS_CNT) //100*10ms
        {
            if(second_cnt++>=3600)
            {
              second_cnt=0;
            }
            TIMEOUT_TIMER[SYSTEM_TIMER] = Timer_GetTick();
            timer = time(NULL);  //直接就是时间戳 time_t timer
            tblock = localtime(&timer); //struct tm *tblock; 变成2022-07-25 17:23:12
            ttvalue[0] = tblock->tm_year + 1900;
            ttvalue[1] = tblock->tm_mon + 1;
            ttvalue[2] = tblock->tm_mday;
            ttvalue[3] = tblock->tm_hour;
            ttvalue[4] = tblock->tm_min;
            ttvalue[5] = tblock->tm_sec;
        }
            
       
        MSecs = GetMSecsSinceloop();
      
        usleep(10 * 1000); //10ms
    }
}
