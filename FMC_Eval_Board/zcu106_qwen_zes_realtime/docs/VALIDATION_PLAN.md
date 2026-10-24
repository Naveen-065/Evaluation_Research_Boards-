# Validation plan and evidence gates

No layer may be labelled `real` in the GUI until its corresponding gate passes.

## PC application

- Unit-test BER rounding, unique deterministic bit positions, bit ordering,
  1 KiB bounds, and SHA transitions.
- Unit-test the mock codec with zero, one, and multiple bit faults; keep its
  result labelled `reference-mock`.
- Exercise every HTTP endpoint with same-origin checks and malformed input.
- Verify that SSE events reconstruct the exact final response and terminate.
- Verify that hardware work is asynchronous and cannot stall token events.
- Render the GUI at a laptop viewport and inspect the 32 x 32 map, legend,
  progress, error states, long prompt, and long model output.
- Restart the service with a saved complete 1,024-cell read and verify that the
  map returns only as historical evidence.  Require an identical current
  encoded-parity SHA before it becomes EDAC-usable, and require a differing SHA
  to invalidate it.

## A53 ZS relay

- Verify the copied library/header SHA-256 values before every link.
- Cross-compile an AArch64 Linux executable with the installed Vitis toolchain.
- Inspect the ELF machine type and linked symbols.
- Run the protocol test with the open native stub where a POSIX host compiler is
  available; this validates framing only.
- On ZCU106 Linux, call `INFO` and require 1,024 data bytes and 72 parity bytes.
- Test zero-error, vendor-correctable, and vendor-uncorrectable cases with saved
  hashes.  Do not infer the correction envelope from the stub.

## FPGA bitmap scheduler

- Simulate all 32 bitmap load words, incomplete-map rejection, mixed `0/1`
  selection, full 1,024-cell completion, abort, and result paging.
- Assert a fresh bounded Caravel reset/READY transaction for every inner packet.
- Synthesize, place, and route for `xczu7ev-ffvc1156-2-e`.
- Require no error/critical-warning DRCs, nonnegative setup and hold slack, and
  zero unrouted nets before producing `.bit`/`.ltx`.
- Record SHA-256 for RTL, Tcl, constraints, bitstream, probes, and routed DCP.

## Integrated hardware

1. Confirm J5/HPC0, VADJ near 1.8 V, Si5351 lock, ADC health, and DAC-safe idle.
2. Program the new bitstream, then run a read-only controller check.
3. Encode a known 1 KiB block with the real ZS relay.
4. Program only its 576 parity bits with the bitmap scheduler; leave physical
   cells 576 through 1023 untouched as reserved spares.
5. Page every cell result and create the physical readback evidence.  Physical
   EDAC remains blocked if any of cells 0 through 575 is failed, unknown, or
   mismatched; automatic spare remapping is not implemented.
6. Perform a separate full read, reconstruct all 72 parity bytes from measured
   cells, and require parity SHA-256 equality.
7. Inject a known error into the live Qwen tensor between requests, run `check`,
   run `repair`, and require restored model-block SHA-256.
8. Compare clean, corrupted (guarded), and repaired inference/logit evidence.
9. Power-cycle retention is a separate experiment; do not regenerate parity
   before its post-cycle read.

## Evidence recorded on 2026-10-23

- **PC / real Qwen:** a local Qwen inference completed over SSE with output
  `Hardware ready.`
- **PC / reference EDAC:** a deliberate one-bit fault was detected and repair
  restored the exact protected-block SHA-256.  This passes the reference path,
  not the A53 vendor-library gate.
- **PL build/deployment:** two-phase SET-then-RESET bitstream
  `b69c7ac2eebb9b1f2afea506ea099246f906dc68c03248fb9a204d5e9791368c`
  is physically deployed and supersedes the interleaved `541cfd...` image and
  the earlier `164b...` development image.  Its hash-pinned deployment passed
  the `BMP2` identity and safe digital reset-hold checks with no array pulse.
  The saved implementation report has WNS `+0.525 ns`, WHS `+0.010 ns`, zero
  routing errors, and zero DRC errors or critical warnings.
- **Full initialization:** the deployed two-phase image passed HPC0 mux and
  2 MHz Si5351/PLLA checks, DAC and ADC startup, all ten return-clock windows,
  and `FULL_CONTROL_STARTUP_PASS`; the CPU remained held until an operation.
- **Prior physical smoke read:** row 0, column 0 returned a real measured
  result before the corrected-image deployment.
- **Full baseline read:** job `b3e0224dd8534231a213553bcdb9c4aa`
  completed all 1,024 cells with 24 LRS and 1,000 HRS classifications.  The
  compact 32 x 32 map exposes measured digits only after readback; its first 18
  rows are the 576 parity cells and its final 14 rows are the 448 spares.
- **Interleaved-image physical parity trial:** program job
  `e9107b27095840e28eb6b420ad803f96` ran on the now-superseded `541cfd...`
  image, visited all 576 assigned cells, and recorded 53 bounded programming
  failures (11 SET and 42 RESET). Independent
  read job `3502ff4562dc4e01a8284a3c50ebeae8` completed all 1,024 cells but had
  280 parity mismatches; a repeat read without intervening writes, job
  `40eff80686e94d639850b56bfd3df66a`, had 276 mismatches and 24 assigned-bit
  classification changes. Neither reconstructed parity SHA-256 matched the
  encoded record, so physical EDAC correctly remains blocked. These are failed
  verification trials, not successful stored-parity evidence.
- **Read-order diagnostic:** forward, reverse, and deterministic-random reads
  of rows 17 and 18 on the `541cfd...` image changed only marginal cell
  `r17c31`; the other 63 coordinate-aligned classifications were stable. Read
  order is not the dominant failure mechanism.
- **Two-phase physical-parity gate:** the deployed `b69c7ac...` image has
  passed simulation, implementation, safe deployment, and full initialization.
  The latest independent read, job `e157bd40d31a4ff8a924831734c166ef`,
  completed all 1,024 cells after an interrupted parity-program attempt and
  found 313 mismatches in the 576 assigned cells. Physical check/repair remains
  blocked until exact parity SHA-256 equality.
- **VM / vendor ZS-EDAC:** the pinned Linux/AArch64 relay runs in the local
  Ubuntu VM through `qemu-aarch64`; live ZES1 `INFO` reports vendor `1.3.0` and
  1024/72 geometry. An exact one-bit fault is detected and repaired back to the
  baseline SHA. Capabilities report `execution_kind=vm`, never `real_board`.
- **A53 / vendor ZS-EDAC:** board execution remains pending because SD boot
  stops in BootROM and no board Linux/SSH IP is reachable.

## Current-host blockers that must remain visible

- The local Qwen CPU runtime is usable after the bundled model download and
  hash check; no NVIDIA GPU is detected, so generation latency is CPU-bound.
- The Ethernet interface has link but no reachable ZCU106 Linux/SSH neighbour;
  the verified VM relay is a software-plane substitute, not an A53 claim.
- The existing hardware route is Windows Vivado/JTAG/VIO, not PS-to-PL AXI.

These block an end-to-end board-A53-plus-physical-parity claim, but not real
Qwen inference on the PC, the VM-hosted vendor ZS path, web/protocol validation,
FPGA build and simulation, or measured PL/ReRAM reads over the existing
Vivado/JTAG/VIO route.

