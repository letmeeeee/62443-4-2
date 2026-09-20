/*
 * Copyright (C) 2023
 * File Name: db_work_ex.c
 * Project:
 * Description:数据库操作模块的补充
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
#include "db_work_ex.h"
#include "other_work.h"
//时间戳
static uint32_t Time_stamp;
//时间结构体
struct tm tm_m;
unsigned int ttvalue[6];
/**
 * @brief 获取文件大小
 * @param[in] char* filename 文件路径名称
 * @return 返回结果 文件大小
 */
int file_size(char *filename)
{
	struct stat sta;
	stat(filename, &sta);
	int size = sta.st_size;
	return size;
}


//每月天数
const static uint8_t st_ucMonthDays[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
/**
 * @brief 时间戳转换
 * @return 返回结果 时间戳
 */
int64_t lTimeToStamp(TimeType *ptypeTime)
{
	int64_t lDaysNumber = 0, lStamp = 0;
	int32_t lYearTemp = 1970;
	uint8_t ucMonthTemp = 1;
	for (lYearTemp = 1970; lYearTemp < ptypeTime->year; ++lYearTemp)
	{
		lDaysNumber += DAYS_OF_THE_YEAR(lYearTemp); // 按闰年或平年来计算年数并*365或366换算成日数
	}
	for (ucMonthTemp = 1; ucMonthTemp < ptypeTime->month; ++ucMonthTemp)
	{
		lDaysNumber += DAYS_OF_THE_MONTH(ptypeTime->year, ucMonthTemp); // 按全年的月内日数结合闰年的二月日数换算成日数
	}
	lDaysNumber += ptypeTime->day - 1; // 当日的号数折合计算的时候,不能算入,日数是历史日数,上一天计入

	lStamp = lDaysNumber * 86400;	  // 全部日数(年日数、月日数、天日数)换算成秒数
	lStamp += ptypeTime->hour * 3600; // 小时数换算成秒数
	lStamp += ptypeTime->minute * 60; // 分钟数换算成秒数
	lStamp += ptypeTime->second;	  // 秒数做尾巴加上去

	lStamp -= ptypeTime->cUTC * 3600; // 世界时归一化,东八区的时间偏差,在中国这边时间里已经初默加8了,故换算回西方时间需要减掉8个小时的秒数

	return lStamp;
}
/**
 * @brief 刷新时间戳
 * @return 返回结果 时间戳
 */
void flash_local_Time_stamp(void)
{
	static time_t timer;
	static struct tm *tblock;
	static TimeType tt_Stamp;
	char TimeStamp[15];
	int64_t res;
	
	// printf("%04d年%02d月%02d日%02d时%02d分%02d秒", ttvalue[0], ttvalue[1], ttvalue[2], ttvalue[3], ttvalue[4], ttvalue[5]); // 只是为了打印以下
	tt_Stamp.year = ttvalue[0];
	tt_Stamp.month = ttvalue[1];
	tt_Stamp.day = ttvalue[2];
	tt_Stamp.hour = ttvalue[3];
	tt_Stamp.minute = ttvalue[4];
	tt_Stamp.second = ttvalue[5];
	tt_Stamp.cUTC = 8;
	res = lTimeToStamp(&tt_Stamp);
	sprintf(TimeStamp, "%ld", res);
	// printf("-%s\n", TimeStamp); // 打印以下
	Time_stamp = (uint32_t)res;
}
/**
 * @brief 获取时间戳
 * @return 返回结果 时间戳
 */
uint32_t now_to_stamp(void)
{
	return Time_stamp;
}

// void getDate(long long ts, char *str)
// {
// 	time_t t;
// 	struct tm *p;
// 	t = ts / 1000;
// 	uint8_t nn, yy, rr, ss, ff, mm;
// 	p = localtime(&t);
// 	sprintf(str, "%04d-%02d-%02dT%02d:%02d:%02d",
// 			p->tm_year + 1900, p->tm_mon + 1, p->tm_mday, p->tm_hour, p->tm_min, p->tm_sec);
// }
