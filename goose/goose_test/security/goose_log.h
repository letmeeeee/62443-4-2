#ifndef GOOSE_LOG_H
#define GOOSE_LOG_H
#include <stddef.h>
#include <stdint.h>
void goose_log_write(const char *file, int line, const char *func,
                     const char *level, const char *format, ...)
    __attribute__((format(printf, 5, 6)));
#define GLOG(level, ...) goose_log_write(__FILE__, __LINE__, __func__, level, __VA_ARGS__)
int goose_log_sample(uint64_t count);
void goose_log_packet(const char *file, int line, const char *func,
                      const char *label, const void *data, size_t size);
/* Opt-in raw wire diagnostics: first 64 bytes only, never decrypted GOOSE data. */
#define GPACKET(label, data, size) goose_log_packet(__FILE__, __LINE__, __func__, label, data, size)
#endif
