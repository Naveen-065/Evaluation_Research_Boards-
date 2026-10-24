# ZCU106 Qwen + ZS-EDAC1 + 1 Kbit ReRAM demo

This is an isolated implementation of the supplied realtime Qwen/ZS-EDAC
design.  It does not modify the original SenseEval project.  The PC runs the
web application and local Qwen model, the ZCU106 programmable logic runs the
packet-reset-safe ReRAM scheduler, and an optional Cortex-A53 Linux relay calls
the supplied Arm64 ZS-EDAC library over the isolated Ethernet link.

## Start the web GUI

Create the host environment once (the Qwen weights remain outside Git):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Place a Transformers-compatible Qwen model at `models/Qwen3-0.6B`, or pass
`-ModelPath` below.  The verified local `model.safetensors` used here has
SHA-256 `F47F71177F32BCD101B7573EC9171E6A57F4F4D31148D38E382306F42996874B`;
model weights are intentionally excluded from Git because of their size and
licensing.

```powershell
cd FMC_Eval_Board\zcu106_qwen_zes_realtime\app
.\run.ps1
```

Open <http://127.0.0.1:8780/>.  `run.ps1` prefers the project `.venv` and the
local `models/Qwen3-0.6B` directory when the complete weight file is present.
Pass `-ModelPath` to select another local Transformers-compatible Qwen model,
or `-ZesHost <board-ip>` after the A53 Linux relay is reachable. For the
verified VirtualBox fallback, first run `board/scripts/deploy_virtualbox.ps1`,
then launch:

```powershell
.\run.ps1 -ExclusiveHardware -ZesHost 127.0.0.1 `
  -ZesTargetLabel 'Ubuntu VM · qemu-aarch64' -ZesExecutionKind vm
```

For physical program/read commands, first stop the legacy service on port 8771
and then launch `run.ps1 -ExclusiveHardware`.  Direct mode refuses to start a
job while the legacy listener exists, and it holds a cross-process hardware
lease for the full Vivado subprocess lifetime.  Without the switch, inference,
fault injection, reference EDAC, and simulation remain available but the
physical program/read buttons stay disabled.

The GUI exposes:

- realtime token streaming and an exact BER control for one live 1,024-byte
  model-tensor view;
- explicit host-reference or vendor ZS-EDAC backends, with truthful embedded
  board versus VM execution metadata and no silent substitution;
- independent check and SHA-verified repair actions;
- direct FPGA programming/read jobs for the 1 Kbit ReRAM array; and
- a compact physical 32 x 32 memory map.  Every assigned parity cell displays
  measured `0`/`1`, HRS/LRS classification, row/column, current,
  requested parity, and readback source.  Digits stay blank before a read;
  unknown, failed, and mismatched cells remain visible
  and block use of physical parity.

## Physical parity layout

The actual `ZS-EDAC1-LN-03` interface protects 1,024 bytes and produces a
72-byte (576-bit) parity record.  Parity bit `k` is stored LSB-first at physical
cell `row = k // 32`, `column = k % 32`, for cells 0 through 575.  Cells 576
through 1023 are reserved spares and are left untouched.  Automatic spare-cell
remapping is not implemented; a bad assigned cell is reported, never hidden.
The compact map therefore shows rows 0 through 17 as the 576 parity cells and
rows 18 through 31 as 448 spares.  A visible `0` or `1` is always a measured
readback classification; the requested bit is available separately and is not
painted as though it came from the array.

A physical record becomes selectable for check/repair only after a complete
non-simulated 1,024-cell read, reconstruction of all 72 bytes, and an exact
SHA-256 match to the encoded record.  Desired data and simulated data are never
labelled as hardware readback.

The map also survives an application restart.  Startup restores only the
newest saved `physical_readback.json` that contains one valid measurement for
every physical cell and has a matching parity snapshot.  It is displayed as
historical evidence but is never EDAC-usable by restoration alone.  After the
current live tensor is initialized, an identical encoded-parity SHA retains
and binds that map; a different SHA clears it and requires a new physical read.

## Components

| Folder | Purpose |
|---|---|
| `app/` | Python standard-library HTTP/SSE service, local Qwen runtime, fault injection, hardware orchestration, responsive web UI, and tests |
| `fpga/` | Copied ZCU106 baseline plus two-phase SET-then-RESET bitmap scheduler, Vivado tools, simulation, bitstream reports, and hardware Tcl |
| `caravel/` | Exact rebuildable Caravel firmware/tool snapshot and hash-pinned flash image used by the scan controller |
| `board/` | AArch64 Linux TCP relay for the exact 1,024-byte/72-byte vendor API, protocol specification, service unit, and cross-build scripts |
| `docs/` | Architecture, hardware truth boundaries, and validation gates |
| `evidence/` | Curated hardware readback inputs/results kept outside the ignored live-run directory |
| `runtime/` | Generated experiment evidence and job snapshots; ignored by Git |

The FPGA bitmap protocol adds operation 14 for loading/reading the 32 row words
and operation 15 for programming a selected range.  Each inner Caravel packet
still receives the mandatory reset/READY sequence.  A bitmap value of `1`
selects the existing SET path; `0` selects the reliable RESET path.  Operation
15 visits all selected SET targets first and all selected RESET targets second,
while result records remain keyed by row-major physical index.

## Validation

```powershell
.\scripts\check_environment.ps1
.\.venv\Scripts\python.exe -m unittest discover -s app\tests -v
node --check app\web\app.js
```

FPGA simulation and bitstream instructions are in [fpga/README.md](fpga/README.md).
Relay build/deployment and the unauthenticated isolated-link warning are in
[board/README.md](board/README.md).  The architecture and evidence requirements
are in [docs/SYSTEM_ARCHITECTURE.md](docs/SYSTEM_ARCHITECTURE.md) and
[docs/VALIDATION_PLAN.md](docs/VALIDATION_PLAN.md).

## Hardware boundary

The current Windows host reaches the PL through Vivado/JTAG/VIO. The ZCU106 SD
boot stops in BootROM, so there is still no reachable board Linux/SSH endpoint.
The same pinned AArch64 relay is deployed instead in the local Ubuntu VM through
`qemu-aarch64` binfmt, with loopback-only NAT forwarding. The GUI reports that
backend as vendor ZES with `execution_kind=vm` and `real_board=false`; it does
not claim that EDAC is executing on the ZCU106 A53.

## Current verified evidence

The following results were captured on the attached system through 2026-10-24 and
keep the PC, PL, and A53 claims separate:

| Plane | Result | Interpretation |
|---|---|---|
| PC / Qwen | Real local Qwen SSE completed with `VM EDAC FPGA demo verified.` | Confirms local model loading, generation, and streaming on the PC |
| PC / reference EDAC | A one-bit injection was detected and the repair restored the exact baseline SHA-256 | Confirms the application data path with the labelled reference codec; it is not a vendor-library result |
| ZCU106 PL / ReRAM | Two-phase bitstream `b69c7ac2eebb9b1f2afea506ea099246f906dc68c03248fb9a204d5e9791368c` is physically deployed, superseding the interleaved `541cfd...` image and the earlier `164b...` development image; safe reset hold and full initialization passed | Confirms the deployed `BMP2` protocol, SET-then-RESET implementation, HPC0/Si5351 setup, DAC/ADC startup, return clocks, and full controller startup over Vivado/JTAG/VIO; it does not prove a successfully stored parity record |
| Ubuntu VM / vendor EDAC | Pinned AArch64 relay `v1.3.0` runs through `qemu-aarch64` binfmt and a loopback-only VirtualBox forward; an exact one-bit injection returned decoder result `1` and repair restored the baseline SHA-256 | Confirms the real vendor ZES backend end to end, but truthfully reports execution kind `vm`, not ZCU106 A53 |
| ZCU106 A53 / Linux | SD boot still stops in BootROM with `CSU_BOOTROM_ERROR=0x80003B3B` | The VM substitutes only for the unavailable A53 software plane; it does not claim that Linux or EDAC is running on the board CPU |

The hash-pinned deployment receipt records the two-phase image, probes SHA-256
`d49d9992d961bab1d451e8594ee4f4a9d253aa847a6015373a647e7dbeb24e70`,
and the safe post-program state with the Caravel reset asserted and no array
pulse.  The routed image meets timing (saved report WNS `+0.525 ns`, WHS
`+0.010 ns`) with 19,944/19,944 routable nets complete, zero routing errors,
and zero DRC errors or critical warnings.  The subsequent full initialization
verified the HPC0 mux, 2 MHz Si5351/PLLA configuration, DAC and ADC startup,
all ten return-clock windows, and ended in `FULL_CONTROL_STARTUP_PASS` with the
CPU held until an operation.

The latest independent full-array read job
`e157bd40d31a4ff8a924831734c166ef` completed 1,024/1,024 physical cells but
found 313 mismatches in the 576 parity locations. Its reconstructed SHA-256
did not match the vendor-encoded parity, so the GUI retains it as physical
evidence and blocks it from check/repair. The working VM demo therefore uses
the vendor relay's host-memory encoded copy; it never substitutes the failed
physical readback silently.

Full-array read job `b3e0224dd8534231a213553bcdb9c4aa` completed all 1,024
physical cells and classified 24 as LRS and 1,000 as HRS.  This was a baseline
read taken **before** parity programming.  Among the 576 assigned parity cells,
287 differed from the requested parity record.  The reconstructed physical
parity SHA-256 therefore did not match the encoded record, and the application
correctly kept physical-parity EDAC gated.  These numbers must not be read as a
post-programming verification result.

The subsequent physical program job `e9107b27095840e28eb6b420ad803f96`
ran on the now-superseded row-major-interleaved `541cfd...` image, visited all
576 assigned cells, and recorded 53 bounded programming failures.
Independent full read `3502ff4562dc4e01a8284a3c50ebeae8` found 280 parity
mismatches; repeat read `40eff80686e94d639850b56bfd3df66a`, performed without
an intervening write, found 276 mismatches and 24 assigned-bit classification
changes.  Neither readback SHA matched the encoded 72-byte record, so the GUI
correctly continues to block physical-parity check/repair.  The complete
program/read evidence and confusion matrix are under
[`evidence/mixed_scheduler_postprogram_2026-10-23/`](evidence/mixed_scheduler_postprogram_2026-10-23/README.md).

A zero-write forward/reverse/deterministic-random diagnostic on rows 17 and 18
was also captured on the `541cfd...` image.  Only marginal cell `r17c31`
changed classification in the 64 coordinate-aligned reads; no spare-row cell
changed.  Acquisition order is therefore not the dominant cause of the failed
parity image.  See
[`evidence/read_order_probe_2026-10-23/`](evidence/read_order_probe_2026-10-23/README.md).
The deployed two-phase image has passed build, safe deployment, and full
initialization, but it has not yet produced a new full parity-program plus
independent-read result.  Physical-parity EDAC remains SHA-gated and blocked.

