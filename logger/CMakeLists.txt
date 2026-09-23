cmake_minimum_required(VERSION 3.16)

# === 交叉编译工具链 ===
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_C_COMPILER "/usr/bin/aarch64-linux-gnu-gcc")
set(CMAKE_CXX_COMPILER "/usr/bin/aarch64-linux-gnu-g++")   # 让 g++ 负责最终链接
set(CMAKE_SYSTEM_PROCESSOR aarch64)
project(tems C CXX)

# === 编译标准与选项 ===
set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -g -Wall")

# === 线程库 ===
find_package(Threads REQUIRED)

# === MySQL SDK（放在工程目录下的 ./mysqlib） ===
set(MYSQLIB_DIR "${CMAKE_CURRENT_SOURCE_DIR}/mysqlib")

# 头文件路径自动探测：支持 include/mysql.h 或 include/mysql/mysql.h
if (EXISTS "${MYSQLIB_DIR}/include/mysql.h")
  set(MYSQL_INCLUDE_DIR "${MYSQLIB_DIR}/include")
elseif (EXISTS "${MYSQLIB_DIR}/include/mysql/mysql.h")
  set(MYSQL_INCLUDE_DIR "${MYSQLIB_DIR}/include/mysql")
else()
  message(FATAL_ERROR "mysql.h not found under ${MYSQLIB_DIR}/include")
endif()

# Keep OpenSSL 1.1 target headers separate from host /usr/include.
# An explicit SDK takes priority; otherwise use the reproducible local SDK.
set(MODBUS_OPENSSL_INCLUDE_DIR "" CACHE PATH "Target OpenSSL 1.1 include directory")
set(_modbus_openssl_include "${MODBUS_OPENSSL_INCLUDE_DIR}")
if(NOT _modbus_openssl_include AND
   EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/.deps/openssl-arm64/include/openssl/ssl.h")
  set(_modbus_openssl_include "${CMAKE_CURRENT_SOURCE_DIR}/.deps/openssl-arm64/include")
endif()
if(_modbus_openssl_include)
  include_directories(BEFORE "${_modbus_openssl_include}")
  message(STATUS "Modbus target OpenSSL headers: ${_modbus_openssl_include}")
endif()

# Fail at configure time with an actionable message. In plaintext builds no
# OpenSSL headers are needed by the transport; honor its actual compile macro.
include(CheckCSourceCompiles)
set(CMAKE_REQUIRED_INCLUDES "${CMAKE_CURRENT_SOURCE_DIR}/lib")
if(_modbus_openssl_include)
  list(PREPEND CMAKE_REQUIRED_INCLUDES "${_modbus_openssl_include}")
endif()
unset(MODBUS_OPENSSL_HEADERS_OK CACHE)
check_c_source_compiles("
#include <openssl/ssl.h>
#include <openssl/opensslv.h>
#if OPENSSL_VERSION_NUMBER < 0x10101000L || OPENSSL_VERSION_NUMBER >= 0x10200000L
#error Expected target OpenSSL 1.1.1 headers for libssl.so.1.1
#endif
int main(void) { return 0; }
" MODBUS_OPENSSL_HEADERS_OK)
unset(CMAKE_REQUIRED_INCLUDES)
if(NOT MODBUS_OPENSSL_HEADERS_OK)
  message(FATAL_ERROR
    "Missing/incompatible AArch64 OpenSSL 1.1.1 headers. Run: "
    "sh ${CMAKE_CURRENT_SOURCE_DIR}/scripts/prepare_openssl_headers.sh ; "
    "then rerun cmake. Or set MODBUS_OPENSSL_INCLUDE_DIR to a complete target SDK include directory. "
    "Do not add /usr/include/x86_64-linux-gnu for an AArch64 build.")
endif()

# === 头文件搜索路径 ===
include_directories(
  ${CMAKE_CURRENT_SOURCE_DIR}/base
  ${CMAKE_CURRENT_SOURCE_DIR}/bms
  ${CMAKE_CURRENT_SOURCE_DIR}/dido
  ${CMAKE_CURRENT_SOURCE_DIR}/lib
  ${CMAKE_CURRENT_SOURCE_DIR}/logic
  ${CMAKE_CURRENT_SOURCE_DIR}/pcs
  ${CMAKE_CURRENT_SOURCE_DIR}/serival_device
  ${CMAKE_CURRENT_SOURCE_DIR}/tcp_server
  ${CMAKE_CURRENT_SOURCE_DIR}/cJSON
  ${CMAKE_CURRENT_SOURCE_DIR}/web_server
  ${CMAKE_CURRENT_SOURCE_DIR}/cem9000
  ${CMAKE_CURRENT_SOURCE_DIR}/dsp
  ${CMAKE_CURRENT_SOURCE_DIR}/sort
  ${CMAKE_CURRENT_SOURCE_DIR}/whitelist
  ${CMAKE_CURRENT_SOURCE_DIR}/p2p_server
  ${MYSQL_INCLUDE_DIR}                       # <--- MySQL 头文件
)

# === 链接库搜索路径 ===
link_directories(
  ${CMAKE_CURRENT_SOURCE_DIR}/lib         
  /usr/aarch64-linux-gnu/lib                # 交叉环境系统库
  ${MYSQLIB_DIR}/lib                        # <--- 放有 libmysqlclient.a / libssl.so.1.1 / libcrypto.so.1.1 / libz.so.1.2.11
)

# ===  ===
file(GLOB_RECURSE ALL_SRCS
  ${CMAKE_CURRENT_SOURCE_DIR}/base/*.c
  ${CMAKE_CURRENT_SOURCE_DIR}/bms/*.c
  ${CMAKE_CURRENT_SOURCE_DIR}/dido/*.c
  ${CMAKE_CURRENT_SOURCE_DIR}/lib/*.c
  ${CMAKE_CURRENT_SOURCE_DIR}/logic/*.c
  ${CMAKE_CURRENT_SOURCE_DIR}/pcs/*.c
  ${CMAKE_CURRENT_SOURCE_DIR}/serival_device/*.c
  ${CMAKE_CURRENT_SOURCE_DIR}/tcp_server/*.c
  ${CMAKE_CURRENT_SOURCE_DIR}/cJSON/*.c
  ${CMAKE_CURRENT_SOURCE_DIR}/web_server/*.c
  ${CMAKE_CURRENT_SOURCE_DIR}/cem9000/*.c
  ${CMAKE_CURRENT_SOURCE_DIR}/dsp/*.c
  ${CMAKE_CURRENT_SOURCE_DIR}/sort/*.c
  ${CMAKE_CURRENT_SOURCE_DIR}/whitelist/*.c
  ${CMAKE_CURRENT_SOURCE_DIR}/p2p_server/*.c
)

add_executable(tems ${ALL_SRCS})

# === 关键：用 C++ 链接器，并指定库顺序 ===
# - libmysqlclient.a 静态（避免链接到 .so）
# - OpenSSL/zlib 精确到 1.1 / 1.2.11，避免误连系统的 3.x
set_target_properties(tems PROPERTIES
  LINKER_LANGUAGE CXX
  BUILD_RPATH "${CMAKE_CURRENT_SOURCE_DIR}/lib;${MYSQLIB_DIR}/lib"
  INSTALL_RPATH "\$ORIGIN/../lib;\$ORIGIN/../mysqlib/lib"
)

target_link_libraries(tems PRIVATE
  Threads::Threads
  rt
  zlog
  m
  # ---- 静态 MySQL 客户端库（等价于链接 libmysqlclient.a）----
  -Wl,-Bstatic mysqlclient
  # ---- 其余恢复为动态 ----
  -Wl,-Bdynamic
  # 精确版本以免误连 OpenSSL 3.x；这些文件位于 ${MYSQLIB_DIR}/lib
  -l:libssl.so.1.1
  -l:libcrypto.so.1.1
  -l:libz.so.1.2.11
  dl
  pthread
)


# 可选：安装规则（如需要）
# install(TARGETS tems RUNTIME DESTINATION bin)
# install(DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}/mysqlib/lib/ DESTINATION lib
#         FILES_MATCHING PATTERN "lib*.so*")
