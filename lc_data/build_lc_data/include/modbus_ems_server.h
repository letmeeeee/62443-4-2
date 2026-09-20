/* ------------------------------------------------------------
 * Copyright (C) 2022
 * File Name : modbus_ems_server.h
 * Project :
 * Description : Modbus TCP通信协议，对接EMS的链接
 * File Created : 2022/10/08
 * Author : jinxue.zhao
 * ------------------------------------------------------------
 * Last Modified : 2022/10/08
 * Modified By : jinxue.zhao
 * ------------------------------------------------------------
 * HISTORY : 2022/10/08，修改文件的命名，修改函数的声明
 */

#ifndef MODBUS_EMS_SERVER_H
#define MODBUS_EMS_SERVER_H

/**
 * @brief EMS服务器通信线程
 */
void Task_EMS_Server(void);


/***************************************EMS服务器通信定义************************************/

//读取
#define TCP_SERVER_RECV_LEN (300)  //接收的缓存长度

#endif //MODBUS_EMS_SERVER_H
