# testta — OP-TEE 示例 TA 工程

一个 TA（`ta/crypto_ta`）+ 一个测试客户端（`host/crypto_test_ta`），演示 AES-128 CMAC 与 RSA-3072 PSS 的密钥生成、数据校验与公钥导出。TA 由 OP-TEE
dev kit 用 `keys/default.pem` 自动签名，与当前 prebuilt bl32 配套，开箱即跑。

## 内容

| TA | CA | 演示 |
|---|---|---|
| `ta/crypto_ta` | `host/crypto_test_ta` | AES-128 CMAC + RSA-3072 PSS：生成持久密钥/密钥对、导出公钥、算/验 CMAC、签/验签名 |

`crypto_ta` 对外提供 8 个命令（见 `ta/crypto_ta/include/crypto_ta.h`）：
`CRYPTO_GEN_AES_128_KEY`、`CRYPTO_GEN_RSA_3072_KEY`、`CRYPTO_MAC_AES_128_KEY`、
`CRYPTO_MAC_RSA_3072_KEY`（RSA 实为 PSS 签名）、`CRYPTO_VERIFY_AES_128_KEY`、
`CRYPTO_VERIFY_RSA_3072_KEY`、`CRYPTO_GET_RSA_3072_PUB_KEY`（导出 RSA 公钥 n、e）、
`CRYPTO_ROTATE_RSA_3072_KEY`（显式生成新 RSA 密钥对并覆盖旧对象）。

轮换命令 ID 7 需要同时部署更新后的 TA 和 CA。原命令 ID 1 保持幂等。
轮换会使旧证书与新私钥不匹配，应先安排证书重新签发、信任方更新和服务重启。
当前采用 `TEE_DATA_FLAG_OVERWRITE` 直接覆盖持久对象；如果写入期间掉电，
本例没有应用层回滚机制。仅在维护窗口显式调用，勿将轮换加入常规启动流程。
此 TA 使用公开会话，设备侧还需限制谁可以调用轮换命令。

## 前置条件

1. OP-TEE TA dev kit：已随工程内置在 `dev_kit/`（含 `mk/`、`lib/`、
   `keys/default.pem` 等，平台 `em1000`），为默认值；可用
   `TA_DEV_KIT_DIR=/path/to/export-ta_arm64 make ...` 覆盖。
2. aarch64 交叉工具链：容器内为 `aarch64-linux-gnu-`（Debian
   `gcc-aarch64-linux-gnu`）；若有 BSP Yocto SDK 则为 `aarch64-oe-linux-`。
3. host client 需要 optee_client 的 `tee_client_api.h` + `libteec`：Debian
   trixie 装 `optee-client-dev:arm64`（提供头与 arm64 `libteec.so`），或从
   [optee_client](https://github.com/OP-TEE/optee_client) 源码编。

## 编译

推荐用容器一键编译（镜像内已备齐交叉工具链、TA 签名依赖与 arm64 libteec，
并设好 `CROSS_COMPILE`/`LIBTEEC_LIB`；默认用工程内置的 `dev_kit/`）：

```
./containers/build-container.sh            # 构建 optee-builder:latest
./containers/run-container.sh -- make      # 容器内编译全部 TA + CA
```

默认 `TA_DEV_KIT_DIR` 指向 `$(CURDIR)/dev_kit`，`make` 无需额外参数。改用特定
dev kit：`./containers/run-container.sh -- make TA_DEV_KIT_DIR=/path/to/export-ta_arm64`
（容器内 BSP 的 dev kit 只读挂在 `/u-boot-zlg/build/optee-os/em1000/export-ta_arm64`，
可直接覆盖指向）。`make tas` / `make cas` 分别只编 TA / CA。裸 `make`（不在容器内）
需自行备好工具链与 arm64 libteec。

## 安装到板子

```
make install DESTDIR=/mnt/rootfs     # 一次性装 .ta + CA
# 或手动：
#   ta/*/*.ta           -> /usr/lib/optee_armtz/
#   host/crypto_test_ta -> /usr/bin/
```

## 运行（板上，需 tee-supplicant 在跑以支持持久存储）

```
crypto_test_ta
```

预期输出：
```
[PASS] aes-gen: generate/persist AES-128 key
[PASS] aes-mac: compute AES-128 CMAC tag
[PASS] aes-verify-good: verify correct CMAC tag
[PASS] aes-verify-tampered: verify tampered CMAC tag
[PASS] rsa-gen: generate/persist RSA-3072 keypair
[PASS] rsa-pubkey: export RSA-3072 public key (n,e)
[PASS] rsa-sign: compute RSA-3072 PSS signature
[PASS] rsa-verify-good: verify correct RSA signature
[PASS] rsa-verify-tampered: verify tampered RSA signature

9 passed, 0 failed
```

## 配置

- **存储后端**：`common.h` 的 `TESTTA_STORAGE_ID`。默认 `0x1`
  （`TEE_STORAGE_PRIVATE`，平台默认；`CFG_RPMB_FS=n` → REE FS，`CFG_RPMB_FS=y`
  → RPMB）。强制 RPMB 改 `0x80000100`（`TEE_STORAGE_PRIVATE_RPMB`，需 RPMB 已就绪）。
- **持久密钥 obj_id**：`common.h` 中 `aes128_key` / `rsa3072_kp`。跨会话复用。
  重置：删 REE FS 下 `/data/tee/*` 对应文件，或换 obj_id。

## 实现要点

- **持久密钥对象**：`AllocateTransientObject` → `GenerateKey` →
  `CreatePersistentObject(attrs=transient)` 落盘；使用时 `OpenPersistentObject` +
  `CopyObjectAttributes1` 拷到瞬态再 `SetCryptoKey`。
- **非对称签名**：optee 4.x 只提供 `TEE_AsymmetricSignDigest/VerifyDigest`（对摘要
  签/验），故先 `TEE_DigestDoFinal`（SHA-256）算摘要。verify 接受 KEYPAIR 或
  PUBLIC_KEY（`tee_svc_cryp.c:2680-2683`），本示例直接用持久 keypair。
- **对称 MAC**：`TEE_MACComputeFinal`（算）/`TEE_MACCompareFinal`（验），one-shot，
  前置 `TEE_MACInit`。
- **导出公钥**：`CRYPTO_GET_RSA_3072_PUB_KEY` 用 `TEE_GetObjectBufferAttribute` 直接
  从持久 keypair 读模数 n 与公钥指数 e（PUBLIC 属性，无需拷瞬态）。

## 备注

- 不修改 optee 树任何现有文件，仅在 `testta/` 下新建。
- 设计文档：`docs/superpowers/specs/2026-06-25-testta-example-tas-design.md`。
