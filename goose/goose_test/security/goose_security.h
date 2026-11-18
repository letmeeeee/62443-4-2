#ifndef GOOSE_SECURITY_H
#define GOOSE_SECURITY_H
#include <stddef.h>
#include <stdint.h>
#define GSEC_MAX_HANDSHAKE 1024
#define GSEC_MAX_FRAME 2048

typedef struct GooseSecurity GooseSecurity;
/* One authenticated publisher and one configured control block per instance.
 * Calls are serialized by the bridge event loop. No caller-visible key material.
 * PKI uses the same unencrypted PEM file-key model as existing TLS imports. */
GooseSecurity *gsec_create(const char *pki_dir, uint16_t appid,
                          const uint8_t destination[6], const char *gocb_ref);
void gsec_destroy(GooseSecurity *security);
/* peer is the opaque source IP, used solely for routing cached ACKs. */
int gsec_hello(GooseSecurity *security, const uint8_t *packet, size_t length,
               uint32_t peer, uint8_t ack[GSEC_MAX_HANDSHAKE], size_t *ack_length);
/* Returns reconstructed, authenticated plaintext Ethernet frame length, or -1.
 * Output is erased on rejection; only success may enter libiec61850. */
int gsec_open_frame(GooseSecurity *security, const uint8_t *frame, size_t length,
                     uint8_t plain[GSEC_MAX_FRAME], int *new_session);
#endif
