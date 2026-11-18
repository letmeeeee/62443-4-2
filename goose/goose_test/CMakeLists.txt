cmake_minimum_required(VERSION 3.10)

# ======== 可选开关：是否启用交叉编译 ========
option(USE_CROSS "Use aarch64 cross compiler" ON)

# ======== 交叉编译配置（必须在 project() 之前）========
if(USE_CROSS)
    message(STATUS ">>> Using AArch64 cross compiler")

    set(CMAKE_SYSTEM_NAME Linux)
    set(CMAKE_SYSTEM_PROCESSOR aarch64)

    set(CMAKE_C_COMPILER   aarch64-linux-gnu-gcc)
    set(CMAKE_CXX_COMPILER aarch64-linux-gnu-g++)
    set(CMAKE_AR           aarch64-linux-gnu-ar)
    set(CMAKE_RANLIB       aarch64-linux-gnu-ranlib)

    # 查找策略（避免误用主机库）
    set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
    set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
    set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
    set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
endif()

# ======== 工程定义 ========
project(goose_demo C)

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)

# ======== libiec61850 路径配置 ========
set(LIBIEC_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../libiec61850" CACHE PATH "libiec61850 source directory")
set(LIBIEC_BUILD "${LIBIEC_ROOT}/build" CACHE PATH "libiec61850 build directory")
set(LIBIEC_A "${LIBIEC_BUILD}/src/libiec61850.a")

# ======== 自动查找 HAL 静态库 ========
find_library(HAL_LIB
  NAMES hal iec61850_hal
  PATHS "${LIBIEC_BUILD}/hal" "${LIBIEC_BUILD}"
  NO_DEFAULT_PATH
)

# ======== 基本检查 ========
if(NOT EXISTS "${LIBIEC_A}")
    message(FATAL_ERROR "❌ 未找到 ${LIBIEC_A}，请确认 libiec61850 已编译")
endif()

if(NOT HAL_LIB)
    message(FATAL_ERROR "❌ 未找到 HAL 静态库（libhal.a 或 libiec61850_hal.a）")
endif()

# ======== 打印关键信息（调试用）========
message(STATUS "----------------------------------")
message(STATUS "CMAKE_C_COMPILER = ${CMAKE_C_COMPILER}")
message(STATUS "LIBIEC_A         = ${LIBIEC_A}")
message(STATUS "HAL_LIB          = ${HAL_LIB}")
message(STATUS "USE_CROSS        = ${USE_CROSS}")
message(STATUS "----------------------------------")

# ======== 头文件路径 ========
include_directories(
  "${LIBIEC_ROOT}/src"
  "${LIBIEC_ROOT}/src/iec61850/inc"
  "${LIBIEC_ROOT}/src/common/inc"
  "${LIBIEC_ROOT}/src/goose"
  "${LIBIEC_ROOT}/src/mms/inc"
  "${LIBIEC_ROOT}/src/mms/iso_mms"
  "${LIBIEC_ROOT}/src/mms/iso_mms/asn1c"
  "${LIBIEC_ROOT}/src/logging"
  "${LIBIEC_ROOT}/hal/inc"
  "${LIBIEC_ROOT}/src/r_session"
)

# ======== 导入 libiec61850 静态库 ========
add_library(iec61850 STATIC IMPORTED GLOBAL)
set_target_properties(iec61850 PROPERTIES
  IMPORTED_LOCATION "${LIBIEC_A}"
)

# ======== 可执行程序 ========
add_executable(goose_pub       pub.c)
add_executable(goose_sub       sub.c)
add_executable(goose_multi_pub goose_multi_pub.c)
add_executable(goose_multi_sub goose_multi_sub.c)
find_package(OpenSSL 1.1.1 REQUIRED COMPONENTS Crypto)
add_executable(goose_middle middle.c security/goose_security.c
    security/goose_transport.c security/goose_log.c)
target_compile_options(goose_middle PRIVATE -Wall -Wextra)
# Do not embed this workstation's cross-SDK library directory in deployed ELF.
set_target_properties(goose_middle PROPERTIES SKIP_BUILD_RPATH TRUE)
target_link_libraries(goose_middle PRIVATE OpenSSL::Crypto)
# ======== 链接库（顺序很重要）========
target_link_libraries(goose_pub       PRIVATE iec61850 "${HAL_LIB}" pthread rt)
target_link_libraries(goose_sub       PRIVATE iec61850 "${HAL_LIB}" pthread rt)
target_link_libraries(goose_multi_pub PRIVATE iec61850 "${HAL_LIB}" pthread rt)
target_link_libraries(goose_multi_sub PRIVATE iec61850 "${HAL_LIB}" pthread rt)
target_link_libraries(goose_middle PRIVATE iec61850 "${HAL_LIB}" pthread rt)
