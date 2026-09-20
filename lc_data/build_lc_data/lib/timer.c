/*
 * Copyright (C) 2022
 * File Name: timed.c
 * Project:
 * Description: 定时器、超时判定
 * File Created:
 * Author: wujinjin
 * -----
 * Last Modified:
 * Modified By:
 * -----
 * HISTORY:
 */

#include "main.h"
#include "timer.h"

//!定时器变量
INT32U Timer_Tick = 0;                               //系统TICK
INT32U volatile TIMEOUT_TIMER[TIMER_CNT] = {0};               //超时检测定时器定义


unsigned int Timer_GetTick()
{
    return Timer_Tick;    //10ms精度
}

void Rset_Timer(unsigned short num)
{
    TIMEOUT_TIMER[num] = Timer_GetTick();
}

void Rset_All_Timer()
{
    INT32U i = 0;
    for(i = 0; i < TIMER_CNT; i++)
    {
        TIMEOUT_TIMER[i] = Timer_GetTick();
    }
}

void Timer_Callback(int signo)
{
    if(signo == SIGALRM)
    {
        Timer_Tick++;
        if(Timer_Tick > 0xFFFF0000) //避免tick溢出，定时器失效
        {
            Timer_Tick = 0;
            Rset_All_Timer();
            LOG_INFO("system time tick reset");
        }
    }
}

void Timer_Init()
{
    signal(SIGALRM, Timer_Callback);

    struct itimerval value, ovalue;
    value.it_value.tv_sec = 0;
    value.it_value.tv_usec = TICK_TIME * 1000;
    value.it_interval = value.it_value;

    setitimer(ITIMER_REAL, &value, &ovalue);
    return;
}
