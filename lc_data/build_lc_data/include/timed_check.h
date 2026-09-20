/* ------------------------------------------------------------
 * Copyright (C) 2022
 * File Name : timed.h
 * Project :
 * Description : 定时器、超时判定
 * File Created :
 * Author : wujinjin
 * ------------------------------------------------------------
 * Last Modified : 2022/12/05
 * Modified By : jinxue.zhao
 * ------------------------------------------------------------
 * HISTORY : 2022/12/05 增加系统系统断电超时和UPS断电超时两个判断函数
 * ------------------------------------------------------------
 * HISTORY : 2022/10/26 修改文件名和宏定义、调整task函数的结构
 */

#ifndef TIMED_CHECK_H
#define TIMED_CHECK_H

#include "system.h"


INT8U Get_BMS_Comm(INT8U num);

/**
 * @brief 设置BMS通讯状态
 * @param[in] num 定时器序号 第几个bms,0代表第一台
 * @param[in] status 状态 0-正常，1-通讯故障
 * @param[in] isreset 是否做定时器复位 
 */
void Set_BMS_Comm(INT8U num, INT8U status,INT8U isreset);

/**
 * @brief 返回EMS通讯状态
 * @param[in] num 定时器序号
 * @return 状态
 */
INT8U Get_EMS_Comm(INT8U num);

/**
 * @brief 设置EMS通讯状态
 * @param[in] num 定时器序号 第几个测控装置
 * @param[in] status 状态 0-正常，1-通讯故障
 * @param[in] isreset 是否做定时器复位 
 */
void Set_EMS_Comm(INT8U num, INT8U status,INT8U isreset);

/**
 * @brief 定时器线程
 */
void Task_Timed_Check(void);


/***************************************超时检查的宏定义************************************/
#define TIMED_CHECK_OUT_BOUNDS    2  //返回定时器状态的数组越界结果


#endif //TIMED_CHECK_H
