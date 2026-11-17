#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <unistd.h>
#include <stdint.h>

#include "goose_publisher.h"
#include "linked_list.h"
#include "mms_value.h"
#define _POSIX_C_SOURCE 200809L  
#include <time.h>
/* ========== 运行控制 ========== */
static volatile int g_running = 1;
static void onSig(int sig){ (void)sig; g_running = 0; }

static const char* kIface = "net4";

/* 常用 GOOSE 组播 MAC：01-0C-CD-01-00-01 （必要时可改） */
static const uint8_t kDstMac[6] = {0x01,0x0c,0xcd,0x01,0x00,0x01};

/* ========== 三个固定的 GoCB 配置 ========== */
typedef struct {
    /* 语义字段 */
    const char* goCbRef;     /* 必须与订阅端过滤一致 */
    const char* dataSetRef;  /* 数据集标识（顺序与下面 LinkedList 元素顺序一致） */
    const char* goID;        

    /* 以太层参数 */
    uint16_t appId;          /* 不同通道建议不同 APPID */
    uint16_t vlanId;         /* 0 = 不用 VLAN */
    uint8_t  vlanPrio;       /* 802.1Q PCP（0..7） */
} PubCfg;

static const PubCfg kCfgs[] = {
    { "demoLD/LLN0$GO$gcb1",  "demoLD/LLN0$DataSet$ds1",  "gcb1",  0x1000, 0, 4 },
    { "demoLD/LLN0$GO$gcb2",  "demoLD/LLN0$DataSet$ds2",  "gcb2",  0x1001, 0, 4 },
    { "Feeder1/LLN0$GO$Trip", "Feeder1/LLN0$DataSet$TripDs", "Trip", 0x1002, 0, 4 }
};
#define NUM_PUBS (int)(sizeof(kCfgs)/sizeof(kCfgs[0]))

/* 每个发布器的上下文（1 个元素 BOOL，实际项目可扩展为多元素） */
typedef struct {
    GoosePublisher pub;
    LinkedList     ds;
    MmsValue*      v0;       /* data[0]：BOOL */
    unsigned       tick_ms;  /* 发送节拍 */
    unsigned       next_ms;  /* 下次发送时刻（简单定时） */
} PubCtx;

static unsigned now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return (unsigned)(ts.tv_sec*1000u + ts.tv_nsec/1000000u);
}

int main(void)
{
    signal(SIGINT,  onSig);
    signal(SIGTERM, onSig);

    PubCtx pubs[NUM_PUBS];
    memset(pubs, 0, sizeof(pubs));
/*发布16位数值 */

CommParameters params;
    memset(&params, 0, sizeof(params));
    params.appId        = 0x1000;
    params.vlanPriority = 4;
    params.vlanId       = 0;
    uint8_t dst[6]      = {0x01,0x0c,0xcd,0x01,0x00,0x01};
    memcpy(params.dstAddress, dst, 6);

    GoosePublisher pub = GoosePublisher_create(&params, "net4");
    if (!pub) { perror("GoosePublisher_create"); return -1; }

GoosePublisher_setGoCbRef(pub, "demoLD/LLN0$GO$gcb3");    
GoosePublisher_setDataSetRef(pub, "demoLD/LLN0$DataSet$ds3");

    GoosePublisher_setGoID(pub, "gcb3");
    GoosePublisher_setTimeAllowedToLive(pub, 5000);

 LinkedList ds = LinkedList_create();
    MmsValue* v_bool = MmsValue_newBoolean(0);

 MmsValue* v_u16 = NULL;

 #if 0
    v_u16 = MmsValue_newUnsignedFromUint16(0);
#else
  
    v_u16 = MmsValue_newIntegerFromInt32(0);
#endif
    LinkedList_add(ds, v_u16);
    LinkedList_add(ds, v_bool);
    uint16_t counter = 0;
    int bit = 0;

/*发布u16的数值*/
    for (int i = 0; i < NUM_PUBS; ++i) {
        const PubCfg* c = &kCfgs[i];

        /* 1) 以太层参数都放在 CommParameters 里 */
        CommParameters params;
        memset(&params, 0, sizeof(params));
        params.appId        = c->appId;
        params.vlanId       = c->vlanId;
        params.vlanPriority = c->vlanPrio;
        memcpy(params.dstAddress, kDstMac, 6);

        /* 2) 创建发布器 */
        pubs[i].pub = GoosePublisher_create(&params, kIface);
        if (!pubs[i].pub) {
            fprintf(stderr, "GoosePublisher_create 失败: %s\n", c->goCbRef);
            return 1;
        }

        GoosePublisher_setGoCbRef(pubs[i].pub, c->goCbRef);

        GoosePublisher_setDataSetRef(pubs[i].pub, c->dataSetRef);
        GoosePublisher_setGoID(pubs[i].pub, c->goID);
        GoosePublisher_setTimeAllowedToLive(pubs[i].pub, 5000); /* ms */
   
#ifdef GoosePublisher_setConfRev
        GoosePublisher_setConfRev(pubs[i].pub, 1);
#endif

        pubs[i].ds = LinkedList_create();
        pubs[i].v0 = MmsValue_newBoolean(false);
        LinkedList_add(pubs[i].ds, pubs[i].v0);

      
        pubs[i].tick_ms = (i == 0) ? 500 : (i == 1 ? 1000 : 1500);
        pubs[i].next_ms = now_ms();
        printf("PUB ready: iface=%s  goCbRef=%s  appId=0x%04x  ds=%s\n",
               kIface, c->goCbRef, c->appId, c->dataSetRef);
    }

    printf("\nGOOSE 多发布运行中（Ctrl+C 退出）...\n");

   
    while (g_running) {
        unsigned t = now_ms();
        for (int i = 0; i < NUM_PUBS; ++i) {
            if ((int)(t - pubs[i].next_ms) >= 0) {
                /* 翻转并发送 */
                int b = !MmsValue_getBoolean(pubs[i].v0);
                MmsValue_setBoolean(pubs[i].v0, b);
                GoosePublisher_publish(pubs[i].pub, pubs[i].ds);
                printf("Sent %-24s  data[0]=%s  (appId=0x%04x)\n",
                       kCfgs[i].goCbRef, b ? "true" : "false", kCfgs[i].appId);

                pubs[i].next_ms += pubs[i].tick_ms;
            }
        }

         bit ^= 1;
         MmsValue_setBoolean(v_bool, bit);

        /* 更新16位数值 */
        #if 0
            MmsValue_setUint16(v_u16, counter);z
        #else
            MmsValue_setInt32(v_u16, counter);   
        #endif
            counter = (uint16_t)(counter + 123);  

            /* 发布 */
             GoosePublisher_publish(pub, ds);

        
        usleep(500 * 1000); /* 1ms 轮询 */
    }

    /* 6) 释放 */
    for (int i = 0; i < NUM_PUBS; ++i) {
        if (pubs[i].v0) MmsValue_delete(pubs[i].v0);
        if (pubs[i].ds) LinkedList_destroy(pubs[i].ds);
        if (pubs[i].pub) GoosePublisher_destroy(pubs[i].pub);
    }
    MmsValue_delete(v_bool);
    MmsValue_delete(v_u16);
    LinkedList_destroy(ds);
    GoosePublisher_destroy(pub);


    printf("已退出。\n");
    return 0;
}
