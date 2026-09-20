/* ------------------------------------------------------------
 * Copyright (C) 2022
 * File Name : ModbusProtocol.c
 * Project : 本地控制器
 * Description : Modbus通信协议
 * File Created : 2022/09/23
 * Author: jinxue.zhao
 * ------------------------------------------------------------
 * Last Modified : 2022/09/23
 * Modified By : jinxue.zhao
 * ------------------------------------------------------------
 * HISTORY : 新规
 */

#include "main.h"
#include "modbus_protocol.h"

void Modbus_TCP_Read(int socket_fd, uint8_t device_id, uint8_t cmd_type, uint16_t start_addr, uint16_t length, uint32_t delay_time)
{
    // 初期化
    u16_conv addr, len;
    addr.D16 = start_addr;
    len.D16 = length;
    unsigned char SendBuffer[16] = {0};

    // 事务元识别符，2byte
    SendBuffer[0] = addr.D8[1];
    SendBuffer[1] = addr.D8[0];
    // 协议标识符，2byte
    SendBuffer[2] = 0;
    SendBuffer[3] = 0;
    // 长度，2byte
    SendBuffer[4] = 0;
    SendBuffer[5] = 0x06;
    // 单元标识符，1byte
    SendBuffer[6] = device_id;
    // 功能码，1byte
    SendBuffer[7] = cmd_type;
    // 寄存器地址，高在前，2byte
    SendBuffer[8] = addr.D8[1];
    SendBuffer[9] = addr.D8[0];
    // 寄存器数量，高在前，2byte
    SendBuffer[10] = len.D8[1];
    SendBuffer[11] = len.D8[0];
    // 发送
    write(socket_fd, SendBuffer, 12);
    // 在服务器断开链接时，防止程序中断
    signal(SIGPIPE, SIG_IGN);
    // 命令下发后延迟读取
    usleep(delay_time);
}

void Modbus_TCP_Read01_SingleCoil(int socket_fd, uint16_t start_addr, uint16_t length, uint32_t delay_time)
{
    Modbus_TCP_Read(socket_fd, MODBUS_DEFAULT_DEV, MODBUS_READ_TYPE_01, start_addr, length, delay_time);
}

void Modbus_TCP_Read02_InputDiscrete(int socket_fd, uint16_t start_addr, uint16_t length, uint32_t delay_time)
{
    Modbus_TCP_Read(socket_fd, MODBUS_DEFAULT_DEV, MODBUS_READ_TYPE_02, start_addr, length, delay_time);
}

void Modbus_TCP_Read03_HoldRegist(int socket_fd, uint16_t start_addr, uint16_t length, uint32_t delay_time)
{
    Modbus_TCP_Read(socket_fd, MODBUS_DEFAULT_DEV, MODBUS_READ_TYPE_03, start_addr, length, delay_time);
}

void Modbus_TCP_Read04_InputRegist(int socket_fd, uint16_t start_addr, uint16_t length, uint32_t delay_time)
{
    Modbus_TCP_Read(socket_fd, MODBUS_DEFAULT_DEV, MODBUS_READ_TYPE_04, start_addr, length, delay_time);
}

void Modbus_TCP_Write_Single(int socket_fd, uint8_t device_id, uint8_t cmd_type, uint16_t start_addr, uint16_t value, uint32_t delay_time)
{
    // 初期化
    u16_conv addr, val;
    addr.D16 = start_addr;
    val.D16 = value;
    unsigned char SendBuffer[16] = {0};

    // 事务元识别符，2byte
    SendBuffer[0] = addr.D8[1];
    SendBuffer[1] = addr.D8[0];
    // 协议标识符，2byte
    SendBuffer[2] = 0;
    SendBuffer[3] = 0;
    // 长度，2byte
    SendBuffer[4] = 0;
    SendBuffer[5] = 0x06;
    // 单元标识符，1byte
    SendBuffer[6] = device_id;
    // 功能码，1byte
    SendBuffer[7] = cmd_type;
    // 寄存器地址，高在前，2byte
    SendBuffer[8] = addr.D8[1];
    SendBuffer[9] = addr.D8[0];
    // 写入的值，高在前，2byte
    SendBuffer[10] = val.D8[1];
    SendBuffer[11] = val.D8[0];

    // 发送
    write(socket_fd, SendBuffer, 12);
    // 在服务器断开链接时，防止程序中断
    signal(SIGPIPE, SIG_IGN);
    // 命令下发后延迟读取
    usleep(delay_time);
}

void Modbus_TCP_Write05_SingleCoil(int socket_fd, uint16_t start_addr, uint16_t value, uint32_t delay_time)
{
    Modbus_TCP_Write_Single(socket_fd, MODBUS_DEFAULT_DEV, MODBUS_WRITE_TYPE_05, start_addr, value, delay_time);
}

void Modbus_TCP_Write06_SingleRegist(int socket_fd, uint16_t start_addr, uint16_t value, uint32_t delay_time)
{
    Modbus_TCP_Write_Single(socket_fd, MODBUS_DEFAULT_DEV, MODBUS_WRITE_TYPE_06, start_addr, value, delay_time);
}

void Modbus_TCP_Write_Multiple(int socket_fd, uint8_t device_id, uint16_t start_addr, uint16_t length, uint16_t *pbuf, uint32_t delay_time)
{
    // 越界检查
    if ((length * 2 + 13) >= 256)
    {
        return;
    }

    // 初期化
    u16_conv addr, len;
    addr.D16 = start_addr;
    len.D16 = length;
    unsigned char SendBuffer[256] = {0};

    // 事务元识别符，2byte
    SendBuffer[0] = addr.D8[1];
    SendBuffer[1] = addr.D8[0];
    // 协议标识符，2byte
    SendBuffer[2] = 0;
    SendBuffer[3] = 0;
    // 长度，2byte
    SendBuffer[4] = 0;
    SendBuffer[5] = (7 + length * 2);
    // 单元标识符，1byte
    SendBuffer[6] = device_id;
    // 功能码，1byte
    SendBuffer[7] = 0x10; // 写多个寄存器
    // 寄存器地址，高在前，2byte
    SendBuffer[8] = addr.D8[1];
    SendBuffer[9] = addr.D8[0];
    // 寄存器数量，高在前，2byte
    SendBuffer[10] = len.D8[1];
    SendBuffer[11] = len.D8[0];
    // 字节长度
    SendBuffer[12] = length * 2;
    // 寄存器值
    int i = 0;
    u16_conv value;
    for (; i < length; i++)
    {
        value.D16 = *(pbuf + i);
        SendBuffer[13 + i * 2] = value.D8[1];
        SendBuffer[14 + i * 2] = value.D8[0];
    }

    // 发送
    write(socket_fd, SendBuffer, (length * 2 + 13));
    // 在服务器断开链接时，防止程序中断
    signal(SIGPIPE, SIG_IGN);
    // 命令下发后延迟读取
    usleep(delay_time);
}

void Modbus_RTU_Read(int socket_fd, uint8_t cmd_type, uint8_t station_no, uint16_t start_addr, uint16_t length, uint32_t delay_time)
{
    // 初期化
    u16_conv addr, len;
    addr.D16 = start_addr;
    len.D16 = length;
    unsigned char SendBuffer[16] = {0};

    // 站号，1byte
    SendBuffer[0] = station_no;
    // 功能码，1byte
    SendBuffer[1] = cmd_type;
    // 寄存器地址，高在前，2byte
    SendBuffer[2] = addr.D8[1];
    SendBuffer[3] = addr.D8[0];
    // 寄存器数量，高在前，2byte
    SendBuffer[4] = len.D8[1];
    SendBuffer[5] = len.D8[0];
    // CRC16，低在前，2byte
    SendBuffer[6] = crc16(SendBuffer, 6) & 0xFF;
    SendBuffer[7] = (crc16(SendBuffer, 6) >> 8) & 0xFF;

    // 发送
    write(socket_fd, SendBuffer, 8);
    // 在服务器断开链接时，防止程序中断
    signal(SIGPIPE, SIG_IGN);
    // 命令下发后延迟读取
    usleep(delay_time);
}

void Modbus_RTU_Read01_SingleCoil(int socket_fd, uint8_t station_no, uint16_t start_addr, uint16_t length, uint32_t delay_time)
{
    Modbus_RTU_Read(socket_fd, MODBUS_READ_TYPE_01, station_no, start_addr, length, delay_time);
}

void Modbus_RTU_Read02_InputDiscrete(int socket_fd, uint8_t station_no, uint16_t start_addr, uint16_t length, uint32_t delay_time)
{
    Modbus_RTU_Read(socket_fd, MODBUS_READ_TYPE_02, station_no, start_addr, length, delay_time);
}

void Modbus_RTU_Read03_HoldRegist(int socket_fd, uint8_t station_no, uint16_t start_addr, uint16_t length, uint32_t delay_time)
{
    Modbus_RTU_Read(socket_fd, MODBUS_READ_TYPE_03, station_no, start_addr, length, delay_time);
}

void Modbus_RTU_Read04_InputRegist(int socket_fd, uint8_t station_no, uint16_t start_addr, uint16_t length, uint32_t delay_time)
{
    Modbus_RTU_Read(socket_fd, MODBUS_READ_TYPE_04, station_no, start_addr, length, delay_time);
}

void Modbus_RTU_Write_Single(int socket_fd, uint8_t cmd_type, uint8_t station_no, uint16_t start_addr, uint16_t value, uint32_t delay_time)
{
    // 初期化
    u16_conv addr, val;
    addr.D16 = start_addr;
    val.D16 = value;
    unsigned char SendBuffer[16] = {0};

    // 站号，1byte
    SendBuffer[0] = station_no;
    // 功能码，1byte
    SendBuffer[1] = cmd_type;
    // 寄存器地址，高在前，2byte
    SendBuffer[2] = addr.D8[1];
    SendBuffer[3] = addr.D8[0];
    // 寄存器值，高在前，2byte
    SendBuffer[4] = val.D8[1];
    SendBuffer[5] = val.D8[0];
    // CRC16，低在前，2byte
    SendBuffer[6] = crc16(SendBuffer, 6) & 0xFF;
    SendBuffer[7] = (crc16(SendBuffer, 6) >> 8) & 0xFF;

    // 发送
    write(socket_fd, SendBuffer, 8);
    // 在服务器断开链接时，防止程序中断
    signal(SIGPIPE, SIG_IGN);
    // 命令下发后延迟读取
    usleep(delay_time);
}

void Modbus_RTU_Write05_SingleCoil(int socket_fd, uint8_t station_no, uint16_t start_addr, uint16_t value, uint32_t delay_time)
{
    Modbus_RTU_Write_Single(socket_fd, MODBUS_WRITE_TYPE_05, station_no, start_addr, value, delay_time);
}

void Modbus_RTU_Write06_SingleRegist(int socket_fd, uint8_t station_no, uint16_t start_addr, uint16_t value, uint32_t delay_time)
{
    Modbus_RTU_Write_Single(socket_fd, MODBUS_WRITE_TYPE_06, station_no, start_addr, value, delay_time);
}

void Modbus_RTU_Write_Multiple(int socket_fd, uint8_t station_no, uint16_t start_addr, uint16_t length, uint16_t *pbuf, uint32_t delay_time)
{
    // 越界检查
    if ((length * 2 + 13) >= 256)
    {
        return;
    }

    // 初期化
    u16_conv addr, len;
    addr.D16 = start_addr;
    len.D16 = length;
    unsigned char SendBuffer[256] = {0};

    // 站号，1byte
    SendBuffer[0] = station_no;
    // 功能码，1byte
    SendBuffer[1] = 0x10; // 写多个寄存器
    // 寄存器地址，高在前，2byte
    SendBuffer[2] = addr.D8[1];
    SendBuffer[3] = addr.D8[0];
    // 寄存器数量，高在前，2byte
    SendBuffer[4] = len.D8[1];
    SendBuffer[5] = len.D8[0];
    // 字节长度
    SendBuffer[6] = length * 2;
    // 寄存器值
    int i = 0;
    u16_conv value;
    for (; i < length; i++)
    {
        value.D16 = *(pbuf + i);
        SendBuffer[7 + i * 2] = value.D8[1];
        SendBuffer[8 + i * 2] = value.D8[0];
    }
    i--;
    // CRC16，低在前，2byte
    SendBuffer[9 + i * 2] = crc16(SendBuffer, (9 + i * 2)) & 0xFF;
    SendBuffer[10 + i * 2] = (crc16(SendBuffer, (9 + i * 2)) >> 8) & 0xFF;

    // 发送
    write(socket_fd, SendBuffer, (i * 2 + 11));
    // 在服务器断开链接时，防止程序中断
    signal(SIGPIPE, SIG_IGN);
    // 命令下发后延迟读取
    usleep(delay_time);
}
