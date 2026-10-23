# Qwen + ZS-EDAC + X1 ReRAM architecture

## Scope and implementation boundary

This project implements the supplied design as three independently testable
planes.  Keeping the planes separate is important because the existing ZCU106
image is a PL-only JTAG/VIO design; it does not currently expose the ReRAM
scheduler to Cortex-A53 Linux over AXI.

1. **PC control plane** — web UI, token streaming, Qwen runtime, live-tensor
   fault injection, hashes, experiment log, and asynchronous job control.
2. **ZCU106 processing-system plane** — the Arm64 relay that calls the supplied
   ZS-EDAC static library on Cortex-A53 Linux.
3. **ZCU106 programmable-logic plane** — the existing packet-reset-safe 1 Kbit
   Caravel/ReRAM scheduler, extended with a 1,024-bit mixed SET/RESET bitmap.

The browser communicates with the PC service.  The PC can call the Arm64 relay
over Ethernet for real ZS encoding/correction and controls the PL scheduler over
the proven local Vivado/JTAG/VIO route.  The two board paths are deliberately
not presented as one path until a future PS-to-PL AXI bridge is implemented and
measured.

Direct Vivado access is an explicit standalone mode.  The application requires
the legacy service on port 8771 to be closed, requires the operator's
`-ExclusiveHardware` launch switch, and holds a process-wide file lease while a
direct tool runs.  It fails closed when the legacy listener is still present;
an idle snapshot is not treated as durable ownership.

## Corrected protection geometry

The executable `ZS-EDAC1-LN-03` API, rather than the illustrative numbers in
the design PDF, defines the deployed geometry:

| Item | Actual value |
|---|---:|
| Protected data block | 1,024 bytes / 8,192 bits |
| ZS parity record | 72 bytes / 576 bits |
| X1 physical array | 32 x 32 = 1,024 cells |
| Unallocated cells after one parity record | 448 cells |

The GUI's error percentage means bit error rate within the selected 8,192-bit
live model window.  It reports both the requested percentage and the exact
integer number of distinct bits flipped.  Faults are injected between inference
requests; a live tensor is never patched while a compute kernel is using it.

## Physical parity mapping

Physical cell index is row-major:

```text
physical_index = row * 32 + column
row             = physical_index // 32
column          = physical_index % 32
```

Logical parity bits map directly to cells 0 through 575.  Cells 576 through
1023 are reserved spares.  This implementation does not silently remap a failed
cell: a failed, unknown, or mismatched assigned cell makes the physical parity
record unusable for EDAC.  The readback job records the protected-block and
parity SHA-256 values, physical coordinates, failed-cell labels, measured state,
and scheduler/bitstream evidence.  A readback is not valid for another
protected block or another parity record.  Spare-cell remapping is a future
extension and must not be inferred from the reserved cells shown in the GUI.

The 72-byte vendor record is treated as opaque and is never word-swapped.
Logical bit `k` is `(parity[k // 8] >> (k % 8)) & 1`; this same byte/bit order
is used when reconstructing the record from measured physical cells.

The UI heatmap is always a **physical** 32 x 32 view:

- `1 / LRS`: verified SET state;
- `0 / HRS`: verified RESET state;
- `spare`: not assigned to the current parity record;
- `failed`: a known or newly failed physical cell; no replacement is implied;
- `mismatch/unknown`: requested and measured state disagree, or no valid read.

Mock mode is separately labelled and never turns desired data into a claimed
hardware readback.  Rows 0 through 17 contain the 576 assigned parity cells;
rows 18 through 31 contain the 448 reserved spares.  The compact map leaves its
digits blank until a readback exists, then displays measured `0`/`1` values.
Requested bits remain separate metadata, so a target pattern cannot be mistaken
for an observed array state.

At process startup, the service scans saved bitmap jobs newest-first and
restores only a complete `physical_readback.json` with 1,024 unique row-major
coordinates and a valid matching 72-byte parity snapshot.  The restored map is
historical display evidence: its measured parity is deliberately not attached
to the current live tensor and `usable_for_check_repair` remains false.  A
later protection initialization retains and binds it only when the new encoded
parity SHA exactly matches the saved identity; any different SHA invalidates
the map.  Thus persistence fixes disappearing GUI history without weakening
the live-tensor/SHA trust boundary.

## Transaction flow

### Protect

1. Select a contiguous 1,024-byte view of a live Qwen parameter tensor.
2. Synchronize the model runtime and capture the baseline bytes and SHA-256.
3. Ask the A53 ZS relay to encode a 72-byte parity record.
4. Load the 1,024 desired physical states into the FPGA bitmap RAM.
5. Start the two-phase mixed-state scheduler.  It chooses SET for a `1` and reliable
   RESET for a `0`; every inner Caravel scan packet still receives its mandatory
   reset/READY sequence.
6. Page the measured per-cell results and verify every assigned parity bit.
   Any mismatch, failed cell, or unknown state blocks use of physical parity;
   save the evidence without claiming repair or remapping.

### Inject, check, and repair

1. Choose distinct live-window bit positions from the requested BER and seed.
2. Patch the live tensor between inference requests and record positions/hashes.
3. Read parity from the mapped physical cells rather than reusing desired bits.
4. Send the current 1 KiB block and read parity to the A53 ZS relay.
5. For `check`, report the vendor status without replacing model data.
6. For `repair`, write corrected bytes back to the live tensor, synchronize, and
   require the SHA-256 to match the protected baseline before declaring success.

Vendor return values are retained exactly: `0 = no detectable error`,
`1 = detected and corrected`, and `2 = detected but uncorrectable`.  The UI does
not infer a stronger correction guarantee from these values.

## Realtime behavior

Token delivery uses Server-Sent Events and remains interactive while a ReRAM
job runs in the background.  Physical array programming is not placed in the
per-token path: the latest measured full RESET took approximately 347 seconds
for 1,024 cells.  The honest realtime claim is therefore realtime UI/token
streaming plus asynchronous hardware protection, not a sub-second full-array
rewrite.

## Backend truth labels

Every result includes independent labels for:

- model: `qwen` or `demo`;
- EDAC: `zes-aarch64` or `reference-mock`;
- parity memory: `zcu106-x1` or `memory-mock`;
- hardware readback: `measured`, `desired-only`, or `unavailable`.

Only the first value in each pair supports a production hardware claim.  A
mixed configuration is useful for integration, but its status remains visible
in the GUI and event log.

## Current integration evidence (2026-10-23)

The two-phase SET-then-RESET image is now physically deployed, superseding the
row-major-interleaved `541cfd...` image and the earlier `164b...` development
image.  Its bitstream SHA-256 is
`b69c7ac2eebb9b1f2afea506ea099246f906dc68c03248fb9a204d5e9791368c`;
the matching probes SHA-256 is
`d49d9992d961bab1d451e8594ee4f4a9d253aa847a6015373a647e7dbeb24e70`.
Implementation met setup and hold timing and completed all 19,944 routable
nets with zero routing errors and no DRC errors or critical warnings.
Deployment verified the expected `BMP2` protocol identity and the corrected
digital reset-hold path while the ADC/DAC interlocks were disabled; the receipt
records the safe state as Caravel reset asserted with no array pulse.  The
subsequent full initialization verified HPC0 mux selection, the 2 MHz
Si5351/PLLA configuration, DAC and ADC startup, all ten return-clock windows,
and `FULL_CONTROL_STARTUP_PASS` with the CPU held until an operation.  These
checks establish the deployed controller and operation order, not successful
physical parity programming.

Full 1,024-cell read job `b3e0224dd8534231a213553bcdb9c4aa`
completed with 24 LRS classifications and 1,000 HRS classifications.  The read
was intentionally taken before parity programming.  Of the 576 parity-assigned
cells, 287 did not match the requested record, so reconstruction produced a
different parity SHA-256 and physical EDAC remained gated.  The result is a
measured initial-state baseline, not a programmed-array accuracy result; no
post-program parity outcome is inferred from the corrected-image deployment.

The later mixed-scheduler program job
`e9107b27095840e28eb6b420ad803f96` ran on the now-superseded interleaved
`541cfd...` image, visited all 576 assigned cells, and recorded 53 bounded
failures. Independent full read job
`3502ff4562dc4e01a8284a3c50ebeae8` reconstructed 280 mismatched parity bits,
and no-write repeat read `40eff80686e94d639850b56bfd3df66a` reconstructed 276
mismatches with 24 assigned-bit classification changes. Both physical parity
SHA-256 values differed from the encoded record. The application therefore
keeps physical check/repair disabled; these runs are diagnostic evidence, not
a successful physical-parity claim.

A zero-write forward/reverse/deterministic-random diagnostic on physical rows
17 and 18 was also captured on the `541cfd...` image. Only the marginal
assigned cell at `r17c31` crossed the fixed current separator; the other 63
coordinate-aligned classifications, including every tested spare cell, were
stable. This rules out acquisition order as the dominant cause and points to
cell/programming or half-select disturbance. No full parity program plus
independent read has yet been performed with the deployed two-phase image, so
physical EDAC remains blocked by the exact-SHA gate.

On the PC, the real local Qwen runtime streamed `Hardware ready.` through SSE.
A separate one-bit test using the explicitly labelled reference codec reported
the fault as detected and restored the exact protected-block SHA-256 after
repair.  That test validates the PC integration path but does not exercise the
proprietary ZS-EDAC implementation.

The A53 relay has been cross-built for Linux/AArch64, but it has not been
runtime-deployed because this host has no reachable ZCU106 Linux/SSH IP.  Until
that endpoint exists and the real vendor tests pass, the supported measured
path is PC-to-PL over Vivado/JTAG/VIO and the GUI must retain its offline A53
label.

