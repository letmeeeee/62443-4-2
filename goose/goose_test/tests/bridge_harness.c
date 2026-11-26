/* Test-only: execute the real bridge callback, queue and Modbus encoder.
 * No sockets are opened. Only the final send/recv system calls are replaced. */
#include <sys/socket.h>
#include <string.h>
#include <stdint.h>

static unsigned write_count;
static uint8_t writes[128][64];
static size_t write_sizes[128];
static ssize_t harness_send(int fd, const void *data, size_t size, int flags)
{
    (void)fd; (void)flags;
    if (write_count >= 128 || size > sizeof(writes[0])) return -1;
    memcpy(writes[write_count],data,size);
    write_sizes[write_count++]=size;
    return (ssize_t)size;
}
static ssize_t harness_recv(int fd, void *data, size_t size, int flags)
{
    (void)fd; (void)flags;
    if (!write_count || size < 12) return -1;
    memcpy(data,writes[write_count-1],12);
    ((uint8_t *)data)[4]=0;
    ((uint8_t *)data)[5]=6;
    return 12;
}

#define send harness_send
#define recv harness_recv
#define main unused_bridge_main
#include "../middle.c"
#undef main
#undef recv
#undef send
#define EXPORT __attribute__((visibility("default")))

EXPORT int bridge_init(void)
{
    memset(&g_up,0,sizeof(g_up));
    g_q_head=g_q_tail=g_q_count=0;
    write_count=0;
    running=1;
    g_modbus_sock=123; /* virtual fd used only by harness_send/recv */
    initial_modbus_addr_list();
    uint8_t dst[6]={1,12,205,1,0,0};
    g_up.receiver=GooseReceiver_create();
    g_up.subscriber=GooseSubscriber_create(SUbSCRIBER1_goCbRef,NULL);
    if (!g_up.receiver || !g_up.subscriber) return -1;
    GooseSubscriber_setDstMac(g_up.subscriber,dst);
    GooseSubscriber_setAppId(g_up.subscriber,SUbSCRIBER1_APPID);
    GooseSubscriber_setListener(g_up.subscriber,onUpperGooseReceived,NULL);
    GooseReceiver_addSubscriber(g_up.receiver,g_up.subscriber);
    return 0;
}

EXPORT int bridge_feed(GooseSecurity *security, const uint8_t *frame, size_t size)
{
    uint8_t plain[GSEC_MAX_FRAME];
    int first=0;
    int length=gsec_open_frame(security,frame,size,plain,&first);
    if (length > 0) {
        if (first && resetUpstreamSession()!=0) return -1;
        GooseReceiver_handleMessage(g_up.receiver,plain,length);
    }
    return length;
}

EXPORT int bridge_drain(void)
{
    while (g_q_count) {
        QueueEntry entry;
        if (queue_pop(&entry) || modbus_write_registers(entry.addr,entry.values,entry.count)) return -1;
    }
    return (int)write_count;
}
EXPORT int bridge_write_byte(unsigned index, unsigned offset)
{
    if (index >= write_count || offset >= write_sizes[index]) return -1;
    return writes[index][offset];
}
EXPORT void bridge_close(void)
{
    if (g_up.receiver) GooseReceiver_destroy(g_up.receiver);
    memset(&g_up,0,sizeof(g_up));
    g_modbus_sock=-1;
}
