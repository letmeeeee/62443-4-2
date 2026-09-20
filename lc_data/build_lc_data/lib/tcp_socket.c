/* ------------------------------------------------------------
 * Copyright (C) 2022
 * File Name : tcp_socket.c
 * Project : 本地控制器
 * Description : 创建TCP服务，处理基本的TCP业务
 * File Created : 2022/10/11
 * Author : jinxue.zhao
 * ------------------------------------------------------------
 * Last Modified : 2022/10/11
 * Modified By : jinxue.zhao
 * ------------------------------------------------------------
 * HISTORY : 新规
 */

#include "main.h"
#include "tcp_socket.h"

int Create_Client_Socket(struct sockaddr_in server_addr, struct timeval time_out)
{
    // 初始化socket
    int socket_fd = 0;
    if ((socket_fd = socket(AF_INET, SOCK_STREAM, 0)) == -1)
    {
        DebugPrint("Create client socket Error : %s\n", strerror(errno));
        close(socket_fd);
        socket_fd = -1;
        return socket_fd;
    }

    // 设置收发超时
    if (setsockopt(socket_fd, SOL_SOCKET, SO_SNDTIMEO, (char *)&time_out, sizeof(time_out)) == -1)
    {
        DebugPrint("Set client sockopt SO_SNDTIMEO Error : %s\n", strerror(errno));
        close(socket_fd);
        socket_fd = -1;
        return socket_fd;
    }
    if (setsockopt(socket_fd, SOL_SOCKET, SO_RCVTIMEO, (char *)&time_out, sizeof(time_out)) == -1)
    {
        DebugPrint("Set client sockopt SO_RCVTIMEO Error : %s\n", strerror(errno));
        close(socket_fd);
        socket_fd = -1;
        return socket_fd;
    }

    // 连接服务端，默认IPV4
    if (connect(socket_fd, (struct sockaddr *)(&server_addr), sizeof(struct sockaddr)) == -1)
    {
        DebugPrint("Connect Server[ip:%s,port:%d]  Error : %s\n", inet_ntoa(server_addr.sin_addr), ntohs(server_addr.sin_port), strerror(errno));
        close(socket_fd);
        socket_fd = -1;
        return socket_fd;
    }

    return socket_fd;
}

int Create_Server_Socket(in_port_t sin_port, int connections)
{
    // 初始化socket
    int socket_fd = 0;
    if ((socket_fd = socket(AF_INET, SOCK_STREAM, 0)) == -1)
    {
        DebugPrint("Create server socket Error : %s\n", strerror(errno));
        close(socket_fd);
        socket_fd = -1;
        return socket_fd;
    }

    // 设置socket属性
    if (fcntl(socket_fd, F_SETFL, O_NONBLOCK) == -1)
    {
        DebugPrint("Set server socket fcntl Error : %s\n", strerror(errno));
        close(socket_fd);
        socket_fd = -1;
        return socket_fd;
    }

    // 打开地址复用功能
    int optval = 1;
    if (setsockopt(socket_fd, SOL_SOCKET, SO_REUSEADDR, (char *)&optval, sizeof(optval)) == -1)
    {
        DebugPrint("Set client sockopt SO_REUSEADDR Error : %s\n", strerror(errno));
        close(socket_fd);
        socket_fd = -1;
        return socket_fd;
    }

    // 绑定本地服务端端口，默认绑定本地所有IP
    struct sockaddr_in server_addr;
    memset(&server_addr, 0, sizeof(server_addr));
    server_addr.sin_family = AF_INET;
    server_addr.sin_port = sin_port;
    server_addr.sin_addr.s_addr = htonl(INADDR_ANY);
    if (bind(socket_fd, (struct sockaddr *)(&server_addr), sizeof(struct sockaddr)) == -1)
    {
        DebugPrint("Local server bind port:%d, Error : %s\n", ntohs(server_addr.sin_port), strerror(errno));
        close(socket_fd);
        socket_fd = -1;
        return socket_fd;
    }

    // 打开网络监听
    if (listen(socket_fd, connections) == -1)
    {
        DebugPrint("Local server listen[%d] Error : %s\n", connections, strerror(errno));
        close(socket_fd);
        socket_fd = -1;
        return socket_fd;
    }

    return socket_fd;
}



int Monitor_Socket(int socket_fd, struct timeval time_out)
{
    int retval = 0;
    fd_set fs_read;

    FD_ZERO(&fs_read);
    FD_SET(socket_fd, &fs_read);

    retval = select(socket_fd + 1, &fs_read, NULL, NULL, &time_out);
    // 正常
    if (retval > 0)
    {
        return retval;
    }
    // 异常
    else
    {
        // 超时
        if (0 == retval)
        {
            return 0;
        }
        // 发生错误
        else
        {
            return -1;
        }
    }
}

int Recv_Modbus_Back(int socket_fd, int dev_num, int recv_size, DATA_PROCESS handler)
{
    // 初始化socket
    int result = -1;
    int recv_bytes = 0;
    unsigned char recv_buf[NORMAL_BUF_LEN] = {0};

    // 接收返回数据
    memset((char *)recv_buf, 0, sizeof(recv_buf));
    recv_bytes = recv(socket_fd, recv_buf, recv_size, 0);

    // 接收数据异常
    if (((recv_bytes < 0) && (errno != EAGAIN)) || (recv_bytes == 0))
    {
        // 连接关闭
        if (recv_bytes == 0)
        {
            printf("Dev[%d] LC close the socket[%d] recv_bytes == 0\n", dev_num, socket_fd);
            result = -3;
        }
        // 其他错误
        if ((recv_bytes < 0) && (errno != EAGAIN))
        {
            printf("Dev[%d] Other socket[%d] fault! error:%s\n", dev_num, socket_fd, strerror(errno));
            result = -2;
        }

        result = -1;
        close(socket_fd);
        DebugPrint("Dev[%d] LC close the socket[%d], in fault status\n", dev_num, socket_fd);
    }
    else if ((recv_bytes < 0) && (errno == EAGAIN)) // 超时
    {
        // printf("Time out(pcs): numbytes = %d, errno = %d\n",numbytes,errno);
        result = 0;
    }
    // 对接收到数据进行处理, 需要对数据进行格式校验
    else
    {
        // 接收字节数
        result = recv_bytes;
        // 需要增加粘包处理
        handler(recv_buf, dev_num);
    }

    return result;
}
