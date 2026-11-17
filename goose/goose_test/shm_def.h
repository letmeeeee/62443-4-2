 #ifndef SHM_DEF_H
 #define SHM_DEF_H

 #define HOLD_SIZE 65535
 #define INPUT_SIZE 65535
 #define ALL_SIZE (INPUT_SIZE + HOLD_SIZE)
/* Shared memory / publisher config */
#define SHM_NAME "/goose_shm"
 // 共享内存文件路径
 #define LOGGER_SHARE_RAM_PATH "/my_shared_memory_logger"
 #define BBMS_SHARE_RAM_PATH "/my_shared_memory_bms"
#define SHM_POLL_MS 200

 // 联合体结构定义寄存器模块
 typedef union RegistersModel {   
     struct {
         unsigned short Input[INPUT_SIZE];
         unsigned short Hold[HOLD_SIZE];
     };
     unsigned short Reg[ALL_SIZE];
     unsigned char ubyte[ALL_SIZE*2];
 } RegistersModel,*pRegistersModel;

#endif /* SHM_DEF_H */
