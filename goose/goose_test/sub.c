#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>

#include "goose_receiver.h"
#include "goose_subscriber.h"
#include "mms_value.h"

static volatile int running = 1;

static void onSig(int sig)
{
    (void)sig;
    running = 0;
}

#define PCS_MODE_STOP      0
#define PCS_MODE_GRID      1
#define PCS_MODE_ISLAND    2

typedef struct
{
    bool    startCmd;
    bool    stopCmd;
    int32_t modeCmd;
    int32_t pset;
    int32_t qset;
} PCS_GooseCtrl_t;

static PCS_GooseCtrl_t g_pcsCtrl = {0};

static const char* modeToStr(int32_t mode)
{
    switch (mode) {
        case PCS_MODE_STOP:   return "STOP";
        case PCS_MODE_GRID:   return "GRID";
        case PCS_MODE_ISLAND: return "ISLAND";
        default:              return "UNKNOWN";
    }
}

/* 模拟PCS控制执行 */
static void PCS_executeControl(const PCS_GooseCtrl_t* ctrl)
{
    printf("[PCS] EXECUTE => Start=%d Stop=%d Mode=%s Pset=%d Qset=%d\n",
           ctrl->startCmd ? 1 : 0,
           ctrl->stopCmd ? 1 : 0,
           modeToStr(ctrl->modeCmd),
           (int)ctrl->pset,
           (int)ctrl->qset);

    if (ctrl->stopCmd) {
        printf("[PCS] Action : STOP PCS\n");
        return;
    }

    if (ctrl->startCmd) {
        printf("[PCS] Action : START PCS\n");
    }

    printf("[PCS] Action : Set Mode=%s\n", modeToStr(ctrl->modeCmd));
    printf("[PCS] Action : Set P=%d, Q=%d\n", (int)ctrl->pset, (int)ctrl->qset);
}

/* GOOSE接收回调 */
static void onGooseReceived(GooseSubscriber subscriber, void* parameter)
{
    (void)parameter;

    const char* goCbRef = GooseSubscriber_getGoCbRef(subscriber);
    uint32_t stNum      = GooseSubscriber_getStNum(subscriber);
    uint32_t sqNum      = GooseSubscriber_getSqNum(subscriber);
    uint32_t confRev    = GooseSubscriber_getConfRev(subscriber);
    bool needsComm      = GooseSubscriber_needsCommission(subscriber);
    bool testFlag       = GooseSubscriber_isTest(subscriber);

    printf("\n================ GOOSE RECEIVED ================\n");
    printf("goCbRef   : %s\n", goCbRef ? goCbRef : "NULL");
    printf("stNum     : %u\n", stNum);
    printf("sqNum     : %u\n", sqNum);
    printf("confRev   : %u\n", confRev);
    printf("ndsCom    : %d\n", needsComm ? 1 : 0);
    printf("test      : %d\n", testFlag ? 1 : 0);

    MmsValue* dataSetValues = GooseSubscriber_getDataSetValues(subscriber);
    if (dataSetValues == NULL) {
        printf("dataset   : NULL\n");
        printf("================================================\n");
        return;
    }

    int count = MmsValue_getArraySize(dataSetValues);
    printf("data count: %d\n", count);

    if (count < 5) {
        printf("dataset size error, need 5 elements\n");
        printf("================================================\n");
        return;
    }

    MmsValue* e0 = MmsValue_getElement(dataSetValues, 0); /* StartCmd */
    MmsValue* e1 = MmsValue_getElement(dataSetValues, 1); /* StopCmd */
    MmsValue* e2 = MmsValue_getElement(dataSetValues, 2); /* ModeCmd */
    MmsValue* e3 = MmsValue_getElement(dataSetValues, 3); /* Pset */
    MmsValue* e4 = MmsValue_getElement(dataSetValues, 4); /* Qset */

    if (!e0 || !e1 || !e2 || !e3 || !e4) {
        printf("dataset element NULL\n");
        printf("================================================\n");
        return;
    }

    g_pcsCtrl.startCmd = MmsValue_getBoolean(e0);
    g_pcsCtrl.stopCmd  = MmsValue_getBoolean(e1);
    g_pcsCtrl.modeCmd  = MmsValue_toInt32(e2);
    g_pcsCtrl.pset     = MmsValue_toInt32(e3);
    g_pcsCtrl.qset     = MmsValue_toInt32(e4);

    printf("StartCmd  : %d\n", g_pcsCtrl.startCmd ? 1 : 0);
    printf("StopCmd   : %d\n", g_pcsCtrl.stopCmd ? 1 : 0);
    printf("ModeCmd   : %d (%s)\n", (int)g_pcsCtrl.modeCmd, modeToStr(g_pcsCtrl.modeCmd));
    printf("Pset      : %d\n", (int)g_pcsCtrl.pset);
    printf("Qset      : %d\n", (int)g_pcsCtrl.qset);

    PCS_executeControl(&g_pcsCtrl);

    printf("================================================\n");
}

int main(void)
{
    signal(SIGINT, onSig);

    GooseReceiver receiver = GooseReceiver_create();
    if (receiver == NULL) {
        fprintf(stderr, "GooseReceiver_create failed!\n");
        return -1;
    }

    /* 接收网口要和发布链路一致 */
    GooseReceiver_setInterfaceId(receiver, "net1");

    GooseSubscriber subscriber =
        GooseSubscriber_create("EMSLD0/LLN0$GO$gcbPCSCtrl", NULL);

    if (subscriber == NULL) {
        fprintf(stderr, "GooseSubscriber_create failed!\n");
        GooseReceiver_destroy(receiver);
        return -1;
    }

    GooseSubscriber_setAppId(subscriber, 0x1000);
    GooseSubscriber_setListener(subscriber, onGooseReceived, NULL);
    GooseReceiver_addSubscriber(receiver, subscriber);
    GooseReceiver_start(receiver);

    printf("PCS GOOSE subscriber started on net1\n");
    printf("Subscribe goCbRef : EMSLD0/LLN0$GO$gcbPCSCtrl\n");
    printf("Waiting for GOOSE messages... Press Ctrl+C to exit.\n");

    while (running) {
        sleep(1);
    }

    GooseReceiver_stop(receiver);
    GooseSubscriber_destroy(subscriber);
    GooseReceiver_destroy(receiver);

    return 0;
}