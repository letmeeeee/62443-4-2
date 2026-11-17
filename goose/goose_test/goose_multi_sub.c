#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <unistd.h>

#include "goose_receiver.h"
#include "goose_subscriber.h"
#include "mms_value.h"

static volatile int g_running = 1;
static void onSig(int sig){ (void)sig; g_running = 0; }

/* === 固定配置：网口 & 要订阅的 GoCB === */
static const char* kIface = "net1";  /* 和发布端一致 */
static const char* kGoCBs[] = {
    "demoLD/LLN0$GO$gcb1",
    "demoLD/LLN0$GO$gcb2",
    "Feeder1/LLN0$GO$Trip",
    "demoLD/LLN0$GO$gcb3"
};
#define NUM_GOCB (int)(sizeof(kGoCBs)/sizeof(kGoCBs[0]))


static void print_dataset_all(const MmsValue* arr)
{
    if (!arr) { printf("  (no dataset)\n"); return; }

    if (MmsValue_getType((MmsValue*)arr) != MMS_ARRAY) {
  
        char buf[128];
        int n = MmsValue_printToBuffer((MmsValue*)arr, buf, sizeof(buf));
        if (n < 0) strcpy(buf, "<print failed>");
        printf("  data = %s (type=%d)\n", buf, (int)MmsValue_getType((MmsValue*)arr));
        return;
    }

    int count = MmsValue_getArraySize((MmsValue*)arr);
    for (int i = 0; i < count; ++i) {
        MmsValue* e = MmsValue_getElement((MmsValue*)arr, i);
        if (!e) { printf("  data[%d]=<null>\n", i); continue; }

switch (MmsValue_getType(e)) {
case MMS_BOOLEAN:
    printf("  data[%d]=%s (BOOL)\n", i, MmsValue_getBoolean(e) ? "true":"false");
    break;

case MMS_INTEGER: {
    int64_t v = MmsValue_toInt32(e);
    printf("  data[%d]=%lld (INTEGER)\n", i, (long long)v);
    break;
}

case MMS_UNSIGNED: {
    uint64_t v = MmsValue_toUint32(e);
    printf("  data[%d]=%llu (UNSIGNED)\n", i, (unsigned long long)v);
    break;
}

case MMS_FLOAT: {
    double f = MmsValue_toDouble(e);
    printf("  data[%d]=%g (FLOAT)\n", i, f);
    break;
}

case MMS_VISIBLE_STRING:
case MMS_OCTET_STRING:
case MMS_BIT_STRING:
default: {

    char buf[256];
    int n = MmsValue_printToBuffer(e, buf, sizeof(buf));
    if (n < 0) strcpy(buf, "<print failed>");
    printf("  data[%d]=%s (type=%d)\n", i, buf, (int)MmsValue_getType(e));
    break;
}
}
    }
}


static void onGoose(GooseSubscriber sub, void* param)
{
    (void)param;

    const char* ref = GooseSubscriber_getGoCbRef(sub);
    uint32_t stNum  = GooseSubscriber_getStNum(sub);
    uint32_t sqNum  = GooseSubscriber_getSqNum(sub);
    uint32_t ttl    = GooseSubscriber_getTimeAllowedToLive(sub);

    printf("\n[GOOSE] ref=%s  stNum=%u  sqNum=%u  ttl=%u\n",
           ref ? ref : "(unknown)", stNum, sqNum, ttl);


    const MmsValue* values = GooseSubscriber_getDataSetValues(sub);
    print_dataset_all(values);
}

int main(void)
{
    signal(SIGINT,  onSig);
    signal(SIGTERM, onSig);

    GooseReceiver receiver = GooseReceiver_create();
    if (!receiver) {
        fprintf(stderr, "GooseReceiver_create 失败\n");
        return 1;
    }


    GooseReceiver_setInterfaceId(receiver, kIface);


    GooseSubscriber subs[NUM_GOCB] = {0};
    int okCount = 0;

    for (int i = 0; i < NUM_GOCB; ++i) {
        const char* ref = kGoCBs[i];

        GooseSubscriber sub = GooseSubscriber_create((char*)ref, NULL);
        if (!sub) {
            fprintf(stderr, "GooseSubscriber_create 失败: %s\n", ref);
            continue;
        }


        GooseSubscriber_setListener(sub, onGoose, NULL);
        GooseReceiver_addSubscriber(receiver, sub);

        subs[okCount++] = sub;
        printf("已固定订阅: iface=%s  goCbRef=%s\n", kIface, ref);
    }

    if (okCount == 0) {
        fprintf(stderr, "无有效订阅，退出\n");
        GooseReceiver_destroy(receiver);
        return 2;
    }

    GooseReceiver_start(receiver);

    printf("\nGOOSE 多订阅运行中 (iface=%s)。Ctrl+C 退出。\n", kIface);
    while (g_running) sleep(1);

    GooseReceiver_stop(receiver);
    for (int i = 0; i < okCount; ++i) {
        if (subs[i]) GooseSubscriber_destroy(subs[i]);
    }
    GooseReceiver_destroy(receiver);
    printf("已退出。\n");
    return 0;
}
