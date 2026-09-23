#ifndef MODBUS_TRANSPORT_H
#define MODBUS_TRANSPORT_H

#include <stddef.h>
#include <sys/types.h>

/* Mode comes from SysConf_GetInfo()->modbus_tls_enabled:
 * 0: plaintext Modbus TCP; 1: TLS 1.2+, slave verifies master certificate.
 * Load configuration before starting communication threads and keep it fixed
 * until process exit. Mode/certificate changes require restarting the process.
 * TLS with ISPLANT_V RTU transport is rejected at runtime.
 */
#ifndef MODBUS_TLS_SERVER_CERT
#define MODBUS_TLS_SERVER_CERT "/etc/ems/modbus/slave.crt"
#endif
#ifndef MODBUS_TLS_SERVER_KEY
#define MODBUS_TLS_SERVER_KEY "/etc/ems/modbus/slave.key"
#endif
#ifndef MODBUS_TLS_CLIENT_CA
#define MODBUS_TLS_CLIENT_CA "/etc/ems/modbus/master-ca.crt"
#endif
#ifndef MODBUS_TLS_CLIENT_CERT
#define MODBUS_TLS_CLIENT_CERT "/etc/ems/modbus/master.crt"
#endif
#ifndef MODBUS_TLS_CLIENT_KEY
#define MODBUS_TLS_CLIENT_KEY "/etc/ems/modbus/master.key"
#endif
#ifndef MODBUS_TLS_HANDSHAKE_MS
#define MODBUS_TLS_HANDSHAKE_MS 5000
#endif
#ifndef MODBUS_TLS_FRAME_MS
#define MODBUS_TLS_FRAME_MS 3000
#endif

/* Initialize before accepting connections. No plaintext fallback on failure. */
int Modbus_Server_Init(void);
/* Attach only after TCP connect/accept. Failure leaves fd owned by caller. */
int Modbus_Client_Attach(int fd);
int Modbus_Server_Attach(int fd);
/* TLS: one complete MBAP ADU; partial frames survive idle EAGAIN returns. */
ssize_t Modbus_Recv(int fd, void *buf, size_t capacity);
ssize_t Modbus_Send(int fd, const void *buf, size_t length);
/* Connection owner closes once; receive helpers do not close underneath it. */
int Modbus_Close(int fd);
#endif
