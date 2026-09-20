
#ifndef OTHER_WORK_H
#define OTHER_WORK_H

//MAC_1字符串指针
extern char *const pMAC_1;
//pMAC_1_No字符串指针
extern char *const pMAC_1_No;


#ifdef __cplusplus
extern "C"
{
#endif

/**
 * @brief 杂项任务
 * @param[in] void *arg
 * @return 返回结果 无
 */
void *other_task(void *arg);
#ifdef __cplusplus
}
#endif
#endif
