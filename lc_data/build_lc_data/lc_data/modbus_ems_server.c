/* ------------------------------------------------------------
 * Copyright (C) 2022
 * File Name : modbus_ems_server.c
 * Project :
 * Description : Modbus TCP通信协议，对接EMS的链接
 * File Created :
 * Author : wujinjin
 * ------------------------------------------------------------
 * Last Modified : 2022/10/08
 * Modified By : jinxue.zhao
 * ------------------------------------------------------------
 * HISTORY : 2022/10/08，修改文件的命名，修改函数的声明
 */

#include "main.h"
#include "timed_check.h"
#include "modbus_ems_server.h"


// 等待客户端的连接
static int new_client_fd = 0;
/**
 * @brief 服务端收发信处理
 * @param[in] _num 线程入参
 */
static void server_handle_data(void)
{
    // 初始化
    const int new_fd_thread = new_client_fd;
    static int volatile connect_num = 0; // 统计链接的客户端数量
    static unsigned int volatile connect_time = 0;          // 统计链接的客户端总次数
    static unsigned int volatile connect_ID_min = UINT_MAX; // 链接的最小序号
    int numbytes = 0;
    u16_conv Temp;
    char buffer[TCP_SERVER_RECV_LEN] = {0};
    char Sendbuffer[TCP_SERVER_RECV_LEN] = {0};
    char LogStr[100] = {0};
    char shortBuf[16] = {0};
    char time_str[36] = {0};
    u16_conv set_sub_half;
    bool is_sub = false;
    bool is_print = false;
    char str_char[2] = "";
    INT16U j = 0;
    INT16U i = 0;
    INT16U AddrStar = 0;
    INT16U year = 0, month = 0, day = 0, hour = 0, min = 0, second = 0;
    INT16U MStar = 0, MLen = 0;
    INT8U dev_add = 0;
    u16_conv RegVal; 
    ////////////////设置接收超时////////////////
    struct timeval rec_TimeOut;
    // EMS通讯正常,全部通信链接均判断正常
    Set_EMS_Comm(0, IsNoFault, TRUE);
    rec_TimeOut.tv_sec = 0;
    rec_TimeOut.tv_usec = (20 * 1000);
    if (setsockopt(new_fd_thread, SOL_SOCKET, SO_RCVTIMEO, (char *)&rec_TimeOut, sizeof(rec_TimeOut)) == -1)
    {
        LOG_INFO("EMS Set socket property failed, SO_RCVTIMEO: %s *Reason: EMS server (fd:%d) ", strerror(errno), new_fd_thread);
        if (new_fd_thread > 0)
        {
            close(new_fd_thread);
        }
        return;
    }
    connect_num++;
    connect_time++;
    LOG_INFO("EMS Client[%d] new connect success! (fd:%d) ", connect_num, new_fd_thread);
    unsigned short *pTimeCnt = malloc(sizeof(unsigned short));
    *pTimeCnt = 0;
    unsigned int *pConnectID = malloc(sizeof(unsigned int));
    *pConnectID = connect_time;
    while (1)
    {
        if ((*pConnectID) < connect_ID_min)
        {
            connect_ID_min = (*pConnectID);
        }
#ifdef NO_EMS_TIMEOUT
        Set_EMS_Comm(0, IsNoFault, TRUE);
#endif
        // 收信
        memset(buffer, 0, sizeof(buffer));
        numbytes = recv(new_fd_thread, buffer, TCP_SERVER_RECV_LEN, 0);
        // 接收错误
        if (((numbytes < 0) && (errno != EAGAIN)) || (numbytes == 0))
        {
            // 连接关闭
            if (numbytes == 0)
            {
                LOG_INFO("EMS close the socket\n");
            }
            // 其他错误
            if ((numbytes < 0) && (errno != EAGAIN))
            {
                LOG_INFO("EMS Other socket fault!\n");
            }
            (*pTimeCnt) = 0;
            if (new_fd_thread > 0)
            {
                close(new_fd_thread);
            }
            connect_num--;
            LOG_INFO("EMS Client[%d] Close the TCP server socket! (fd:%d) ", connect_num, new_fd_thread);
            // 对方关闭连接，或者连接出现错误，则关闭退出线程。
            break;
        }
        // 超时
        else if ((numbytes < 0) && (errno == EAGAIN))
        {
            (*pTimeCnt) += 1;
            if ((*pTimeCnt) > (50 * ((EMS_TIMEOUT_CNT / 100) + 5))) // 600s 清理僵尸进程
            {
                if (new_fd_thread > 0)
                {
                    close(new_fd_thread);
                }
                connect_num--;
                LOG_INFO("EMS Client[%d] Close the TCP server socket! (fd:%d) ", connect_num, new_fd_thread);
                break;
            }
            // printf("Time out(pcs): numbytes = %d, errno = %d\n",numbytes,errno);
        }
        // 对接收到数据进行处理
        else
        {
            // EMS通讯正常
            Set_EMS_Comm(0, IsNoFault, TRUE);
            (*pTimeCnt) = 0;
            // printf("connect_num = %d\n",connect_num);
            // 接收的数据
            Sendbuffer[0] = buffer[0];
            Sendbuffer[1] = buffer[1];
            Sendbuffer[2] = buffer[2];
            Sendbuffer[3] = buffer[3];
            Sendbuffer[4] = buffer[4];
            Sendbuffer[6] = buffer[6];
            Sendbuffer[7] = buffer[7];
            Sendbuffer[8] = buffer[11] * 2;
            dev_add = buffer[6];
            MStar = 9;
            // 请求的起始地址
            Temp.D8[1] = buffer[8];
            Temp.D8[0] = buffer[9];
            
            // 按功能码分
            switch (buffer[7])
            {
            case 0x03:
            case 0x04:
                // 读输入寄存器
                //Read input register
                for (i = 0; (i < buffer[11]) && (MStar < TCP_SERVER_RECV_LEN) && (Temp.D16 < MAX_SYSTEM_TOTAL_DATA_NUM); i++)
                {
                    if(dev_add==1)
                    {
                        RegVal.D16= GET_INPUT(Temp.D16);
                    }
                    else if((dev_add>=2)&&(dev_add<(2+BANK_SIZE)))
                    {
                        int bankN = (dev_add-2);
                        RegVal.D16= GET_R_INPUT(bankN,Temp.D16);
                    }
                    else
                    {
                        break;
                    }
                    Sendbuffer[MStar++] = RegVal.D8[1];
                    Sendbuffer[MStar++] = RegVal.D8[0];
                    Temp.D16++;
                }
                Sendbuffer[5] = Sendbuffer[8] + 3;
                break;
            default:
                break;
            }

            // 返信
            write(new_fd_thread, Sendbuffer, Sendbuffer[5] + 6);

            signal(SIGPIPE, SIG_IGN);
        }
        if ((connect_num >= (MAX_CLIENT_NUM - 1)) && (connect_ID_min == (*pConnectID)))
        {
            if (new_fd_thread > 0)
            {
                close(new_fd_thread);
            }
            connect_num--;
            LOG_INFO("EMS Client[%d] Close the TCP server socket! (fd:%d,connect_ID_min:%d) ", connect_num, new_fd_thread, connect_ID_min);
            break;
        }
    }
    connect_ID_min = UINT_MAX;
    free(pTimeCnt);
    free(pConnectID);
}
/**
 * @brief 创建本地服务端的客户通信线程
 * @param[in] *pserver_fd 服务端fd指针
 * @param[in] handler 客户端通信线程，带参数的线程执行函数
 */
static void Accept_Client_Connect(int *pserver_fd)
{
    
    struct sockaddr_in client_addr = {0};
    socklen_t sin_size = sizeof(struct sockaddr_in);
    memset(&client_addr, 0, sin_size);
    if ((new_client_fd = accept((*pserver_fd), (struct sockaddr *)(&client_addr), &sin_size)) == -1)
    {
        new_client_fd = 0;
    }
    // 开线程处理数据
    else
    {
        //DebugPrint("New Client[%d] connect\n", new_client_fd);
        LOG_INFO("EMS New Client (fd:%d) connect\n", new_client_fd);
           
        pthread_t client_thread_id = 0;
        pthread_attr_t client_thread_attr;
        pthread_attr_init(&client_thread_attr);
        pthread_attr_setdetachstate(&client_thread_attr, PTHREAD_CREATE_DETACHED);
        if (pthread_create(&client_thread_id, &client_thread_attr, (void *)server_handle_data, NULL) == -1)
        {
            //DebugPrint("Client[%d] pthread create Error:%s\n", new_client_fd, strerror(errno));
            LOG_INFO("EMS Client (fd:%d) pthread create Error:%s\n", new_client_fd, strerror(errno));
            close(new_client_fd);
            new_client_fd = 0;
        }
        else
        {
            //DebugPrint("Client[%d] Connect from %s:%d\n", new_client_fd, inet_ntoa(client_addr.sin_addr), ntohs(client_addr.sin_port));
            LOG_INFO("EMS Client (fd:%d) Connect from %s:%d\n", new_client_fd, inet_ntoa(client_addr.sin_addr), ntohs(client_addr.sin_port));
            usleep(10 * 1000);
        }
    }
}
void Task_EMS_Server(void)
{
    // 配置socket资料
    static int sockfd_service = 0;
    static INT32U server_create_count = 0;
    sysPara *sys_cfg = SysConf_GetInfo();
    static in_port_t sin_port;
    sin_port = htons(sys_cfg->localEmsPort);

    // 创建EMS服务端socket
    while (1)
    {
        if ((sockfd_service = Create_Server_Socket(sin_port, MAX_CLIENT_NUM)) == -1)
        {
            // 无通讯故障时打印log，防止log刷屏
            if (Get_EMS_Comm(0) == IsNoFault)
            {
                LOG_INFO("EMS Create server socket failure!, count:%d", server_create_count++);
            }
            sleep(10);
            continue;
        }
        // EMS通讯正常
        LOG_INFO("EMS server[%d] : Create socket success! wait client connect ......", ntohs(sin_port));
        Set_EMS_Comm(0, IsNoFault, TRUE);
        break;
    }

    // 等待客户端的链接
    while (1)
    {
        Accept_Client_Connect(&sockfd_service);
        usleep(20 * 1000);
    }
}
