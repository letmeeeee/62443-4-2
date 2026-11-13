#ifndef MODBUS_PEERS_H
#define MODBUS_PEERS_H
#include <openssl/ssl.h>
/* Best-effort telemetry only; these calls preserve errno and never alter TLS policy.
 * PEM/state I/O belongs to the publisher thread, not the Modbus transport threads. */
void Modbus_Peers_Start(int tls_enabled);
void Modbus_Peers_Add(int fd, int server, SSL *ssl);
void Modbus_Peers_Remove(int fd);
#endif
