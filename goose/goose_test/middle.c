#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>

#include "goose_receiver.h"
#include "goose_subscriber.h"
#include "goose_publisher.h"
#include "mms_value.h"
#include "linked_list.h"
#include <fcntl.h>
#include <stdlib.h>
#include "rpch_common.h"
#include <arpa/inet.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <errno.h>
#include <time.h>
#include <pthread.h>
#include <fcntl.h>
#include <sys/select.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include "shm_def.h"
#include "security/goose_transport.h"
#include "security/goose_log.h"

/* Keep bridge diagnostics in the independent GOOSE daily log, like DPrint. */
#define printf(...) GLOG("INFO", __VA_ARGS__)
#define fprintf(stream, ...) GLOG("ERROR", __VA_ARGS__)
#define perror(message) GLOG("ERROR", "%s: %s", message, strerror(errno))

static GooseTransport *g_secure_transport;
static volatile int running = 1;

static void onSig(int sig)
{
    (void)sig;
    running = 0;
}

/* =========================
 * Modbus TCP client (simple)
 * ========================= */
#define MODBUS_SERVER_IP   "127.0.0.1"
#define MODBUS_SERVER_PORT 1502
#define MODBUS_UNIT_ID     1
/* starting register address */
#define MODBUS_ACTIVE_REG_ADDR1    27204
#define MODBUS_ACTIVE_REG_ADDR2    27205
#define MODBUS_ACTIVE_REG_ADDR3    27206
#define MODBUS_ACTIVE_REG_ADDR4    27207

#define MODBUS_REACTIVE_REG_ADDR1    27208
#define MODBUS_REACTIVE_REG_ADDR2    27209
#define MODBUS_REACTIVE_REG_ADDR3    27210
#define MODBUS_REACTIVE_REG_ADDR4    27211


#define SUbSCRIBER1_NET "net2"
#define SUbSCRIBER1_APPID 0x1000
// #define SUbSCRIBER1_goCbRef "China_PCSPIGO/LLN0$GO$gocb1"
#define SUbSCRIBER1_goCbRef "TEMPLATEPIGO/LLN0$GO$gocb1"
#define MAX_SUB_NUM 8
#define MAX_PCS_NUM 4
#define S_BUS 0
#define D_BUS 1

#define LC_MAX_NUM 1
#define LC_ID 1
#define PCSGROUP_OFFSET 300

static int g_modbus_sock = -1;
static uint16_t BUS_MODE = -1;  /*0: S_BUS, 1: D_BUS*/
static uint16_t g_modbus_tid = 0;
static uint16_t modbus_addr_list_actice[MAX_SUB_NUM / 2];
static uint16_t modbus_addr_list_reactice[MAX_SUB_NUM / 2];

void initial_modbus_addr_list(void)
{
    uint16_t sys_per_num = MAX_SUB_NUM / MAX_PCS_NUM;
    if (sys_per_num == 2)
    {
        BUS_MODE = D_BUS;
        printf("双BUS模式启动\n");
    }
    else if (sys_per_num == 1)
    {
        BUS_MODE = S_BUS;
        printf("单BUS模式启动\n");
    }
    else
    {
        printf("BUS模式异常: %d,请检查系统参数配置\n", sys_per_num);
        return;
    }

    modbus_addr_list_actice[0] = MODBUS_ACTIVE_REG_ADDR1;
    modbus_addr_list_actice[1] = MODBUS_ACTIVE_REG_ADDR2;
    modbus_addr_list_actice[2] = MODBUS_ACTIVE_REG_ADDR3;
    modbus_addr_list_actice[3] = MODBUS_ACTIVE_REG_ADDR4;

    modbus_addr_list_reactice[0] = MODBUS_REACTIVE_REG_ADDR1;
    modbus_addr_list_reactice[1] = MODBUS_REACTIVE_REG_ADDR2;
    modbus_addr_list_reactice[2] = MODBUS_REACTIVE_REG_ADDR3;
    modbus_addr_list_reactice[3] = MODBUS_REACTIVE_REG_ADDR4;
}

/* Try a non-blocking connect with timeout (ms). On success sets g_modbus_sock and returns 0. */
static int modbus_try_connect(int timeout_ms)
{
    struct sockaddr_in addr;
    int s = socket(AF_INET, SOCK_STREAM, 0);
    if (s < 0) {
        perror("socket");
        return -1;
    }

    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(MODBUS_SERVER_PORT);
    if (inet_pton(AF_INET, MODBUS_SERVER_IP, &addr.sin_addr) <= 0) {
        fprintf(stderr, "inet_pton failed for %s\n", MODBUS_SERVER_IP);
        close(s);
        return -1;
    }

    int flags = fcntl(s, F_GETFL, 0);
    if (flags < 0) flags = 0;
    fcntl(s, F_SETFL, flags | O_NONBLOCK);

    int rc = connect(s, (struct sockaddr*)&addr, sizeof(addr));
    if (rc == 0) {
        /* connected immediately */
        fcntl(s, F_SETFL, flags); /* restore blocking */
        g_modbus_sock = s;
        g_modbus_tid = 0;
        return 0;
    }
    if (errno != EINPROGRESS) {
        close(s);
        return -1;
    }

    /* wait for writability */
    fd_set wfds;
    FD_ZERO(&wfds);
    FD_SET(s, &wfds);
    struct timeval tv;
    tv.tv_sec = timeout_ms / 1000;
    tv.tv_usec = (timeout_ms % 1000) * 1000;

    rc = select(s + 1, NULL, &wfds, NULL, &tv);
    if (rc <= 0) {
        /* timeout or error */
        close(s);
        return -1;
    }

    /* check socket error */
    int so_err = 0;
    socklen_t len = sizeof(so_err);
    if (getsockopt(s, SOL_SOCKET, SO_ERROR, &so_err, &len) < 0) {
        close(s);
        return -1;
    }
    if (so_err != 0) {
        close(s);
        return -1;
    }

    /* success */
    fcntl(s, F_SETFL, flags); /* restore blocking */
    g_modbus_sock = s;
    g_modbus_tid = 0;
    return 0;
}

/* Ensure there is a connected modbus socket; retry with exponential backoff until running is false. */
static int ensure_modbus_connected(void)
{
    if (g_modbus_sock >= 0)
        return 0;

    int backoff_ms = 500;
    const int max_backoff = 16000;
    while (running) {
        if (modbus_try_connect(2000) == 0) {
            printf("Modbus TCP connected to %s:%d\n", MODBUS_SERVER_IP, MODBUS_SERVER_PORT);
            return 0;
        }
        fprintf(stderr, "modbus: connect failed, retrying in %d ms\n", backoff_ms);
        int slept = 0;
        while (slept < backoff_ms && running) {
            int step = (backoff_ms - slept) > 200 ? 200 : (backoff_ms - slept);
            usleep(step * 1000);
            slept += step;
        }
        backoff_ms *= 2;
        if (backoff_ms > max_backoff) backoff_ms = max_backoff;
    }
    return -1;
}

static int initModbusClient(void)
{
    /* Try an initial quick connect (non-fatal). The sender thread will perform retries if needed. */
    if (modbus_try_connect(2000) == 0) {
        printf("Modbus TCP connected to %s:%d\n", MODBUS_SERVER_IP, MODBUS_SERVER_PORT);
        return 0;
    }
    fprintf(stderr, "modbus: initial connect failed, will retry in sender thread\n");
    g_modbus_sock = -1;
    return 0;
}

static void deinitModbusClient(void)
{
    if (g_modbus_sock >= 0) {
        close(g_modbus_sock);
        g_modbus_sock = -1;
    }
}

/* Write consecutive 16-bit registers using Modbus function 0x10. */
#define MODBUS_MAX_WRITE_REGS 123
static int modbus_write_registers(uint16_t addr, const uint16_t* values, uint16_t count)
{
    if (g_modbus_sock < 0 || values == NULL || count == 0 ||
        count > MODBUS_MAX_WRITE_REGS)
        return -1;

    uint8_t buf[7 + 6 + MODBUS_MAX_WRITE_REGS * 2];
    uint16_t tid = ++g_modbus_tid;
    uint16_t pid = 0;
    uint16_t length = (uint16_t)(7 + count * 2);
    uint8_t unit = MODBUS_UNIT_ID;

    /* MBAP header */
    buf[0] = (tid >> 8) & 0xff;
    buf[1] = tid & 0xff;
    buf[2] = (pid >> 8) & 0xff;
    buf[3] = pid & 0xff;
    buf[4] = (length >> 8) & 0xff;
    buf[5] = length & 0xff;
    buf[6] = unit;

    /* PDU: Write Multiple Registers (0x10). */
    buf[7] = 0x10;
    buf[8] = (addr >> 8) & 0xff;
    buf[9] = addr & 0xff;
    buf[10] = (count >> 8) & 0xff;
    buf[11] = count & 0xff;
    buf[12] = (uint8_t)(count * 2);
    for (uint16_t i = 0; i < count; ++i) {
        buf[13 + i * 2] = (values[i] >> 8) & 0xff;
        buf[14 + i * 2] = values[i] & 0xff;
    }

    ssize_t to_send = 13 + count * 2;
    ssize_t n = send(g_modbus_sock, buf, to_send, 0);
    if (n != to_send) {
        perror("modbus send");
        return -1;
    }

    /* Response: MBAP(7) + function(1) + addr(2) + quantity(2) = 12 bytes. */
    uint8_t resp[64];
    ssize_t r = recv(g_modbus_sock, resp, sizeof(resp), 0);
    if (r < 0) {
        perror("modbus recv");
        return -1;
    }
    if (r < 12) {
        fprintf(stderr, "modbus: short response (%zd)\n", r);
        return -1;
    }

    uint16_t resp_tid = (resp[0] << 8) | resp[1];
    if (resp_tid != tid) {
        fprintf(stderr, "modbus: tid mismatch %u!=%u\n", resp_tid, tid);
    }

    uint8_t func = resp[7];
    if (func == (0x10 | 0x80)) {
        fprintf(stderr, "modbus: exception code %u\n", resp[8]);
        return -1;
    }
    if (func != 0x10) {
        fprintf(stderr, "modbus: unexpected function %02x\n", func);
        return -1;
    }

    return 0;
}

/* =========================
 * Queue and Modbus sender thread
 * ========================= */
typedef struct
{
    bool    startCmd;
    bool    stopCmd;
    int32_t modeCmd;
    int32_t pset;
    int32_t qset;
} GooseCtrl_t;

typedef struct
{
    int32_t powerset[MAX_SUB_NUM];
} GoosePower_t;

typedef struct
{
    GoosePublisher pub;
    LinkedList ds;
    MmsValue* values[128];
    size_t value_count;
} DownstreamPublisher_t;

static DownstreamPublisher_t g_down = {0};

#define QUEUE_SIZE 256
typedef struct {
    uint16_t addr;
    uint16_t count;
    uint16_t values[MODBUS_MAX_WRITE_REGS];
    uint32_t stNum; /* optional for logging */
} QueueEntry;

static QueueEntry g_queue[QUEUE_SIZE];
static int g_q_head = 0;
static int g_q_tail = 0;
static int g_q_count = 0;
static pthread_mutex_t g_q_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t  g_q_cond  = PTHREAD_COND_INITIALIZER;
static pthread_t g_modbus_thread;
static int g_modbus_thread_started = 0;
static pthread_t g_goose_pub_thread;
static int g_goose_pub_thread_started = 0;


typedef struct {
    size_t register_address;
    enum {
        GOOSE_VALUE_BOOL,
        GOOSE_VALUE_FLOAT32,
        GOOSE_VALUE_INT32
    } type;
} ShmGooseMapping;

/* Order must match the complete DataSet defined in SCD/CID. */
static const ShmGooseMapping shm_goose_mappings[] = {
    { 0, GOOSE_VALUE_BOOL }, { 1, GOOSE_VALUE_BOOL },
    { 2, GOOSE_VALUE_BOOL }, { 3, GOOSE_VALUE_BOOL },
    { 4, GOOSE_VALUE_FLOAT32 }, { 6, GOOSE_VALUE_INT32 },
    { 7, GOOSE_VALUE_FLOAT32 }, { 9, GOOSE_VALUE_INT32 },
    { 10, GOOSE_VALUE_FLOAT32 }, { 12, GOOSE_VALUE_INT32 },
    { 13, GOOSE_VALUE_FLOAT32 }, { 15, GOOSE_VALUE_INT32 },
    { 16, GOOSE_VALUE_FLOAT32 }, { 18, GOOSE_VALUE_INT32 },
    { 19, GOOSE_VALUE_FLOAT32 }, { 21, GOOSE_VALUE_INT32 },
    { 22, GOOSE_VALUE_FLOAT32 }, { 24, GOOSE_VALUE_INT32 },
    { 25, GOOSE_VALUE_FLOAT32 }, { 27, GOOSE_VALUE_INT32 },
    { 28, GOOSE_VALUE_FLOAT32 }, { 30, GOOSE_VALUE_INT32 },
    { 31, GOOSE_VALUE_FLOAT32 }, { 33, GOOSE_VALUE_INT32 },
    { 34, GOOSE_VALUE_FLOAT32 }, { 36, GOOSE_VALUE_INT32 },
    { 37, GOOSE_VALUE_FLOAT32 }, { 39, GOOSE_VALUE_INT32 },
    { 40, GOOSE_VALUE_FLOAT32 }, { 42, GOOSE_VALUE_INT32 },
    { 43, GOOSE_VALUE_FLOAT32 }, { 45, GOOSE_VALUE_INT32 },
    { 46, GOOSE_VALUE_FLOAT32 }, { 48, GOOSE_VALUE_INT32 },
    { 49, GOOSE_VALUE_FLOAT32 }, { 51, GOOSE_VALUE_INT32 },
    { 52, GOOSE_VALUE_FLOAT32 }, { 54, GOOSE_VALUE_INT32 },
    { 55, GOOSE_VALUE_FLOAT32 }, { 57, GOOSE_VALUE_INT32 },
    { 58, GOOSE_VALUE_FLOAT32 }, { 60, GOOSE_VALUE_INT32 },
    { 61, GOOSE_VALUE_FLOAT32 }, { 63, GOOSE_VALUE_INT32 },
    { 64, GOOSE_VALUE_FLOAT32 }, { 66, GOOSE_VALUE_INT32 },
    { 67, GOOSE_VALUE_FLOAT32 }, { 69, GOOSE_VALUE_INT32 },
    { 70, GOOSE_VALUE_FLOAT32 }, { 72, GOOSE_VALUE_INT32 },
    { 73, GOOSE_VALUE_BOOL }, { 74, GOOSE_VALUE_BOOL },
    { 75, GOOSE_VALUE_BOOL }, { 76, GOOSE_VALUE_BOOL },
    { 77, GOOSE_VALUE_BOOL }, { 78, GOOSE_VALUE_BOOL },
    { 79, GOOSE_VALUE_BOOL }, { 80, GOOSE_VALUE_BOOL },
    { 81, GOOSE_VALUE_BOOL }, { 82, GOOSE_VALUE_BOOL },
    { 83, GOOSE_VALUE_BOOL }, { 84, GOOSE_VALUE_BOOL },
    { 85, GOOSE_VALUE_BOOL }, { 86, GOOSE_VALUE_BOOL },
    { 87, GOOSE_VALUE_BOOL }, { 88, GOOSE_VALUE_BOOL }
};
static const size_t shm_goose_mapping_count = sizeof(shm_goose_mappings) /
                                              sizeof(shm_goose_mappings[0]);
static volatile RegistersModel* g_registers = NULL;

static uint32_t read_register_u32(size_t address)
{
    uint32_t high = g_registers->Reg[address];
    uint32_t low = g_registers->Reg[address + 1];
    return (high << 16) | low;
}

static void update_goose_value(MmsValue* value, const ShmGooseMapping* mapping)
{
    size_t address = mapping->register_address;
    if (mapping->type == GOOSE_VALUE_FLOAT32) {
        uint32_t raw = read_register_u32(address);
        float number;
        memcpy(&number, &raw, sizeof(number));
        MmsValue_setFloat(value, number);
    }
    else if (mapping->type == GOOSE_VALUE_BOOL) {
        MmsValue_setBoolean(value, g_registers->Reg[address] != 0);
    }
    else {
        MmsValue_setInt32(value, (int32_t)g_registers->Reg[address]);
    }
}

static int map_registers_shm(const char* name)
{
    int fd = shm_open(name, O_RDWR | O_CREAT, 0660);
    if (fd < 0) return -1;

    struct stat st;
    if (fstat(fd, &st) != 0) {
        close(fd);
        return -1;
    }

    if ((size_t)st.st_size < sizeof(RegistersModel) &&
        ftruncate(fd, sizeof(RegistersModel)) != 0) {
        close(fd);
        return -1;
    }

    void* map = mmap(NULL, sizeof(RegistersModel), PROT_READ, MAP_SHARED, fd, 0);
    close(fd);
    if (map == MAP_FAILED) return -1;

    g_registers = (volatile RegistersModel*)map;
    return 0;
}

static void unmap_registers_shm(void)
{
    if (g_registers != NULL) {
        munmap((void*)g_registers, sizeof(RegistersModel));
        g_registers = NULL;
    }
}

static void* goose_publisher_thread(void* arg)
{
    (void)arg;

    while (running) {
        if (g_registers == NULL) {
            if (map_registers_shm(LOGGER_SHARE_RAM_PATH) != 0) {
                fprintf(stderr, "goose_publisher: failed to map %s, retrying...\n", LOGGER_SHARE_RAM_PATH);
                usleep(500 * 1000);
                continue;
            }
            printf("goose_publisher: mapped %s size=%zu\n",
                   LOGGER_SHARE_RAM_PATH, sizeof(RegistersModel));
        }

        for (size_t i = 0; i < shm_goose_mapping_count; ++i) {
            size_t address = shm_goose_mappings[i].register_address;
            size_t register_count = (shm_goose_mappings[i].type == GOOSE_VALUE_FLOAT32) ? 2 : 1;
            if (address + register_count <= ALL_SIZE) {
                update_goose_value(g_down.values[i], &shm_goose_mappings[i]);
            }
        }

        GoosePublisher_publish(g_down.pub, g_down.ds);

        usleep(SHM_POLL_MS * 1000);
    }

    unmap_registers_shm();
    return NULL;
}

static void queue_push(uint16_t addr, const uint16_t* values, uint16_t count, uint32_t stNum)
{
    if (values == NULL || count == 0 || count > MODBUS_MAX_WRITE_REGS)
        return;

    pthread_mutex_lock(&g_q_mutex);
    if (g_q_count == QUEUE_SIZE) {
        /* drop oldest to make room */
        g_q_head = (g_q_head + 1) % QUEUE_SIZE;
        g_q_count--;
    }
    g_queue[g_q_tail].addr = addr;
    g_queue[g_q_tail].count = count;
    memcpy(g_queue[g_q_tail].values, values, count * sizeof(values[0]));
    g_queue[g_q_tail].stNum = stNum;
    g_q_tail = (g_q_tail + 1) % QUEUE_SIZE;
    g_q_count++;
    pthread_cond_signal(&g_q_cond);
    pthread_mutex_unlock(&g_q_mutex);
}

static int queue_pop(QueueEntry* out)
{
    pthread_mutex_lock(&g_q_mutex);
    while (g_q_count == 0 && running) {
        pthread_cond_wait(&g_q_cond, &g_q_mutex);
    }
    if (g_q_count == 0 && !running) {
        pthread_mutex_unlock(&g_q_mutex);
        return -1;
    }
    *out = g_queue[g_q_head];
    g_q_head = (g_q_head + 1) % QUEUE_SIZE;
    g_q_count--;
    pthread_mutex_unlock(&g_q_mutex);
    return 0;
}

static void* modbus_sender_thread(void* arg)
{
    (void)arg;
    while (running) {
        /* Ensure connection (will retry with backoff until running==0) */
        if (ensure_modbus_connected() != 0) break;
        QueueEntry e;
        if (queue_pop(&e) != 0) break;

        /* send via Modbus (function 0x06 single register) */
        if (modbus_write_registers(e.addr, e.values, e.count) != 0) {
            fprintf(stderr, "modbus_sender: failed to send addr=%u count=%u stNum=%u\n",
                (unsigned)e.addr, (unsigned)e.count, (unsigned)e.stNum);
            /* Close socket and mark disconnected so ensure_modbus_connected will reconnect */
            if (g_modbus_sock >= 0) {
                close(g_modbus_sock);
                g_modbus_sock = -1;
            }
        } else {
                 printf("[MODBUS SEND] addr=%u count=%u stNum=%u\n",
                     (unsigned)e.addr, (unsigned)e.count, (unsigned)e.stNum);
        }
    }
    return NULL;
}

/* =========================
 * 业务定义
 * ========================= */
#define PCS_MODE_STOP      0
#define PCS_MODE_GRID      1
#define PCS_MODE_ISLAND    2
#define LOCAL_EPT_ADDR  19

typedef struct
{
    GooseReceiver receiver;
    GooseSubscriber subscriber;

    /* 最近一次收到的上层 stNum，用于去重 */
    uint32_t lastUpperStNum;
    bool lastUpperStNumValid;
} UpstreamSubscriber_t;

static UpstreamSubscriber_t  g_up   = {0};

/* =========================
 * 工具函数
 * ========================= */
static const char* modeToStr(int32_t mode)
{
    switch (mode) {
        case PCS_MODE_STOP:   return "STOP";
        case PCS_MODE_GRID:   return "GRID";
        case PCS_MODE_ISLAND: return "ISLAND";
        default:              return "UNKNOWN";
    }
}

static bool ctrlEquals(const GooseCtrl_t* a, const GooseCtrl_t* b)
{
    if (a == NULL || b == NULL)
        return false;

    return (a->startCmd == b->startCmd) &&
           (a->stopCmd  == b->stopCmd)  &&
           (a->modeCmd  == b->modeCmd)  &&
           (a->pset     == b->pset)     &&
           (a->qset     == b->qset);
}

static bool ctrlIsValid(const GooseCtrl_t* ctrl)
{
    if (ctrl == NULL)
        return false;

    /* 启停同时有效，判定非法 */
    if (ctrl->startCmd && ctrl->stopCmd)
        return false;

    /* 模式范围检查 */
    if ((ctrl->modeCmd != PCS_MODE_STOP) &&
        (ctrl->modeCmd != PCS_MODE_GRID) &&
        (ctrl->modeCmd != PCS_MODE_ISLAND))
        return false;

    return true;
}

/* =========================
 * 下层发布器
 * ========================= */
static int initDownstreamPublisher(void)
{
    CommParameters params;
    memset(&params, 0, sizeof(params));

    params.appId        = 0x0001;  /* ICD: APPID 0001 */
    params.vlanPriority = 4;
    params.vlanId       = 0;

    /* 下层 GOOSE 组播地址 */
    uint8_t dst[6] = {0x01, 0x0c, 0xcd, 0x01, 0x00, 0x01};
    memcpy(params.dstAddress, dst, 6);

    g_down.pub = GoosePublisher_create(&params, "net2");
    if (g_down.pub == NULL) {
        fprintf(stderr, "GoosePublisher_create failed\n");
        return -1;
    }

    /* ICD: IED=TEMPLATE, LDevice=PIGO, GoCB=gocb1, DataSet=dsGOOSE1. */
    GoosePublisher_setGoCbRef(g_down.pub, "TEMPLATE/PIGO$GO$gocb1");
    GoosePublisher_setDataSetRef(g_down.pub, "TEMPLATE/PIGO$dsGOOSE1");
    GoosePublisher_setGoID(g_down.pub, "gocb1");
    GoosePublisher_setTimeAllowedToLive(g_down.pub, 5000);

    g_down.ds = LinkedList_create();
    if (g_down.ds == NULL) {
        fprintf(stderr, "LinkedList_create failed\n");
        GoosePublisher_destroy(g_down.pub);
        g_down.pub = NULL;
        return -1;
    }

    /* Add one integer value per mapping, in the exact SCD/CID DataSet order. */
    if (shm_goose_mapping_count > 128) {
        fprintf(stderr, "Too many GOOSE DataSet items\n");
        return -1;
    }
    for (size_t i = 0; i < shm_goose_mapping_count; ++i) {
        if (shm_goose_mappings[i].type == GOOSE_VALUE_BOOL)
            g_down.values[i] = MmsValue_newBoolean(false);
        else if (shm_goose_mappings[i].type == GOOSE_VALUE_FLOAT32)
            g_down.values[i] = MmsValue_newFloat(0.0f);
        else
            g_down.values[i] = MmsValue_newIntegerFromInt32(0);
        if (g_down.values[i] == NULL) {
            fprintf(stderr, "MmsValue allocation failed at index %zu\n", i);
            return -1;
        }
        LinkedList_add(g_down.ds, g_down.values[i]);
    }
    g_down.value_count = shm_goose_mapping_count;

    printf("Downstream publisher ready\n");
    printf("  ifname    : net2\n");


    return 0;
}

static void deinitDownstreamPublisher(void)
{
    /* 清理 Modbus 连接（如果使用） */
    /* stop sender thread and clean up */
    running = 0;
    pthread_cond_broadcast(&g_q_cond);
    /* join thread if started */
    if (g_modbus_thread_started) {
        pthread_join(g_modbus_thread, NULL);
        g_modbus_thread_started = 0;
    }
    if (g_goose_pub_thread_started) {
        pthread_join(g_goose_pub_thread, NULL);
        g_goose_pub_thread_started = 0;
    }
    deinitModbusClient();
    for (size_t i = 0; i < g_down.value_count; ++i) {
        if (g_down.values[i]) MmsValue_delete(g_down.values[i]);
    }

    if (g_down.ds) LinkedList_destroy(g_down.ds);
    if (g_down.pub) GoosePublisher_destroy(g_down.pub);

    memset(&g_down, 0, sizeof(g_down));
}

/* =========================
 * 上层接收器
 * ========================= */
static bool parseUpperDataset(GooseSubscriber subscriber, GoosePower_t* outpower)
{
    if (subscriber == NULL || outpower == NULL)
        return false;

    MmsValue* dataSetValues = GooseSubscriber_getDataSetValues(subscriber);

    if (dataSetValues == NULL)
        return false;

    int count = MmsValue_getArraySize(dataSetValues);

    /* 数据集长度必须符合预期 */
    if (count != LC_MAX_NUM * MAX_SUB_NUM)
    {
        if (count < LC_MAX_NUM * MAX_SUB_NUM)
        {
            memset(outpower->powerset, 0, sizeof(outpower->powerset));
            printf("GOOSE数据集长度错误: count=%d, expected=%d\n", count, MAX_SUB_NUM);
            return false;
        }
        printf("GOOSE数据集长度错误(大于预期大小,不影响解析): count=%d, expected=%d\n", count, MAX_SUB_NUM);
        memset(outpower->powerset, 0, sizeof(outpower->powerset));
        // return false;
    }

    /* 每个LC8个数据,根据LC ID取出对应位置的数据 */
    for (int i = 0; i < MAX_SUB_NUM; i++)
    {
        uint16_t point_start = (LC_ID - 1) * MAX_SUB_NUM + i;
        /* TEST */
        // point_start = (point_start * 2 + 1) + 4; 
        MmsValue* tmp = MmsValue_getElement(dataSetValues, point_start);
        if (tmp == NULL)
        {
            printf("GOOSE数据集元素为空: index=%d\n", i);
            memset(outpower->powerset, 0, sizeof(outpower->powerset));
            return false;
        }
        if (MmsValue_getType(tmp) != MMS_INTEGER)
        {
            printf("GOOSE下发数据类型有误: index=%d, type=%d\n", i, MmsValue_getType(tmp));
            memset(outpower->powerset, 0, sizeof(outpower->powerset));
            return false;
        }
        outpower->powerset[i] = MmsValue_toInt32(tmp);
    }
    printf("Receive data lenth: %d\n", count);

    return true;
}

/* 上层 GOOSE 接收回调：收到后立即向下发 */
static void onUpperGooseReceived(GooseSubscriber subscriber, void* parameter)
{
    (void)parameter;

    if (!GooseSubscriber_isValid(subscriber)) {
        GLOG("WARNING", "Authenticated GOOSE rejected by dataset decoder; no Modbus forwarding");
        return;
    }
    uint32_t stNum = GooseSubscriber_getStNum(subscriber);
    bool is_valid = false;
    uint16_t pcs_group = 0;
    uint16_t base_addr = 0;
    uint16_t actual_addr = 0;
    /* 只对新的 stNum 做快速转发
     * 因为同一状态变化后，上层会按 sqNum 重发很多帧
     */
    if (g_up.lastUpperStNumValid && stNum == g_up.lastUpperStNum) {
        return;
    }

    GoosePower_t outpower;
    memset(&outpower, 0, sizeof(outpower));

    is_valid = parseUpperDataset(subscriber, &outpower);
    if (is_valid == false)
    {
        printf("reveive invalid data, skip modbus");
        return;
    }

    /* 按连续地址聚合后入队，由 Modbus 线程使用 0x10 批量发送。 */
    uint16_t batch_values[MAX_SUB_NUM];
    uint16_t batch_start = 0;
    uint16_t batch_count = 0;
    uint16_t _count = 0;

    /* 双BUS取索引0、1、2、3和4、5、6、7,一次下发四个连续值 */
    if (BUS_MODE == D_BUS)
    {
        for (int i = 0; i < (MAX_PCS_NUM / 2); i++)
        {
            base_addr = MODBUS_ACTIVE_REG_ADDR1;
            pcs_group = i;
            actual_addr = base_addr + pcs_group * PCSGROUP_OFFSET;

            /* 地址不连续需分批发送 */
            if (batch_count > 0 && actual_addr != batch_start + batch_count) {
                queue_push(batch_start, batch_values, batch_count, stNum);
                batch_count = 0;
                memset(batch_values, 0, sizeof(batch_values));
            }
            if (batch_count == 0)
                batch_start = actual_addr;

            for (size_t i = 0; i < MAX_SUB_NUM / 2; i++)
            {
                if (_count >= MAX_SUB_NUM)
                {
                    printf("_count计数异常,已跳过");
                    continue;
                }
                batch_values[batch_count++] = (uint16_t)outpower.powerset[_count];
                _count++;
            }
        }
    }
    /* 单BUS取索引0、1和4、5,一次下发两个连续值 */
    else
    {
        for (int i = 0; i < (MAX_PCS_NUM / 2); i++)
        {
            _count = i * 4;
            base_addr = MODBUS_ACTIVE_REG_ADDR1;
            pcs_group = i;
            actual_addr = base_addr + pcs_group * PCSGROUP_OFFSET;

            /* 地址不连续需分批发送 */
            if (batch_count > 0 && actual_addr != batch_start + batch_count) {
                queue_push(batch_start, batch_values, batch_count, stNum);
                batch_count = 0;
                memset(batch_values, 0, sizeof(batch_values));
            }
            if (batch_count == 0)
                batch_start = actual_addr;
            /* 单BUS取索引0、1、4、5 */
            for (size_t i = 0; i < MAX_SUB_NUM / 2; i++)
            {
                batch_values[batch_count++] = (uint16_t)outpower.powerset[_count];
                _count++;
            }
        }
    }

    if (batch_count > 0) {
        queue_push(batch_start, batch_values, batch_count, stNum);
        memset(batch_values, 0, sizeof(batch_values));
    }
}

/* Called only by the secure receive thread before the first frame of a new
 * session. Reset the legacy decoder counters without touching Modbus state. */
static int resetUpstreamSession(void)
{
    uint8_t dst[6] = {0x01, 0x0c, 0xcd, 0x01, 0x00, 0x00};
    GooseSubscriber next = GooseSubscriber_create(SUbSCRIBER1_goCbRef, NULL);
    if (!next) return -1;
    GooseSubscriber_setDstMac(next, dst);
    GooseSubscriber_setAppId(next, SUbSCRIBER1_APPID);
    GooseSubscriber_setListener(next, onUpperGooseReceived, NULL);
    GooseReceiver_removeSubscriber(g_up.receiver, g_up.subscriber);
    GooseSubscriber_destroy(g_up.subscriber);
    g_up.subscriber = next;
    GooseReceiver_addSubscriber(g_up.receiver, next);
    g_up.lastUpperStNumValid = false;
    GLOG("INFO", "New authenticated GOOSE session: decoder counters reset");
    return 0;
}

static int initUpstreamSubscriber(void)
{
    uint8_t dst[6] = {0x01, 0x0c, 0xcd, 0x01, 0x00, 0x00};
    g_up.receiver = GooseReceiver_create();
    if (g_up.receiver == NULL) {
        fprintf(stderr, "GooseReceiver_create failed\n");
        return -1;
    }

    /* 上层接收网口 */
    GooseReceiver_setInterfaceId(g_up.receiver, SUbSCRIBER1_NET);

    /* 上层 goCbRef */
    g_up.subscriber = GooseSubscriber_create(SUbSCRIBER1_goCbRef, NULL);
    if (g_up.subscriber == NULL) {
        fprintf(stderr, "GooseSubscriber_create failed\n");
        GooseReceiver_destroy(g_up.receiver);
        g_up.receiver = NULL;
        return -1;
    }
    GooseSubscriber_setDstMac(g_up.subscriber, dst);
    GooseSubscriber_setAppId(g_up.subscriber, SUbSCRIBER1_APPID);
    GooseSubscriber_setListener(g_up.subscriber, onUpperGooseReceived, NULL);

    GooseReceiver_addSubscriber(g_up.receiver, g_up.subscriber);
    const char *pki_directory = getenv("GOOSE_PKI_DIR");
    if (!pki_directory || !*pki_directory) pki_directory = "/etc/ems/goose";
    g_up.lastUpperStNumValid = false;
    g_secure_transport = goose_transport_start(g_up.receiver, SUbSCRIBER1_NET,
        pki_directory, SUbSCRIBER1_APPID, dst, SUbSCRIBER1_goCbRef, resetUpstreamSession);
    if (!g_secure_transport) {
        GooseReceiver_destroy(g_up.receiver); /* receiver owns its subscribers */
        memset(&g_up, 0, sizeof(g_up));
        return -1;
    }

    printf("=============================================================\n");
    printf("================ Upstream subscriber ready ==================\n");
    printf("====================== ifname  : %s =======================\n", SUbSCRIBER1_NET);
    printf("=============================================================\n");


    return 0;
}

static void deinitUpstreamSubscriber(void)
{
    goose_transport_stop(g_secure_transport);
    g_secure_transport = NULL;

    if (g_up.receiver)
        GooseReceiver_destroy(g_up.receiver);

    memset(&g_up, 0, sizeof(g_up));
}

/* =========================
 * main
 * ========================= */
int main(void)
{
    signal(SIGINT, onSig);
    signal(SIGTERM, onSig);

    // if (initDownstreamPublisher() != 0) {
    //     fprintf(stderr, "initDownstreamPublisher failed\n");
    //     return -1;
    // }
    // 改用通过modbus tcp下发
    printf("=============================================================\n");
    printf("====================== Start Succeed! =======================\n");
    printf("=================== goose --> modbus tcp ====================\n");
    printf("=============================================================\n");

    initial_modbus_addr_list();

    if (initModbusClient() != 0) {
        fprintf(stderr, "initModbusClient failed\n");
        return -1;
    }

    /* start modbus sender thread */
    if (pthread_create(&g_modbus_thread, NULL, modbus_sender_thread, NULL) != 0) {
        perror("pthread_create");
        deinitModbusClient();
        return -1;
    }
    g_modbus_thread_started = 1;
    printf("==================Modbus sender thread started===============\n");
    /* start goose publisher thread (reads shared memory and publishes) */
    // if (pthread_create(&g_goose_pub_thread, NULL, goose_publisher_thread, NULL) != 0) {
    //     perror("pthread_create(goose_publisher)");
    //     /* not fatal: continue without publisher thread */
    // } else {
    //     g_goose_pub_thread_started = 1;
    // }

    if (initUpstreamSubscriber() != 0) {
        fprintf(stderr, "initUpstreamSubscriber failed\n");
        deinitDownstreamPublisher();
        return -1;
    }

    printf("=============================================================\n");
    printf("================ GOOSE fast bridge started ==================\n");
    printf("======== Upper -> Lower immediate forwarding enabled ========\n");
    printf("=================== Press Ctrl+C to exit ====================\n");
    printf("=============================================================\n");

    int security_failed = 0;
    while (running) {
        if (!goose_transport_is_running(g_secure_transport)) {
            GLOG("ERROR", "Secure GOOSE receiver failed; stopping bridge without plaintext fallback");
            security_failed = 1;
            break;
        }
        sleep(1);
    }
    running = 0;

    deinitUpstreamSubscriber();
    deinitDownstreamPublisher();

    printf("=============================================================\n");
    printf("=========================== Bye Bye =========================\n");
    printf("=============================================================\n");

    return security_failed ? 1 : 0;
}