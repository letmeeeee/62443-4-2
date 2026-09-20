/* ------------------------------------------------------------
 * Copyright (C) 2022
 * File Name : ModbusProtocol.h
 * Project : 本地控制器
 * Description : Modbus通信协议
 * File Created : 2022/09/23
 * Author: jinxue.zhao
 * ------------------------------------------------------------
 * Last Modified : 2022/12/05
 * Modified By : jinxue.zhao
 * ------------------------------------------------------------
 * HISTORY : 2022/12/05 添加cpp适配宏，使用系统定义类型
 * ------------------------------------------------------------
 * HISTORY : 2022/11/11 修改函数定义 - 增加设备号，修改宏定义，调整函数声明
 * ------------------------------------------------------------
 * HISTORY : 2022/09/23 新规
 */

#ifndef MODBUS_PROTOCOL_H
#define MODBUS_PROTOCOL_H

/* Make this header file easier to include in C++ code */
#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

/**
 * @brief Modbus的TCP协议，读操作
 * @param[in] socket_fd 文件描述符
 * @param[in] device_id 设备号
 * @param[in] cmd_type 操作类型，例如读线圈，读寄存器
 * @param[in] start_addr 地址
 * @param[in] length 数量
 * @param[in] delay_time 延时时间
 */
void Modbus_TCP_Read(int socket_fd, uint8_t device_id, uint8_t cmd_type, uint16_t start_addr, uint16_t length, uint32_t delay_time);

/**
 * @brief Modbus的TCP协议，读单个线圈
 * @param[in] socket_fd 文件描述符
 * @param[in] start_addr 地址
 * @param[in] length 数量
 * @param[in] delay_time 延时时间
 */
void Modbus_TCP_Read01_SingleCoil(int socket_fd, uint16_t start_addr, uint16_t length, uint32_t delay_time);

/**
 * @brief Modbus的TCP协议，读输入离散量
 * @param[in] socket_fd 文件描述符
 * @param[in] start_addr 地址
 * @param[in] length 数量
 * @param[in] delay_time 延时时间
 */
void Modbus_TCP_Read02_InputDiscrete(int socket_fd, uint16_t start_addr, uint16_t length, uint32_t delay_time);

/**
 * @brief Modbus的TCP协议，读保持寄存器
 * @param[in] socket_fd 文件描述符
 * @param[in] start_addr 地址
 * @param[in] length 数量
 * @param[in] delay_time 延时时间
 */
void Modbus_TCP_Read03_HoldRegist(int socket_fd, uint16_t start_addr, uint16_t length, uint32_t delay_time);

/**
 * @brief Modbus的TCP协议，读输入寄存器
 * @param[in] socket_fd 文件描述符
 * @param[in] start_addr 地址
 * @param[in] length 数量
 * @param[in] delay_time 延时时间
 */
void Modbus_TCP_Read04_InputRegist(int socket_fd, uint16_t start_addr, uint16_t length, uint32_t delay_time);

/**
 * @brief Modbus的TCP协议，写操作
 * @param[in] socket_fd 文件描述符
 * @param[in] device_id 设备号
 * @param[in] cmd_type 操作类型，例如写线圈，写寄存器
 * @param[in] start_addr 地址
 * @param[in] value 写入值
 * @param[in] delay_time 延时时间
 */
void Modbus_TCP_Write_Single(int socket_fd, uint8_t device_id, uint8_t cmd_type, uint16_t start_addr, uint16_t value, uint32_t delay_time);

/**
 * @brief Modbus的TCP协议，写单个线圈
 * @param[in] socket_fd 文件描述符
 * @param[in] start_addr 地址
 * @param[in] value 写入值
 * @param[in] delay_time 延时时间
 */
void Modbus_TCP_Write05_SingleCoil(int socket_fd, uint16_t start_addr, uint16_t value, uint32_t delay_time);

/**
 * @brief Modbus的TCP协议，写单个寄存器
 * @param[in] socket_fd 文件描述符
 * @param[in] start_addr 地址
 * @param[in] value 写入值
 * @param[in] delay_time 延时时间
 */
void Modbus_TCP_Write06_SingleRegist(int socket_fd, uint16_t start_addr, uint16_t value, uint32_t delay_time);

/**
 * @brief Modbus的TCP协议，写多个寄存器
 * @param[in] socket_fd 文件描述符
 * @param[in] device_id 设备号
 * @param[in] start_addr 地址
 * @param[in] length 数量
 * @param[in] pbuf 写入值
 * @param[in] delay_time 延时时间
 */
void Modbus_TCP_Write_Multiple(int socket_fd, uint8_t device_id, uint16_t start_addr, uint16_t length, uint16_t* pbuf, uint32_t delay_time);

/**
 * @brief Modbus的RTU协议，读操作
 * @param[in] socket_fd 文件描述符
 * @param[in] cmd_type 操作类型，例如读线圈，读寄存器
 * @param[in] station_no 设备号
 * @param[in] start_addr 地址
 * @param[in] length 数量
 * @param[in] delay_time 延时时间
 */
void Modbus_RTU_Read(int socket_fd, uint8_t cmd_type, uint8_t station_no, uint16_t start_addr, uint16_t length, uint32_t delay_time);

/**
 * @brief Modbus的RTU协议，读单个线圈
 * @param[in] socket_fd 文件描述符
 * @param[in] station_no 设备号
 * @param[in] start_addr 地址
 * @param[in] length 数量
 * @param[in] delay_time 延时时间
 */
void Modbus_RTU_Read01_SingleCoil(int socket_fd, uint8_t station_no, uint16_t start_addr, uint16_t length, uint32_t delay_time);

/**
 * @brief Modbus的RTU协议，读输入离散量
 * @param[in] socket_fd 文件描述符
 * @param[in] station_no 设备号
 * @param[in] start_addr 地址
 * @param[in] length 数量
 * @param[in] delay_time 延时时间
 */
void Modbus_RTU_Read02_InputDiscrete(int socket_fd, uint8_t station_no, uint16_t start_addr, uint16_t length, uint32_t delay_time);

/**
 * @brief Modbus的RTU协议，读保持寄存器
 * @param[in] socket_fd 文件描述符
 * @param[in] station_no 设备号
 * @param[in] start_addr 地址
 * @param[in] length 数量
 * @param[in] delay_time 延时时间
 */
void Modbus_RTU_Read03_HoldRegist(int socket_fd, uint8_t station_no, uint16_t start_addr, uint16_t length, uint32_t delay_time);

/**
 * @brief Modbus的RTU协议，读输入寄存器
 * @param[in] socket_fd 文件描述符
 * @param[in] station_no 设备号
 * @param[in] start_addr 地址
 * @param[in] length 数量
 * @param[in] delay_time 延时时间
 */
void Modbus_RTU_Read04_InputRegist(int socket_fd, uint8_t station_no, uint16_t start_addr, uint16_t length, uint32_t delay_time);

/**
 * @brief Modbus的RTU协议，写操作
 * @param[in] socket_fd 文件描述符
 * @param[in] cmd_type 操作类型，例如写线圈，写寄存器
 * @param[in] station_no 设备号
 * @param[in] start_addr 地址
 * @param[in] value 写入值
 * @param[in] delay_time 延时时间
 */
void Modbus_RTU_Write_Single(int socket_fd, uint8_t cmd_type, uint8_t station_no, uint16_t start_addr, uint16_t value, uint32_t delay_time);

/**
 * @brief Modbus的RTU协议，写单个线圈
 * @param[in] socket_fd 文件描述符
 * @param[in] station_no 设备号
 * @param[in] start_addr 地址
 * @param[in] value 写入值
 * @param[in] delay_time 延时时间
 */
void Modbus_RTU_Write05_SingleCoil(int socket_fd, uint8_t station_no, uint16_t start_addr, uint16_t value, uint32_t delay_time);

/**
 * @brief Modbus的RTU协议，写单个寄存器
 * @param[in] socket_fd 文件描述符
 * @param[in] station_no 设备号
 * @param[in] start_addr 地址
 * @param[in] value 写入值
 * @param[in] delay_time 延时时间
 */
void Modbus_RTU_Write06_SingleRegist(int socket_fd, uint8_t station_no, uint16_t start_addr, uint16_t value, uint32_t delay_time);

/**
 * @brief Modbus的RTU协议，写多个寄存器
 * @param[in] socket_fd 文件描述符
 * @param[in] station_no 设备号
 * @param[in] start_addr 地址
 * @param[in] length 数量
 * @param[in] pbuf 写入值
 * @param[in] delay_time 延时时间
 */
void Modbus_RTU_Write_Multiple(int socket_fd, uint8_t station_no, uint16_t start_addr, uint16_t length, uint16_t* pbuf, uint32_t delay_time);


/***************************************Modbus通信定义************************************/

//Modbus的读取功能码
#define MODBUS_READ_TYPE_01        (0x01)         //读单个线圈
#define MODBUS_READ_TYPE_02        (0x02)         //读输入离散量
#define MODBUS_READ_TYPE_03        (0x03)         //读保持寄存器
#define MODBUS_READ_TYPE_04        (0x04)         //读输入寄存器
#define MODBUS_DEFAULT_DEV         (0x01)         //ModBus协议中默认设备号

//Modbus的单个写入功能码
#define MODBUS_WRITE_TYPE_05       (0x05)         //写单个线圈
#define MODBUS_WRITE_TYPE_06       (0x06)         //写单个寄存器
#define MODBUS_WRITE_TYPE_10       (0x10)         //写多个寄存器

//命令下发后延迟时间，单位ms
#define CMD_DELAY_0                (0)            //0ms延时
#define CMD_DELAY_200              (200 * 1000)   //200ms延时
#define CMD_DELAY_500              (500 * 1000)   //500ms延时
#define CMD_DELAY_1000             (1000 * 1000)  //1s延时


#ifdef __cplusplus
}
#endif

#endif //MODBUS_PROTOCOL_H
