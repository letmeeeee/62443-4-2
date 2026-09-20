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
#include "timed_check.h"

static INT8U ems_comm_fault[1] = {0};                       //EMS通讯故障标志位，1-通讯故障，0-正常





INT8U Get_EMS_Comm(INT8U num)
{
    
    return ems_comm_fault[0];
}

void Set_EMS_Comm(INT8U num, INT8U status,INT8U isreset)
{
    
    ems_comm_fault[0] = status;
    if((status == IsNoFault)&&(TRUE==isreset))
    {
        Rset_Timer(EMS_TIMER_BASE + 0);    //没有超时，则自动把定时器复位
    }
}



/**
 * @brief 初始化通讯故障位
 */
static void Init_Fault_Flag()
{
    int i = 0;
   
}


/********************************************通讯超时检测************************************************/

/**
 * @brief 设备通讯超时检测
 * @param[in] dev_name 设备名称
 * @param[in] dev_num 设备数量
 * @param[in] timer 定时器序号
 * @param[in] timeout 定时器超时时间
 * @param[in] set_handler 通讯状态设置函数声明
 * @param[in] get_handler 通讯状态获取函数声明
 * @param[in] data_pos 设备状态点表位置
 */
static void Check_Dev_Timeout(char* dev_name, INT8U dev_num, INT16U timer, INT32U timeout,
                              COMM_SET set_handler, COMM_GET get_handler, INT32U data_pos)
{
    int i = 0;
    INT32U curtime;
    INT32U timewarn; //提前重连时间
    static INT16U faultFlag[200] = {0};
    for(i = 0; (i < dev_num) && ((timer + i) < TIMER_CNT); i++)
    {
        //超时设置设备通讯故障状态
        curtime = Timer_GetTick() - TIMEOUT_TIMER[timer + i];
        timewarn = timeout/4;//
        if(curtime >= timeout)
        {
            set_handler(i, IsFault,TRUE);
        }
        else if((curtime/20>0)&&(((curtime/20)%(timewarn/20))==0))//提示重连,不做定时器复位
        {
            set_handler(i, IsWarn,FALSE);
        }
        //有故障
        if(get_handler(i) == IsFault)
        {
            if(GetBit(faultFlag[data_pos], i) != 1)
            {
                SetBit(faultFlag[data_pos], i);        //设备通信故障
                LOG_INFO("%s-%d timeout fault generated: [%x] ", dev_name, i, faultFlag[data_pos]);
            }
        }
        //没故障
        else
        {
            if(GetBit(faultFlag[data_pos], i) != 0)
            {
                ClearBit(faultFlag[data_pos], i);      //设备通信正常
                LOG_INFO("%s-%d timeout fault removal: [%x] ", dev_name, i, faultFlag[data_pos]);
            }
        }
    } //loop
}



/**
 * @brief  定时任务集合
 * @note
 * @retval
 */
void Task_Timed_Check(void)
{
    //初始化
    int i = 0;
    sysPara* sys_cfg = SysConf_GetInfo();
    LOG_INFO("Check Fault Task start! ");

    //初始化通讯故障位
    Init_Fault_Flag();

    while(1)
    {
        /********************************************故障/告警检测************************************************/
        //故障/告警检测
        if((Timer_GetTick() - TIMEOUT_TIMER[FALUT_CHECK_TIMER]) >= WARN_FAULT_TIMEOUT_CNT)
        {
            
          
            //轮询周期50ms
            TIMEOUT_TIMER[FALUT_CHECK_TIMER] = Timer_GetTick();
        }

        /********************************************通讯超时检测************************************************/

       
        //EMS超时检测
        Check_Dev_Timeout("EMS", 1, EMS_TIMER_BASE, EMS_TIMEOUT_CNT, Set_EMS_Comm, Get_EMS_Comm, 0);

     
        usleep(10 * 1000); //10ms
    }
}
