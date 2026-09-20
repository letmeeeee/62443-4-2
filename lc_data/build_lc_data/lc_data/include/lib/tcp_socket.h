/* ------------------------------------------------------------
 * Copyright (C) 2022
 * File Name : tcp_socket.h
 * Project : 本地控制器
 * Description : 创建TCP服务，处理基本的TCP业务
 * File Created : 2022/10/11
 * Author : jinxue.zhao
 * ------------------------------------------------------------
 * Last Modified : 2022/12/05
 * Modified By : jinxue.zhao
 * ------------------------------------------------------------
 * HISTORY : 2022/12/05 添加cpp适配宏
 * ------------------------------------------------------------
 * HISTORY : 2022/10/11 新规
 */

#ifndef TCP_SOCKET_H
#define TCP_SOCKET_H

/* Make this header file easier to include in C++ code */
#ifdef __cplusplus
extern "C" {
#endif

#include <linux/sockios.h>
#include <netinet/in.h>


/***************************************TCP服务定义************************************/

#define NORMAL_BUF_LEN  1024  //通用缓存的容量
//线程执行函数声明类型
typedef void (*PTHREAD_HANDLER)(int* pthread_value);
//数据处理函数声明类型
typedef void (*DATA_PROCESS)(unsigned char* data_buf, int dev_num);


/**
 * @brief 创建本地客户端socket
 * @param[in] server_addr 服务端地址和端口
 * @param[in] time_out 收发时限
 * @return 本地客户端fd
 */
int Create_Client_Socket(struct sockaddr_in server_addr, struct timeval time_out);

/**
 * @brief 创建本地服务端socket
 * @param[in] sin_port 服务端端口，将主机的无符号短整形数转换成网络字节顺序
 * @param[in] connections 监听数量，允许连接客户端的最大数量
 * @return 本地服务端fd
 */
int Create_Server_Socket(in_port_t sin_port, int connections);


/**
 * @brief 监视文件描述符（套接字）
 * @param[in] socket_fd 套接字
 * @param[in] time_out 监视时限
 * @return 监视结果，大于是有读写，-1是无读写，0是超时
 */
int Monitor_Socket(int socket_fd, struct timeval time_out);

/**
 * @brief 接收MODBUS返回数据的通用处理
 * @param[in] server_fd 服务端fd
 * @param[in] dev_num 接收设备的编号
 * @param[in] recv_size 接收的数据大小
 * @param[in] handler 返回数据的处理函数，带参数的执行函数
 */
int Recv_Modbus_Back(int socket_fd, int dev_num, int recv_size, DATA_PROCESS handler);

#ifdef __cplusplus
}
#endif

#endif //TCP_SOCKET_H
