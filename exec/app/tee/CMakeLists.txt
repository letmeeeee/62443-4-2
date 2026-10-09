cmake_minimum_required(VERSION 3.16)

project(crypto_ta_client VERSION 1.0 LANGUAGES C)

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

set(OPTEE_CLIENT_INCLUDE_DIR "" CACHE PATH
    "Directory containing the target tee_client_api.h")
set(OPTEE_CLIENT_LIBRARY "" CACHE FILEPATH
    "Target-architecture libteec.so or libteec.a")

if(NOT OPTEE_CLIENT_INCLUDE_DIR OR
   NOT EXISTS "${OPTEE_CLIENT_INCLUDE_DIR}/tee_client_api.h")
    find_path(OPTEE_CLIENT_INCLUDE_DIR
        NAMES tee_client_api.h
        PATH_SUFFIXES include include/optee-client)
endif()

if(NOT OPTEE_CLIENT_LIBRARY OR NOT EXISTS "${OPTEE_CLIENT_LIBRARY}")
    find_library(OPTEE_CLIENT_LIBRARY NAMES teec)
endif()

if(NOT OPTEE_CLIENT_INCLUDE_DIR OR
   NOT EXISTS "${OPTEE_CLIENT_INCLUDE_DIR}/tee_client_api.h")
    message(FATAL_ERROR
        "Target tee_client_api.h was not found. Set "
        "-DOPTEE_CLIENT_INCLUDE_DIR=/path/to/optee_client/include")
endif()

if(NOT OPTEE_CLIENT_LIBRARY OR NOT EXISTS "${OPTEE_CLIENT_LIBRARY}")
    message(FATAL_ERROR
        "Target libteec was not found. Set "
        "-DOPTEE_CLIENT_LIBRARY=/path/to/libteec.so (or libteec.a)")
endif()

add_executable(crypto_ta_client crypto_ta_client.c)
target_include_directories(crypto_ta_client PRIVATE
    "${OPTEE_CLIENT_INCLUDE_DIR}"
    "${CMAKE_CURRENT_SOURCE_DIR}/../../../optee_ta_examples/ta/crypto_ta/include")
target_link_libraries(crypto_ta_client PRIVATE "${OPTEE_CLIENT_LIBRARY}")
target_compile_options(crypto_ta_client PRIVATE -Wall -Wextra -Werror)

install(TARGETS crypto_ta_client RUNTIME DESTINATION home/zlg/app/bin)
install(PROGRAMS ../script/crypto_ta.sh DESTINATION home/zlg/app/scripts)
