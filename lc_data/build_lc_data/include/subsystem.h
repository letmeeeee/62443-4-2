/* ------------------------------------------------------------
 * Copyright (C) 2022
 * File Name : subsystem_base.h
 * Project : 基础版LC程序
 * Description : 储能系统内部子系统运行基础版
 * File Created : 2022-09-29
 * Author : jinxue.zhao
 * ------------------------------------------------------------
 * Last Modified : 2022-09-29
 * Modified By : jinxue.zhao
 * ------------------------------------------------------------
 * HISTORY : 新规
 */

#ifndef SUB_SYSTEM_H
#define SUB_SYSTEM_H

/**
 * @brief 子系统故障处理任务
 * @param[in] _item 线程入参
 */
void Sub_System_Fault_Task(const char* _item);

/**
 * @brief 子系统工作处理任务
 * @param[in] _item 线程入参
 */
void Sub_System_Task(const char* _item);

#endif //SUB_SYSTEM_H
