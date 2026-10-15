/* Archived CLI test stub; never use this for a deployed client. */
#ifndef TEST_TEE_CLIENT_API_H
#define TEST_TEE_CLIENT_API_H

#include <stddef.h>
#include <stdint.h>

#define TEEC_SUCCESS 0U
#define TEEC_LOGIN_PUBLIC 0U
#define TEEC_NONE 0U
#define TEEC_VALUE_OUTPUT 3U
#define TEEC_MEMREF_TEMP_INPUT 5U
#define TEEC_MEMREF_TEMP_OUTPUT 6U
#define TEEC_PARAM_TYPES(t0, t1, t2, t3) \
    ((t0) | ((t1) << 4) | ((t2) << 8) | ((t3) << 12))

typedef uint32_t TEEC_Result;
typedef struct { uint32_t timeLow; uint16_t timeMid; uint16_t timeHiAndVersion;
                 uint8_t clockSeqAndNode[8]; } TEEC_UUID;
typedef struct { void *imp; } TEEC_Context;
typedef struct { void *imp; } TEEC_Session;
typedef struct { void *buffer; size_t size; } TEEC_TempMemoryReference;
typedef struct { uint32_t a; uint32_t b; } TEEC_Value;
typedef union { TEEC_TempMemoryReference tmpref; TEEC_Value value; } TEEC_Parameter;
typedef struct { uint32_t started; uint32_t paramTypes;
                 TEEC_Parameter params[4]; void *imp; } TEEC_Operation;

TEEC_Result TEEC_InitializeContext(const char *, TEEC_Context *);
void TEEC_FinalizeContext(TEEC_Context *);
TEEC_Result TEEC_OpenSession(TEEC_Context *, TEEC_Session *, const TEEC_UUID *,
                             uint32_t, const void *, TEEC_Operation *, uint32_t *);
void TEEC_CloseSession(TEEC_Session *);
TEEC_Result TEEC_InvokeCommand(TEEC_Session *, uint32_t, TEEC_Operation *, uint32_t *);

#endif
