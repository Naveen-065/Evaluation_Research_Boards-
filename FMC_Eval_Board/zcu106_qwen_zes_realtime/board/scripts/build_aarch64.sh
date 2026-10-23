#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
board_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)

cd "$board_dir"
make verify-vendor

if command -v aarch64-linux-gnu-gcc >/dev/null 2>&1; then
    make CROSS_COMPILE=aarch64-linux-gnu-
elif [ "$(uname -m)" = "aarch64" ] && command -v gcc >/dev/null 2>&1; then
    make CROSS_COMPILE=
else
    printf '%s\n' \
        'No AArch64 compiler found. Install aarch64-linux-gnu-gcc in Linux/WSL,' \
        'or run this script natively on the ZCU106 A53 Linux system.' >&2
    exit 1
fi

file build/zes-edac-relay
