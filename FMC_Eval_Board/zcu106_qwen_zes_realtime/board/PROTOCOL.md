# ZES relay protocol v1

The relay uses a persistent TCP connection and network-byte-order framing. Each request and response starts with a 16-byte header:

| Offset | Bytes | Meaning |
|---:|---:|---|
| 0 | 4 | ASCII magic `ZES1` |
| 4 | 1 | protocol version, currently `1` |
| 5 | 1 | opcode; responses set bit 7 |
| 6 | 2 | flags, must be zero |
| 8 | 4 | payload length |
| 12 | 4 | caller-selected request ID |

Every response payload begins with a four-byte status code. Zero means the request was accepted. Nonzero values are defined in `include/zes_protocol.h`.

## Operations

- `INFO` (`0x01`): request payload is empty. Response body after status is `data_bytes:u32`, `parity_bytes:u32`, followed by the vendor version as UTF-8 without a terminator.
- `ENCODE` (`0x02`): request is exactly 1024 raw data bytes. Response body after status is exactly 72 opaque parity bytes.
- `CHECK_REPAIR` (`0x03`): request is `threshold:u32`, 1024 raw data bytes, then the original 72 opaque parity bytes. Response body after status is `decoder_result:u32` followed by 1024 corrected-or-unchanged data bytes. Vendor decoder results are `0` no error, `1` detected and corrected, and `2` detected but not corrected.

The parity field is opaque. Do not byte-swap its internal 32-bit words. It must be returned exactly as produced by `ENCODE` on the same AArch64 service.

This protocol has no authentication or encryption. Bind it only to the isolated FPGA Ethernet link or protect it with a firewall/VPN.
