#!/usr/bin/env python3
"""Map one 72-byte ZS-EDAC parity record into the physical 32x32 bitmap."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


PARITY_BYTES = 72
PARITY_BITS = PARITY_BYTES * 8
ARRAY_BITS = 32 * 32


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Pack the 576 opaque ZS parity bits into physical cells 0..575; "
            "remaining cells receive a deterministic HRS/LRS fill state."
        )
    )
    parser.add_argument("parity_bin", type=Path, help="exact 72-byte ZS parity buffer")
    parser.add_argument("bitmap_hex", type=Path, help="32-word bitmap output")
    parser.add_argument(
        "--bit-order",
        choices=("lsb0", "msb0"),
        default="lsb0",
        help="bit numbering within each opaque parity byte (default: lsb0)",
    )
    parser.add_argument(
        "--unused-state",
        choices=("hrs", "lrs"),
        default="hrs",
        help="state for physical cells 576..1023 (default: hrs)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    parity = args.parity_bin.read_bytes()
    if len(parity) != PARITY_BYTES:
        raise SystemExit(
            f"expected exactly {PARITY_BYTES} parity bytes, got {len(parity)}"
        )

    fill = 1 if args.unused_state == "lrs" else 0
    bits = [fill] * ARRAY_BITS
    for bit_index in range(PARITY_BITS):
        byte = parity[bit_index // 8]
        bit_in_byte = bit_index % 8
        shift = bit_in_byte if args.bit_order == "lsb0" else 7 - bit_in_byte
        bits[bit_index] = (byte >> shift) & 1

    words = []
    for word_index in range(32):
        value = sum(bits[word_index * 32 + bit] << bit for bit in range(32))
        words.append(value)

    args.bitmap_hex.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(f"{word:08x}\n" for word in words)
    args.bitmap_hex.write_text(text, encoding="ascii", newline="\n")

    heatmap_path = args.bitmap_hex.with_suffix(args.bitmap_hex.suffix + ".cells.csv")
    with heatmap_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("physical_index", "row", "column", "requested_bit", "requested_state", "source"))
        for physical_index, bit in enumerate(bits):
            writer.writerow(
                (
                    physical_index,
                    physical_index >> 5,
                    physical_index & 31,
                    bit,
                    "LRS_SET" if bit else "HRS_RESET",
                    "zs_parity" if physical_index < PARITY_BITS else "unused_fill",
                )
            )

    bitmap_bytes = b"".join(word.to_bytes(4, "little") for word in words)
    manifest = {
        "protocol": "ZCU106_BITMAP_V1",
        "parity_source": str(args.parity_bin.resolve()),
        "parity_source_sha256": sha256(parity),
        "parity_bytes": PARITY_BYTES,
        "parity_bits": PARITY_BITS,
        "bit_order": args.bit_order,
        "physical_mapping": "parity bit i -> row=i//32, column=i%32",
        "unused_cells": [PARITY_BITS, ARRAY_BITS - 1],
        "unused_state": args.unused_state.upper(),
        "bitmap_binary_little_endian_sha256": sha256(bitmap_bytes),
        "bitmap_text_sha256": sha256(text.encode("ascii")),
        "lrs_targets": sum(bits),
        "hrs_targets": ARRAY_BITS - sum(bits),
        "bitmap_file": str(args.bitmap_hex.resolve()),
        "heatmap_file": str(heatmap_path.resolve()),
    }
    manifest_path = args.bitmap_hex.with_suffix(args.bitmap_hex.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(
        f"packed {PARITY_BITS} parity bits into 1024 physical cells; "
        f"LRS={manifest['lrs_targets']} HRS={manifest['hrs_targets']}"
    )
    print(f"bitmap={args.bitmap_hex}")
    print(f"manifest={manifest_path}")
    print(f"heatmap={heatmap_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
