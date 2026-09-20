/* ------------------------------------------------------------
 * Copyright (C) 2022
 * File Name : address_map.h
 * Project :
 * Description : 
 * File Created :
 * Author : wujinjin
 * ------------------------------------------------------------
 * Last Modified :
 * Modified By :
 * ------------------------------------------------------------
 * HISTORY :
 */

#ifndef ADDRESS_MAP_H
#define ADDRESS_MAP_H

#define HOLD_SIZE 65535
#define INPUT_SIZE 65535
#define ALL_SIZE (INPUT_SIZE + HOLD_SIZE)


// 联合体结构定义寄存器模块
typedef union RegistersModel {   
    struct {
        unsigned short Input[INPUT_SIZE];
        unsigned short Hold[HOLD_SIZE];
    };
    unsigned short Reg[ALL_SIZE];
    unsigned char ubyte[ALL_SIZE*2];
} RegistersModel,*pRegistersModel;

extern volatile RegistersModel RegM;

// 宏定义获取映射值
// 正向映射：address → index
#define HOLD_INDEX(address)    (address)


// 反向映射：index → address
#define HOLD_ADDRESS(index) (index)


// 宏定义获取映射值（同时检查有效索引）
#define GET_HOLD(address)    \ 
 ({ \
        RegM.Hold[address]; \
})   

#define SET_HOLD(address, val)  \ 
 ({ \
        RegM.Hold[address]=val; \
})  
    

// 正向映射：address → index
#define INPUT_INDEX(address) (address)
// 反向映射：index → address
#define INPUT_ADDRESS(index)  (index)


// 宏定义获取映射值（同时检查有效索引）
#define GET_INPUT(address) \ 
 ({ \
        RegM.Input[address]; \
}) 

#define SET_INPUT(address, val)  \ 
 ({ \
        RegM.Input[address]=val; \
})  



#define BANK_SIZE 10
#define RACK_SIZE 15
#define R_INPUT_SIZE 1152
#define R_ALL_SIZE (BANK_SIZE*RACK_SIZE*R_INPUT_SIZE)
// 联合体结构定义寄存器模块
typedef union RankModel {   
    struct {
        unsigned short Input[BANK_SIZE][RACK_SIZE*R_INPUT_SIZE];
    };
    unsigned short Reg[R_ALL_SIZE];
    unsigned char ubyte[R_ALL_SIZE*2];
} RankModel,*pRankModel;

extern volatile RankModel RankM;

// 宏定义获取映射索引
#define INPUT_R_INDEX(address) (address)


#define INPUT_R_ADDRESS(index)  (index)


// 宏定义获取映射值（同时检查有效索引）
#define GET_R_INPUT(bank_index, address) \ 
 ({ \
        RankM.Input[bank_index][address]; \
})
#define SET_R_INPUT(bank_index, address, val) \ 
 ({ \
        RankM.Input[bank_index][address]=val; \
})
extern pRegistersModel const pRegM;
extern pRankModel const pRankM;




#endif //ADDRESS_MAP_H
