# Build verification

Built on 2026-10-23 with:

`C:\Xilinx\Vitis\2022.2\gnu\aarch64\nt\aarch64-linux\bin\aarch64-linux-gnu-gcc.exe`

Artifact: `build/zes-edac-relay`

- Size: 679,040 bytes
- SHA-256: `ddd47de47769900df0cac2025da546231df5047e81c3325ae04335953089f1c0`
- Format: ELF64, little-endian, machine `AArch64`
- Linkage: static; no dynamic section
- Minimum ABI reported by `file`: GNU/Linux 3.14.0
- Vendor functions linked into the executable: `encodeAllRowColPariBits`, `decodeAndCorrectData`, `intDataBufferSize`, `intParityBufferSize`, and `getVersion`

The executable was cross-linked and structurally verified on Windows. It cannot execute on Windows and still requires a runtime smoke test on the ZCU106 A53 Linux image.
This build includes a 30-second receive/send timeout for each accepted client.
