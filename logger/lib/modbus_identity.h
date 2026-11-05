#ifndef MODBUS_IDENTITY_H
#define MODBUS_IDENTITY_H
#include <openssl/evp.h>
#include <openssl/x509.h>

/* MODBUS_KEY_BACKEND: unset=file; explicit file|tee. No automatic fallback. */
const char *Modbus_Identity_Backend(void);
/* role: 0 master, 1 slave. File keys are adjacent to certificate_path (.key). */
int Modbus_Identity_Ensure(unsigned role, const char *certificate_path);
EVP_PKEY *Modbus_Identity_Key(unsigned role, const char *certificate_path);
int Modbus_Identity_Check(X509 *certificate, unsigned role, const char *certificate_path);
/* [TLS] certificate_mode in LC_INI_PATH (default device INI): 1 CA, -1 invalid; legacy non-CA settings are rejected. */
int Modbus_Certificate_Mode(void);
const char *Modbus_CA_File(void);
#endif
