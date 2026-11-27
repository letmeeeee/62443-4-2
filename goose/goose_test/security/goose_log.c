#define _GNU_SOURCE
#include "goose_log.h"
#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/time.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <pthread.h>
#define DebugEnable 1

static pthread_mutex_t log_lock = PTHREAD_MUTEX_INITIALIZER;
#define LOG_QUEUE_SIZE 256
typedef struct {
    char record[2400];
    char day[16];
} LogEntry;
static LogEntry log_queue[LOG_QUEUE_SIZE];
static pthread_cond_t log_ready = PTHREAD_COND_INITIALIZER;
static pthread_t log_thread;
static size_t log_head, log_tail, log_count;
static uint64_t log_dropped;
static int log_async, log_stopping;

static void write_record(const char *record, const char *day)
{
    char path[1024];
    const char *directory = getenv("GOOSE_LOG_DIR");
    if (!directory || !*directory) directory = "/mnt/nvme/goose_log";
    fputs(record, stderr);
    static int storage_warning;
    if (mkdir(directory, 0750) == 0 || access(directory, W_OK) == 0) {
        int n = snprintf(path, sizeof(path), "%s/%s.log", directory, day);
        if (n > 0 && (size_t)n < sizeof(path)) {
            int fd = open(path, O_WRONLY|O_APPEND|O_CREAT|O_CLOEXEC|O_NOFOLLOW, 0640);
            if (fd >= 0) {
                size_t offset = 0, size = strlen(record);
                while (offset < size) {
                    ssize_t written = write(fd, record+offset, size-offset);
                    if (written <= 0) break;
                    offset += (size_t)written;
                }
                close(fd);
            } else if (!storage_warning) {
                fputs("GOOSE log file unavailable; diagnostics continue on stderr\n",stderr);
                storage_warning=1;
            }
        }
    } else if (!storage_warning) {
        fputs("GOOSE log directory unavailable; diagnostics continue on stderr\n",stderr);
        storage_warning=1;
    }
}

static void *log_worker(void *unused)
{
    (void)unused;
    LogEntry entry;
    for (;;) {
        pthread_mutex_lock(&log_lock);
        while (!log_count && !log_stopping)
            pthread_cond_wait(&log_ready, &log_lock);
        if (!log_count && log_stopping) {
            pthread_mutex_unlock(&log_lock);
            break;
        }
        entry = log_queue[log_head];
        log_head = (log_head + 1) % LOG_QUEUE_SIZE;
        log_count--;
        uint64_t dropped = log_dropped;
        log_dropped = 0;
        pthread_mutex_unlock(&log_lock);
        if (dropped) {
            char warning[160];
            snprintf(warning,sizeof(warning),"GOOSE log queue overflow: dropped %llu records\n",
                     (unsigned long long)dropped);
            write_record(warning,entry.day);
        }
        write_record(entry.record,entry.day);
    }
    return NULL;
}

int goose_log_start_async(void)
{
    pthread_mutex_lock(&log_lock);
    if (log_async) { pthread_mutex_unlock(&log_lock); return 0; }
    log_stopping = 0;
    int error = pthread_create(&log_thread,NULL,log_worker,NULL);
    if (!error) log_async = 1;
    pthread_mutex_unlock(&log_lock);
    return error ? -1 : 0;
}

void goose_log_stop_async(void)
{
    pthread_mutex_lock(&log_lock);
    if (!log_async) { pthread_mutex_unlock(&log_lock); return; }
    log_stopping = 1;
    pthread_cond_signal(&log_ready);
    pthread_mutex_unlock(&log_lock);
    pthread_join(log_thread,NULL);
    pthread_mutex_lock(&log_lock);
    log_async = 0;
    log_stopping = 0;
    pthread_mutex_unlock(&log_lock);
}

int goose_log_sample(uint64_t count)
{
    return DebugEnable || (count <= 10 || count % 100 == 0);
}

void goose_log_packet(const char *file, int line, const char *func,
                      const char *label, const void *data, size_t size)
{
    const char *enabled = getenv("GOOSE_PACKET_TRACE");
    if (!enabled || strcmp(enabled,"1") || !data) return;
    const unsigned char *bytes=data;
    char hex[64*3+1];
    size_t shown=size < 64 ? size : 64;
    for (size_t i=0;i<shown;i++)
        snprintf(hex+i*3,4,"%02x%s",bytes[i],i+1==shown ? "" : " ");
    if (!shown) hex[0]=0;
    goose_log_write(file,line,func,"DEBUG","%s bytes=%zu shown=%zu hex=%s%s",
                    label,size,shown,hex,size>shown ? " ..." : "");
}

void goose_log_write(const char *file, int line, const char *func,
                     const char *level, const char *format, ...)
{
    char message[2048], timestamp[32], day[16], record[2400];
    struct timeval now;
    struct tm calendar;
    va_list args;
    va_start(args, format);
    vsnprintf(message, sizeof(message), format, args);
    va_end(args);
    /* Keep a record on one line, including messages received from OpenSSL. */
    size_t length = strlen(message);
    while (length && (message[length-1] == '\n' || message[length-1] == '\r'))
        message[--length] = 0;
    for (size_t i = 0; i < length; i++)
        if ((unsigned char)message[i] < 32) message[i] = ' ';
    gettimeofday(&now, NULL);
    localtime_r(&now.tv_sec, &calendar);
    strftime(timestamp, sizeof(timestamp), "%Y-%m-%d %H:%M:%S", &calendar);
    strftime(day, sizeof(day), "%Y-%m-%d", &calendar);
    const char *base = strrchr(file, '/');
    snprintf(record, sizeof(record), "[%s.%06ld] [%s:%d] [%s] [%s] %s\n",
             timestamp, (long)now.tv_usec, base ? base+1 : file, line, func, level, message);
    pthread_mutex_lock(&log_lock);
    if (log_async && !log_stopping) {
        if (log_count == LOG_QUEUE_SIZE) log_dropped++;
        else {
            LogEntry *entry = &log_queue[log_tail];
            memcpy(entry->record,record,strlen(record)+1);
            memcpy(entry->day,day,strlen(day)+1);
            log_tail = (log_tail + 1) % LOG_QUEUE_SIZE;
            log_count++;
            pthread_cond_signal(&log_ready);
        }
        pthread_mutex_unlock(&log_lock);
        return;
    }
    /* Startup and test users without an async worker retain direct logging. */
    write_record(record,day);
    pthread_mutex_unlock(&log_lock);
}
