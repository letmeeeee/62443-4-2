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

static pthread_mutex_t log_lock = PTHREAD_MUTEX_INITIALIZER;

void goose_log_write(const char *file, int line, const char *func,
                     const char *level, const char *format, ...)
{
    char message[2048], timestamp[32], day[16], path[1024], record[2400];
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
    const char *directory = getenv("GOOSE_LOG_DIR");
    if (!directory || !*directory) directory = "/mnt/nvme/goose_log";
    pthread_mutex_lock(&log_lock);
    fputs(record, stderr);
    static int storage_warning;
    /* The mounted parent must exist. Never create or modify other modules' dirs. */
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
    pthread_mutex_unlock(&log_lock);
}
