cmake_minimum_required(VERSION 3.16)

project(crypto_ta_client VERSION 1.0 LANGUAGES C)

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

include("${CMAKE_CURRENT_SOURCE_DIR}/../../../logger/cmake/OpteeClient.cmake")

add_executable(crypto_ta_client crypto_ta_client.c)
target_include_directories(crypto_ta_client PRIVATE
    "${OPTEE_CLIENT_INCLUDE_DIR}"
    "${CMAKE_CURRENT_SOURCE_DIR}/../../../optee_ta_examples/ta/crypto_ta/include")
target_link_libraries(crypto_ta_client PRIVATE "${OPTEE_CLIENT_LIBRARY}")
target_compile_options(crypto_ta_client PRIVATE -Wall -Wextra -Werror)

install(TARGETS crypto_ta_client RUNTIME DESTINATION home/zlg/app/bin)
install(PROGRAMS ../script/crypto_ta.sh DESTINATION home/zlg/app/scripts)
