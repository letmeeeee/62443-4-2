
#ifndef DB_WORK_H
#define DB_WORK_H
#ifndef USER_LEAP_YEAR
#define USER_LEAP_YEAR 1
#endif // LEAP_YEAR
#ifndef USER_COMMON_YEAR
#define USER_COMMON_YEAR 0
#endif //
#define YEAR_LEAP(year) (((((year) % 4 == 0) && ((year) % 100 != 0)) || (((year) % 400 == 0) && ((year) % 3200 != 0)) || ((year) % 172800 == 0)) ? USER_LEAP_YEAR : USER_COMMON_YEAR)
#define DAYS_OF_THE_YEAR(year) (YEAR_LEAP(year) == USER_LEAP_YEAR ? 366 : 365)
#define DAYS_OF_THE_MONTH(year, month) ((((month) == 2) && (YEAR_LEAP(year) == USER_LEAP_YEAR)) ? 29 : st_ucMonthDays[(month)-1])
#define DB_HOLD_DAYS "3"  // 数据保持时间
#define DB_SAVE_TIME (20) // 数据库存储周期时间
typedef struct
{
    int32_t year;
    uint8_t month;
    uint8_t day;
    uint8_t hour;
    uint8_t minute;
    uint8_t second;
    uint8_t week;
    int8_t cUTC;
} TimeType;

typedef struct
{
    uint16_t start;
    uint16_t end;
} TableAddressStruct;


/**
 * @brief 获取时间戳
 * @return 返回结果 时间戳
 */
uint32_t now_to_stamp(void);
void flash_local_Time_stamp(void);
/**
 * @brief 插入系统信息数据存储到数据库
 * @param[in] 无
 * @return 返回结果 无
 */
int Deal_database();
#ifdef __cplusplus
extern "C"
{
#endif

    /**
     * @brief 数据库操作任务任务
     * @param[in] void *arg
     * @return 返回结果 无
     */
    void *db_task(void *arg);
#ifdef __cplusplus
}
#endif
#endif
