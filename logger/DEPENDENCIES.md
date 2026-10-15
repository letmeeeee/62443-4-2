# 项目内依赖目录

移植时携带以下目录，编译使用相对项目位置查找：

| 位置 | 内容 |
| --- | --- |
| `logger/.deps/optee-arm64/include` | 设备真实的 `tee_client_api.h` |
| `logger/.deps/optee-arm64/lib` | AArch64 `libteec` 和相对路径链接 |
| `logger/.deps/openssl-arm64/include` | OpenSSL 1.1.1 AArch64 开发头文件 |
| `logger/mysqlib` | 现有 MySQL、OpenSSL 1.1、zlib 目标库及相关头文件 |
| `logger/lib` | 现有 zlog 库和项目代码 |
| `optee_ta_examples/dev_kit` | 匹配设备的 TA 构建与签名开发包 |

编译器、C/C++ 标准库及系统头文件由开发机 AArch64 工具链提供。
本方案没有把完整编译器/sysroot 打包进项目；设备运行时仍使用设备系统库。

## 首次导入 OP-TEE Client

从匹配的 EM-1000 读取真实头文件和运行库，不修改设备：

```sh
sh logger/scripts/prepare_optee_client.sh --device root@DEVICE_IP
```

离线 SDK 文件也可导入：

```sh
sh logger/scripts/prepare_optee_client.sh \
  --header /path/to/tee_client_api.h \
  --library /path/to/aarch64/libteec.so.2.0.0
```

脚本验证库架构和 SONAME、拒绝测试桩，生成相对库链接、来源记录和
SHA-256 清单；已有 SDK 不会被覆盖。更换来源时先将旧目录移走。

```sh
sh logger/scripts/prepare_optee_client.sh --check
make -C logger -j4
```

默认生成 `logger/build/tems` 与 `logger/build/modbus_tee_identity`。
OpenSSL 头文件由现有 `prepare_openssl_headers.sh` 准备，已导入后可离线复用。
打包项目时须保留 `.deps` 隐藏目录和符号链接；搬迁后新建构建目录或重新
配置 CMake，旧 `CMakeCache.txt` 中的绝对路径不适用于新位置。

例如新建构建目录：

```sh
make -C logger -j4 BUILD_DIR="$PWD/logger/build-portable"
```
