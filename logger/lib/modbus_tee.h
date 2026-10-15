#ifndef MODBUS_TEE_H
#define MODBUS_TEE_H
#include <openssl/evp.h>
#include <openssl/x509.h>
/* Role: 0 master, 1 slave. No private key material leaves the TA. */
int Modbus_TEE_Ensure(unsigned role);
EVP_PKEY *Modbus_TEE_Key(unsigned role);
int Modbus_TEE_Check(X509 *certificate, unsigned role);
#endif
