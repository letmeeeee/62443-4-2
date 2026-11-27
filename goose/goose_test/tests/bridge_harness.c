/* Test-only: execute the real bridge callback, queue and Modbus encoder.
 * No sockets are opened. Only the final send/recv system calls are replaced. */
#include <sys/socket.h>
#include <string.h>
#include <stdint.h>

static unsigned write_count;
static uint8_t writes[128][64];
static size_t write_sizes[128];
static size_t response_offset;
static int response_fault;
static ssize_t harness_send(int fd, const void *data, size_t size, int flags)
{
    (void)fd; (void)flags;
    if (write_count >= 128 || size > sizeof(writes[0])) return -1;
    memcpy(writes[write_count],data,size);
    write_sizes[write_count++]=size;
    response_offset=0;
    return (ssize_t)size;
}
static ssize_t harness_recv(int fd, void *data, size_t size, int flags)
{
    (void)fd; (void)flags;
    if (!write_count || response_fault == 1) return -1;
    uint8_t response[12];
    memcpy(response,writes[write_count-1],12);
    response[4]=0; response[5]=6;
    if (response_fault == 2) response[1] ^= 1;
    if (response_fault == 3) response[9] ^= 1;
    if (response_fault == 4) { response[5]=3; response[7]=0x90; response[8]=2; }
    size_t length=response_fault == 4 ? 9 : 12;
    if (response_offset >= length) return 0;
    size_t available=length-response_offset;
    if (size > available) size=available;
    if (size > 3) size=3; /* exercise fragmented TCP response */
    memcpy(data,response+response_offset,size);
    response_offset+=size;
    return (ssize_t)size;
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
    response_fault=0;
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
EXPORT int bridge_modbus_response_fault(int fault)
{
    response_fault=fault;
    return 0;
}
EXPORT int bridge_modbus_probe(void)
{
    uint16_t value=1;
    return modbus_write_registers(27204,&value,1);
}
EXPORT void bridge_close(void)
{
    if (g_up.receiver) GooseReceiver_destroy(g_up.receiver);
    memset(&g_up,0,sizeof(g_up));
    g_modbus_sock=-1;
}
