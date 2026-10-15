# OP-TEE crypto client

`crypto_ta_client` is the only component that calls `libteec`. Flask invokes
this fixed CLI directly; `../script/crypto_ta.sh` is intended for manual
installation diagnostics and is not in the HTTP request path.

The client uses TA UUID `5319e0a0-0001-4e2a-9c01-0c34da100001` and the
project command IDs 0 through 7. Command 7 requires the matching updated TA;
the previously deployed TA supports only IDs 0 through 6. The client passes
original message bytes to RSA operations;
SHA-256 is performed inside the TA.

## Build and install

Target dependencies are shared with tems under `logger/.deps/optee-arm64`.
Import them once from the matching device, then build without external SDK
paths (run from the repository root):

```sh
sh logger/scripts/prepare_optee_client.sh --device root@DEVICE_IP
cmake -S exec/app/tee -B exec/app/tee/build \
  -DCMAKE_TOOLCHAIN_FILE="$PWD/exec/app/tee/cmake/aarch64-linux-gnu.cmake"
cmake --build exec/app/tee/build
```

Transfer `logger/.deps` with the project when migrating to another build
machine. Check imported files with
`sh logger/scripts/prepare_optee_client.sh --check`. The compiler and standard
C runtime sysroot are provided by the build machine's AArch64 toolchain.

Do not assume the production image contains a compiler. Prefer building in its
cross-compilation SDK, with the target OP-TEE Client headers and `libteec`:

### CMake (recommended for this repository)

```sh
cmake -S exec/app/tee -B /tmp/build-crypto-ta \
  -DCMAKE_TOOLCHAIN_FILE=exec/app/tee/cmake/aarch64-linux-gnu.cmake \
  -DCMAKE_SYSROOT=/path/to/target/sysroot \
  -DOPTEE_CLIENT_INCLUDE_DIR=/path/to/optee_client/include \
  -DOPTEE_CLIENT_LIBRARY=/path/to/aarch64/libteec.so
cmake --build /tmp/build-crypto-ta
cmake --install /tmp/build-crypto-ta --prefix /path/to/rootfs
```

`OPTEE_CLIENT_LIBRARY` must be an AArch64 library. Confirm both artifacts before
deployment:

```sh
file /tmp/build-crypto-ta/crypto_ta_client
file /path/to/aarch64/libteec.so
```

### Make

```sh
make CROSS_COMPILE=aarch64-linux-gnu- \
  SYSROOT=/path/to/target/sysroot \
  CPPFLAGS="-I/path/to/optee_client/include"
make DESTDIR=/path/to/rootfs install
```

If the target intentionally contains a native GCC toolchain and the OP-TEE
Client development files, a native build is simply `make CC=gcc`. The Makefile
uses an explicit `CC` when supplied; otherwise it selects
`${CROSS_COMPILE}gcc` or `gcc` instead of GNU Make's built-in `cc` default.

If the compiler reports `tee_client_api.h` missing, add its directory to
`CPPFLAGS`. If linking reports `cannot find -lteec`, add the target library
directory to `LDFLAGS`, for example `LDFLAGS="-L/path/to/optee_client/lib"`.
Never link the host machine's `libteec` into a target-architecture binary.

The deployed files are:

- `/home/zlg/app/bin/crypto_ta_client`
- `/home/zlg/app/scripts/crypto_ta.sh`
- `/lib/optee_armtz/5319e0a0-0001-4e2a-9c01-0c34da100001.ta` (provided by the
  OP-TEE build, not installed by this Makefile)

The updated TA can be built separately without overwriting repository output:

```sh
make -C optee_ta_examples/ta/crypto_ta \
  O=/tmp/build-crypto-ta-rotate-ta \
  TA_DEV_KIT_DIR="$PWD/optee_ta_examples/dev_kit" \
  CROSS_COMPILE=aarch64-linux-gnu-
```

Deploy the matching TA and CLI together during a maintenance window, then
restart the Flask service so it invokes the new CLI. The TA file on this
device is under `/lib/optee_armtz/`. Back up the installed TA file before
replacing it; this backs up only the TA binary, not the persistent RSA key.
Check `gen-rsa` and `public-key` before intentionally invoking `rotate-rsa`.
The new command is irreversible through this ABI. Direct persistent-object
overwrite has no application-level rollback if storage or power fails during
the write; arrange recovery and certificate replacement before rotating.

Set `CRYPTO_TA_CLIENT` for Flask when the client is installed elsewhere.
The diagnostic script additionally accepts `CRYPTO_TA_CLIENT_BIN` and
`CRYPTO_TA_FILE`.

## HTTP API

All endpoints require an authenticated permission-level 4 user. Binary fields
use standard Base64. Message size is limited to 1 MiB.

| Endpoint | Body / result |
| --- | --- |
| `POST /api/cert/tee/keys` | `{"type":"aes|rsa|all"}`; create or reuse, never rotate |
| `POST /api/cert/tee/rotate-rsa` | `{"confirm":"ROTATE_RSA_KEY"}`; replaces the persistent RSA keypair |
| `GET /api/cert/tee/public-key` | RSA modulus and exponent, unsigned big-endian Base64 |
| `POST /api/cert/tee/cmac` | Base64 `message`; returns 16-byte Base64 `mac` |
| `POST /api/cert/tee/sign` | Base64 `message`; returns 384-byte Base64 `signature` |
| `POST /api/cert/tee/verify-cmac` | Base64 `message` and 16-byte `mac`; returns `valid` |
| `POST /api/cert/tee/verify-signature` | Base64 `message` and 384-byte `signature`; returns `valid` |

RSA rotation invalidates certificates and trust entries tied to the previous
public key. Renew and redistribute those certificates before using the new
key for TLS. Certificate files and trust chains remain managed by
`modbus_certs.py`; this TA ABI has no certificate, key import, private-key
export, deletion, or encryption commands. TA public login does not provide
authorization by itself: restrict access to the CLI and TA through device
policy, and expose the HTTP operation only to authenticated administrators.
