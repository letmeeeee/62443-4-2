#ifndef GOOSE_TRANSPORT_H
#define GOOSE_TRANSPORT_H
#include "goose_security.h"
#include "goose_receiver.h"
/* Owns Ethernet and UDP sockets; uses the existing decoder only after authentication. */
typedef struct GooseTransport GooseTransport;
GooseTransport *goose_transport_start(GooseReceiver receiver, const char *interface,
    const char *pki_dir, uint16_t appid, const uint8_t destination[6], const char *reference, int (*on_session)(void));
int goose_transport_is_running(GooseTransport *transport);
void goose_transport_stop(GooseTransport *transport);
#endif
