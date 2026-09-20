/* ------------------------------------------------------------
 * Copyright (C) 2022
 * File Name : trina_log.h
 * Project : 本地控制器基础版代码
 * Description : 日志输出
 * File Created : 2022/11/11
 * Author : jinxue.zhao
 * ------------------------------------------------------------
 * Last Modified : 2022/11/11
 * Modified By : jinxue.zhao
 * ------------------------------------------------------------
 * HISTORY : 新规
 */

#ifndef TRINA_LOG_H
#define TRINA_LOG_H

/* Make this header file easier to include in C++ code */
#ifdef __cplusplus
extern "C" {
#endif

#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include <pthread.h>
#include "log.h"


//线程锁，强制同步全局变量数据
static pthread_mutex_t MS_TRINA_LOG_MUTEX = PTHREAD_MUTEX_INITIALIZER;
//日志的默认值
#define TRINA_LOG_MSG_LIST     (5)         //LOG列表的容量
#define TRINA_LOG_MSG_LEN      (1024)      //单条LOG的长度
#define TRINA_LOG_PRINT_COUNT  (100)       //同种log禁止输出的最大极限
//日志的缓存区，使用static可以避免多个文件间缓存的冲突
static char MS_SRC_BUFF[TRINA_LOG_MSG_LEN] = {0};                             //源标字符串缓存区
static char MS_DST_BUFF[TRINA_LOG_MSG_LIST][TRINA_LOG_MSG_LEN] = {{0}};       //目标字符串缓存区
static volatile unsigned int MS_TRINA_LOG_COUNT[TRINA_LOG_MSG_LIST] = {0};    //同种log内容统计值

//通知日志新编宏
#define TRINA_LOG_INFO(format, ...)    do \
{ \
    /* 将日志内容存入源地址缓存中 */ \
    pthread_mutex_lock(&MS_TRINA_LOG_MUTEX); \
    memset(MS_SRC_BUFF, 0, TRINA_LOG_MSG_LEN); \
    sprintf(MS_SRC_BUFF, format, ##__VA_ARGS__); \
    int MS_LOG_STRCMP_COUNT = 0; \
    int MS_LOG_SUM_COUNT = 0; \
    /* 校验日志是否重复输出，并校验重复输出的日志是否超限 */  \
    for(int i = 0; i < TRINA_LOG_MSG_LIST; i++) \
    { \
        if(strcmp(MS_DST_BUFF[i], MS_SRC_BUFF) == 0) \
        { \
            MS_LOG_STRCMP_COUNT++; \
            if(MS_TRINA_LOG_COUNT[i]++ > TRINA_LOG_PRINT_COUNT) \
            { \
                MS_TRINA_LOG_COUNT[i] = 0; \
                MS_LOG_SUM_COUNT++; \
            } \
            break; \
        } \
    } \
    /* 将新增日志追加到缓存队列中 */ \
    if(MS_LOG_STRCMP_COUNT == 0) \
    { \
        for(int i = TRINA_LOG_MSG_LIST; (i - 1) >= 0; i--) \
        { \
            memset(MS_DST_BUFF[i], 0, TRINA_LOG_MSG_LEN); \
            strcpy(MS_DST_BUFF[i], MS_DST_BUFF[i - 1]); \
        } \
        memset(MS_DST_BUFF[0], 0, TRINA_LOG_MSG_LEN); \
        strcpy(MS_DST_BUFF[0], MS_SRC_BUFF); \
        MS_TRINA_LOG_COUNT[0] = 0; \
    } \
    pthread_mutex_unlock(&MS_TRINA_LOG_MUTEX); \
    /* 输出新增日志和超限日志 */ \
    if(MS_LOG_STRCMP_COUNT == 0 || MS_LOG_SUM_COUNT != 0)  \
    { \
        LOG_INFO("%s", MS_SRC_BUFF); \
    } \
}while(0)

#ifdef __cplusplus
}
#endif

#endif // TRINA_LOG_H
