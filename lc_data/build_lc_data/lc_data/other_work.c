/*
 * Copyright (C) 2023
 * File Name: other_work.c
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
#include "assist_func.h"
#include "trina_log.h"
#include "timed_check.h"
#include "db_work.h"
#include "other_work.h"

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <dirent.h>
#include <errno.h>
#include <pthread.h>
#include <sys/stat.h>
#include <unistd.h>
#include <time.h>


/**
 * @brief 判断一个字符串是否包含另一个字符串
 * @param[in] char *s 字符串指针
 * @param[in] char *c 需要包含的字符
 * @return 返回结果 无
 */
bool is_contain_str(char *s, char *c)
{
    int i = 0, j = 0;
    bool flag = false;
    while (i < strlen(s) && j < strlen(c))
    {
        //如果字符相同则两个字符都增加
        if (s[i] == c[j])
        { 
            i++;
            j++;
        }
        else
        {
            i = i - j + 1; //主串字符回到比较最开始比较的后一个字符
            j = 0;         //字串字符重新开始
        }
        //如果匹配成功
        if (j == strlen(c))
        {                
            flag = true; //字串出现
            break;
        }
    }
    return flag;
}

/**
 * @brief 删除某个字符串中的某一个字符
 * @param[in] char str[] 字符串指针
 * @param[in] char target 需要删除的字符
 * @return 返回结果 无
 */
void delete_char(char str[],char target)
{
	int i,j;
	for(i=0,j=0;str[i]!='\0';i++)
    {
		if(str[i]!=target)
        {
			str[j++]=str[i];
		}
	}
	str[j]='\0';
}

/**
 * @brief 数据库操作任务任务
 * @param[in] void *arg
 * @return 返回结果 无
 */

#ifndef LOG_DIR
#define LOG_DIR "/home/zlgmcu/zlog"
#endif

#ifndef LOG_PREFIX
#define LOG_PREFIX "operation_"
#endif

#define MAX_KEEP_FILES 100



/* 如 GET_INPUT 非线程安全，开启这个锁并在读取时加锁 */
// static pthread_mutex_t g_get_input_lock = PTHREAD_MUTEX_INITIALIZER;

static int ensure_dir_exists(const char *dir)
{
    struct stat st;
    if (stat(dir, &st) == 0) {
        if (S_ISDIR(st.st_mode)) return 0;
        return -1;
    }
    if (mkdir(dir, 0755) == 0) return 0;
    if (errno == EEXIST) return 0;
    return -1;
}

static void format_yyyymmdd(time_t t, char out[9])
{
    struct tm tmv;
    localtime_r(&t, &tmv);
    snprintf(out, 9, "%04d%02d%02d",
             tmv.tm_year + 1900, tmv.tm_mon + 1, tmv.tm_mday);
}

static void format_datetime_s(time_t t, char out[20])
{
    struct tm tmv;
    localtime_r(&t, &tmv);
    snprintf(out, 20, "%04d-%02d-%02d %02d:%02d:%02d",
             tmv.tm_year + 1900, tmv.tm_mon + 1, tmv.tm_mday,
             tmv.tm_hour, tmv.tm_min, tmv.tm_sec);
}

static int starts_with(const char *s, const char *prefix)
{
    return strncmp(s, prefix, strlen(prefix)) == 0;
}

static int ends_with(const char *s, const char *suffix)
{
    size_t ls = strlen(s), lf = strlen(suffix);
    if (ls < lf) return 0;
    return strcmp(s + (ls - lf), suffix) == 0;
}

/* 从文件名 operation_YYYYMMDD.csv 提取 YYYYMMDD，成功返回 0 */
static int parse_date_from_filename(const char *name, char yyyymmdd[9])
{
    const char *prefix = LOG_PREFIX;
    const char *suffix = ".csv";

    if (!starts_with(name, prefix)) return -1;
    if (!ends_with(name, suffix)) return -1;

    size_t pfx = strlen(prefix);
    size_t len = strlen(name);

    /* operation_ + 8位日期 + .csv  => 最少 pfx+8+4 */
    if (len < pfx + 8 + strlen(suffix)) return -1;

    /* 截取日期部分 */
    memcpy(yyyymmdd, name + pfx, 8);
    yyyymmdd[8] = '\0';

    /* 简单校验：必须全是数字 */
    for (int i = 0; i < 8; ++i) {
        if (yyyymmdd[i] < '0' || yyyymmdd[i] > '9') return -1;
    }
    return 0;
}

typedef struct {
    char name[256];
    char date[9]; /* YYYYMMDD */
} log_file_item_t;

static int cmp_by_date_asc(const void *a, const void *b)
{
    const log_file_item_t *fa = (const log_file_item_t *)a;
    const log_file_item_t *fb = (const log_file_item_t *)b;
    return strcmp(fa->date, fb->date);
}

/* 保留最新 MAX_KEEP_FILES 个，删除更旧的 */
static void cleanup_old_logs(void)
{
    DIR *d = opendir(LOG_DIR);
    if (!d) return;

    log_file_item_t *items = NULL;
    size_t count = 0, cap = 0;

    struct dirent *ent;
    while ((ent = readdir(d)) != NULL) {

        /* 跳过 . 和 .. */
        if (strcmp(ent->d_name, ".") == 0 || strcmp(ent->d_name, "..") == 0)
            continue;

        /* 先按命名规则过滤：operation_YYYYMMDD.csv */
        char date[9];
        if (parse_date_from_filename(ent->d_name, date) != 0)
            continue;

        /* 用 stat 判断是否普通文件（完全不依赖 d_type / DT_REG / DT_UNKNOWN） */
        char fullpath[512];
        snprintf(fullpath, sizeof(fullpath), "%s/%s", LOG_DIR, ent->d_name);

        struct stat st;
        if (stat(fullpath, &st) != 0) {
            /* 可能文件被并发删除/权限问题，忽略即可 */
            continue;
        }
        if (!S_ISREG(st.st_mode)) {
            /* 非普通文件（目录/符号链接/设备文件等）跳过 */
            continue;
        }

        /* 动态扩容 */
        if (count == cap) {
            size_t newcap = (cap == 0) ? 64 : cap * 2;
            log_file_item_t *tmp = (log_file_item_t *)realloc(items, newcap * sizeof(*items));
            if (!tmp) {
                /* 内存不足：退出循环，后面会按已收集到的 items 处理 */
                break;
            }
            items = tmp;
            cap = newcap;
        }

        /* 记录条目 */
        snprintf(items[count].name, sizeof(items[count].name), "%s", ent->d_name);
        snprintf(items[count].date, sizeof(items[count].date), "%s", date);
        count++;
    }

    closedir(d);

    if (!items || count <= MAX_KEEP_FILES) {
        free(items);
        return;
    }

    /* 按日期升序（最旧在前） */
    qsort(items, count, sizeof(*items), cmp_by_date_asc);

    /* 删除多余的最旧文件 */
    size_t need_delete = count - MAX_KEEP_FILES;
    for (size_t i = 0; i < need_delete; ++i) {
        char fullpath[512];
        snprintf(fullpath, sizeof(fullpath), "%s/%s", LOG_DIR, items[i].name);
        (void)remove(fullpath); /* 删除失败也不影响主流程 */
    }

    free(items);
}

static FILE *open_daily_csv(const char yyyymmdd[9], char out_path[512])
{
    snprintf(out_path, 512, "%s/%s%s.csv", LOG_DIR, LOG_PREFIX, yyyymmdd);

    int existed = (access(out_path, F_OK) == 0);

    FILE *fp = fopen(out_path, "a");
    if (!fp) return NULL;


    if (!existed) {
        fprintf(fp, "time,value\n");
        fflush(fp);
    }
    return fp;
}

void *other_task(void *arg)
{
    (void)arg;

    if (ensure_dir_exists(LOG_DIR) != 0) {
        /* 目录无法创建，线程直接退出或持续重试都可以，这里选择退出 */
        return NULL;
    }

    char current_day[9] = {0};
    FILE *fp = NULL;
    char csv_path[512] = {0};
   sleep(30);
    while (1) {
        sleep(1);

        time_t now = time(NULL);

        char day[9];
        format_yyyymmdd(now, day);

        /* 日期变化或首次打开：切换文件 */
        if (fp == NULL || strcmp(day, current_day) != 0) {
            if (fp) {
                fclose(fp);
                fp = NULL;
            }

            snprintf(current_day, sizeof(current_day), "%s", day);

            fp = open_daily_csv(current_day, csv_path);
            if (!fp) {
                /* 打不开文件：下一轮再试 */
                continue;
            }

            /* 每天首次打开后，做一次清理（保证最多 100 张） */
            cleanup_old_logs();
        }

        char ts[20];
        format_datetime_s(now, ts);

        /* 读取 GET_INPUT(106) */
        uint16_t v;
        // pthread_mutex_lock(&g_get_input_lock);
        v = GET_INPUT(106);
        // pthread_mutex_unlock(&g_get_input_lock);

        /* 追加一行 CSV */
        fprintf(fp, "%s,%u\n", ts, v);

        /* 建议每行 flush，避免掉电丢数据；如果担心 IO，可改为每 N 行 flush */
        fflush(fp);
    }

    /* 正常不会到这里 */
    if (fp) fclose(fp);
    return NULL;
}

