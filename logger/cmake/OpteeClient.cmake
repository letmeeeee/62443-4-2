# Shared by tems and the standalone crypto client. Paths follow the checkout.
get_filename_component(_optee_project_root "${CMAKE_CURRENT_LIST_DIR}/../.." ABSOLUTE)
set(OPTEE_CLIENT_ROOT "${_optee_project_root}/logger/.deps/optee-arm64" CACHE PATH
    "Project-local target OP-TEE Client SDK")
set(OPTEE_CLIENT_INCLUDE_DIR "" CACHE PATH "Target tee_client_api.h directory")
set(OPTEE_CLIENT_LIBRARY "" CACHE FILEPATH "Target AArch64 libteec")
if(NOT OPTEE_CLIENT_INCLUDE_DIR)
  set(OPTEE_CLIENT_INCLUDE_DIR "${OPTEE_CLIENT_ROOT}/include")
endif()
if(NOT OPTEE_CLIENT_LIBRARY)
  if(EXISTS "${OPTEE_CLIENT_ROOT}/lib/libteec.so")
    set(OPTEE_CLIENT_LIBRARY "${OPTEE_CLIENT_ROOT}/lib/libteec.so")
  elseif(EXISTS "${OPTEE_CLIENT_ROOT}/lib/libteec.a")
    set(OPTEE_CLIENT_LIBRARY "${OPTEE_CLIENT_ROOT}/lib/libteec.a")
  endif()
endif()
if(NOT EXISTS "${OPTEE_CLIENT_INCLUDE_DIR}/tee_client_api.h" OR
   NOT EXISTS "${OPTEE_CLIENT_LIBRARY}")
  message(FATAL_ERROR
    "Project OP-TEE Client SDK is missing. Run: sh ${_optee_project_root}/logger/scripts/prepare_optee_client.sh --device root@DEVICE_IP ; "
    "or import an SDK with --header /path/tee_client_api.h --library /path/libteec.so.2.0.0. "
    "Explicit OPTEE_CLIENT_INCLUDE_DIR/OPTEE_CLIENT_LIBRARY overrides are also supported.")
endif()
message(STATUS "OP-TEE headers: ${OPTEE_CLIENT_INCLUDE_DIR}")
file(READ "${OPTEE_CLIENT_INCLUDE_DIR}/tee_client_api.h" _optee_header)
if(_optee_header MATCHES "TEST_TEE_CLIENT_API_H")
  message(FATAL_ERROR "The selected tee_client_api.h is a test stub, not a target SDK header")
endif()
message(STATUS "OP-TEE library: ${OPTEE_CLIENT_LIBRARY}")
