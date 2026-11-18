#ifndef GOOSE_LOG_H
#define GOOSE_LOG_H
void goose_log_write(const char *file, int line, const char *func,
                     const char *level, const char *format, ...)
    __attribute__((format(printf, 5, 6)));
#define GLOG(level, ...) goose_log_write(__FILE__, __LINE__, __func__, level, __VA_ARGS__)
#endif
