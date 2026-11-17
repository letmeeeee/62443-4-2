#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>

#include "goose_publisher.h"
#include "mms_value.h"
#include "linked_list.h"

static volatile int running = 1;

static void onSig(int sig)
{
    (void)sig;
    running = 0;
}

#define PCS_MODE_STOP      0
#define PCS_MODE_GRID      1
#define PCS_MODE_ISLAND    2

int main(void)
{
    signal(SIGINT, onSig);

    /* 1. GOOSE底层参数 */
    CommParameters params;
    memset(&params, 0, sizeof(params));

    params.appId        = 0x1000;
    params.vlanPriority = 4;
    params.vlanId       = 0;

    uint8_t dst[6] = {0x01, 0x0c, 0xcd, 0x01, 0x00, 0x01};
    memcpy(params.dstAddress, dst, 6);

    /* 2. 创建发布器 */
    GoosePublisher pub = GoosePublisher_create(&params, "net1");
    if (pub == NULL) {
        fprintf(stderr, "GoosePublisher_create failed\n");
        return -1;
    }

    /* 3. 设置GOOSE标识 */
    GoosePublisher_setGoCbRef(pub, "EMSLD0/LLN0$GO$gcbPCSCtrl");
    GoosePublisher_setDataSetRef(pub, "EMSLD0/LLN0$DataSet$dsPCSCtrl");
    GoosePublisher_setGoID(pub, "gcbPCSCtrl");
    GoosePublisher_setTimeAllowedToLive(pub, 5000);

    /* 4. 创建数据集 */
    LinkedList ds = LinkedList_create();
    if (ds == NULL) {
        fprintf(stderr, "LinkedList_create failed\n");
        GoosePublisher_destroy(pub);
        return -1;
    }

    /* 顺序必须和SCL的DataSet一致 */
    MmsValue* startCmd = MmsValue_newBoolean(false);               /* index 0 */
    MmsValue* stopCmd  = MmsValue_newBoolean(false);               /* index 1 */
    MmsValue* modeCmd  = MmsValue_newIntegerFromInt32(PCS_MODE_GRID); /* index 2 */
    MmsValue* pset     = MmsValue_newIntegerFromInt32(500);        /* index 3 */
    MmsValue* qset     = MmsValue_newIntegerFromInt32(0);          /* index 4 */

    LinkedList_add(ds, startCmd);
    LinkedList_add(ds, stopCmd);
    LinkedList_add(ds, modeCmd);
    LinkedList_add(ds, pset);
    LinkedList_add(ds, qset);

    printf("EMS GOOSE publisher started on net1\n");
    printf("goCbRef   : EMSLD0/LLN0$GO$gcbPCSCtrl\n");
    printf("dataSetRef: EMSLD0/LLN0$DataSet$dsPCSCtrl\n");
    printf("Press Ctrl+C to stop.\n");

    int tick = 0;

    while (running) {
        tick++;

        /* 演示逻辑：
         * 前5秒发启动
         * 后5秒发停机
         * P/Q周期变化
         */
        bool start = false;
        bool stop  = false;
        int32_t mode = PCS_MODE_GRID;
        int32_t p = 500;
        int32_t q = 0;

        if ((tick / 10) % 2 == 0) {
            start = true;
            stop  = false;
            mode  = PCS_MODE_GRID;
            p     = 500;
            q     = 100;
        }
        else {
            start = false;
            stop  = true;
            mode  = PCS_MODE_STOP;
            p     = 0;
            q     = 0;
        }

        MmsValue_setBoolean(startCmd, start);
        MmsValue_setBoolean(stopCmd, stop);
        MmsValue_setInt32(modeCmd, mode);
        MmsValue_setInt32(pset, p);
        MmsValue_setInt32(qset, q);

        GoosePublisher_publish(pub, ds);

        printf("[PUB] Start=%d Stop=%d Mode=%d Pset=%d Qset=%d\n",
               start ? 1 : 0,
               stop ? 1 : 0,
               (int)mode,
               (int)p,
               (int)q);

        usleep(500 * 1000);
    }

    MmsValue_delete(startCmd);
    MmsValue_delete(stopCmd);
    MmsValue_delete(modeCmd);
    MmsValue_delete(pset);
    MmsValue_delete(qset);
    LinkedList_destroy(ds);
    GoosePublisher_destroy(pub);

    return 0;
}