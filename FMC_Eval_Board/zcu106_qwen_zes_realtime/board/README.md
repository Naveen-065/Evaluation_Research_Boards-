# ZCU106 A53 ZES EDAC relay

This directory is the board-side boundary between the Windows AI/GUI service and the licensed ZES EDAC library. The relay performs the vendor's real 1 KiB block encode and check/repair calls on the ZCU106 processing system and exposes them over a small length-framed TCP protocol.

Important: the included vendor archive is **AArch64 Linux only**. It cannot execute on Windows or x86/x64. The Windows PC sends blocks to this relay over Ethernet; model loading, tokenization, inference orchestration, error injection, metrics, and the web GUI remain on the PC.

## Included vendor artifacts

These exact files came from `ReRAM + ZES/ZS-EDAC1-LN-03_v1.2/zesEDAC_LN_AA64_NV_v1.3.0_b01_release.zip`. Copyright and confidentiality notices are preserved.

| File | SHA-256 |
|---|---|
| `vendor/zes/zesEDAC_LN_AA64_NV_v1.3.0_b01_release.a` | `b8192785cd3466dc491b1eeaf8da8be98bc4fe0a40ff6688d248d3a675be03b4` |
| `vendor/zes/zesEdacV130.h` | `1c14e54c4a0545350b28aede434cadbf9076be2e019cc0f5d4ccf554b4129375` |

The API reports a 256-`int` data buffer and an 18-`int` parity buffer: 1024 data bytes plus 72 parity bytes. The server refuses to start if the linked library reports a different geometry.

## Build

Cross-build from Linux/WSL:

```sh
cd FMC_Eval_Board/zcu106_qwen_zes_realtime/board
./scripts/build_aarch64.sh
```

Cross-build directly from this Windows/Vitis installation:

```powershell
.\scripts\build_aarch64.ps1
```

The PowerShell script verifies the vendor hashes before compiling and runs the Vitis AArch64 `readelf` check on the result.

Or build natively on AArch64 Linux:

```sh
make CROSS_COMPILE=
```

The result is the static AArch64 Linux executable `build/zes-edac-relay`. Static linking follows the vendor guide and avoids a target glibc-version dependency. `make verify-vendor` checks the copied vendor artifacts before linking.

## Protocol-only test

The native test substitutes a clearly identified open test stub for the proprietary algorithm. It validates framing with deliberately fragmented client writes, INFO, 1 KiB encode, one-bit repair, request IDs, and malformed-length handling. It does not claim to validate the vendor correction algorithm.

```sh
make test-native
```

## Deploy from Windows

After cross-building, with SSH enabled on the ZCU106 Linux image:

```powershell
.\scripts\deploy.ps1 -Target 192.168.1.50 -User root
```

The service listens on TCP port 9106. The shipped service binds all interfaces for direct PC-to-board Ethernet use; firewall this port from other networks. The executable itself defaults to `127.0.0.1` unless `--bind` is supplied.
Each accepted client has a 30-second receive/send timeout so a stalled peer cannot hold the single-client relay indefinitely. The service runs as the unprivileged `nobody` account; use a dedicated unprivileged account instead if the target image does not provide `nobody`.

## SD boot recovery over JTAG

The ZCU106 card slot is PS SD1 through a voltage-level translator, so the
correct boot mode is `SD1_LS` (`0xE`), not SD0 (`0x3`) or ordinary SD1
(`0x5`). If SW6 remains in JTAG mode, the following one-shot override selects
SD1_LS for the current power cycle and issues a system reset:

```powershell
& 'C:\Xilinx\Vitis\2022.2\bin\xsdb.bat' .\scripts\boot_sd1_ls_once.tcl
```

This reset also resets the PL. Re-run the FPGA programming and initialization
scripts before operating the FMC board. Inspect the boot registers without
changing hardware state with:

```powershell
& 'C:\Xilinx\Vitis\2022.2\bin\xsdb.bat' .\scripts\read_boot_status.tcl
```

`SD1_PRESENT_STATE` bit 16 reports card insertion. A fatal
`CSU_BOOTROM_ERROR` ending in `0x3B` means BootROM could not read the selected
boot device; verify that the card contains a FAT32 boot partition with a valid
`BOOT.BIN`, then reseat or re-image it. For persistent SD boot, set the board's
physical boot-mode switch to the documented SD setting and power-cycle it.

See [PROTOCOL.md](PROTOCOL.md) for exact binary framing. The PC client should keep one TCP connection open and pipeline work at 1 KiB block granularity, matching the Qwen tensor-file EDAC pipeline.
