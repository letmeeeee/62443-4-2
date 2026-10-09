#!/bin/sh
set -eu

CLIENT=${CRYPTO_TA_CLIENT_BIN:-/home/zlg/app/bin/crypto_ta_client}
TA_FILE=${CRYPTO_TA_FILE:-/lib/optee_armtz/5319e0a0-0001-4e2a-9c01-0c34da100001.ta}

if [ "$#" -ne 1 ]; then
    echo "usage: $0 gen-aes|gen-rsa|rotate-rsa|cmac|sign|verify-cmac|verify-rsa|public-key" >&2
    exit 2
fi

case "$1" in
    gen-aes|gen-rsa|rotate-rsa|cmac|sign|verify-cmac|verify-rsa|public-key)
        operation=$1
        ;;
    *)
        echo "unsupported TEE operation" >&2
        exit 2
        ;;
esac

if [ ! -x "$CLIENT" ]; then
    echo "crypto TA client is not installed or executable: $CLIENT" >&2
    exit 1
fi

if [ ! -f "$TA_FILE" ]; then
    echo "crypto TA is not installed: $TA_FILE" >&2
    exit 1
fi

exec "$CLIENT" "$operation"
