/* ------------------------------------------------------------
 * Copyright (C) 2022
 * File Name : subsystem.h
 * Project :
 * Description : 储能系统内部子系统运行
 * File Created :
 * Author : wujinjin
 * ------------------------------------------------------------
 * Last Modified :
 * Modified By :
 * ------------------------------------------------------------
 * HISTORY :
 */

#ifndef SUB_SYSTEM_V1_H
#define SUB_SYSTEM_V1_H

/**
 * @brief 子系统V1故障处理任务
 * @param[in] _item 线程入参
 */
void Sub_System_V1_Fault_Task(const char* _item);

/**
 * @brief 子系统V1工作处理任务
 * @param[in] _item 线程入参
 */
void Sub_System_V1_Task(const char* _item);

#endif //SUB_SYSTEM_V1_H
