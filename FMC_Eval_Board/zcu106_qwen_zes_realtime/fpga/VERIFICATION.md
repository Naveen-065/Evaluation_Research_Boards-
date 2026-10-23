# Verification record — 2026-10-23

The build and RTL checks below were followed by physical deployment and full
initialization of the corrected image on the attached ZCU106.

## Deployment-hold correction

The superseded image returned status `0x0000000e00008100` after deployment:
the outer wrapper had accepted the host toggle and remained busy, but the inner
core was IDLE with `interface_enable=0`. The core had gated every operation,
including digital-only hold/abort op4, on `dac_ready`; deployment deliberately
keeps that interlock low. The correction permits only op4 through a low DAC
interlock and forwards op4 from every non-ready wrapper state, so it can also
recover `WR_WAIT`. Op4 never asserts `dac_start`; all array-touching operations
remain interlocked. The old `164b...` bitstream is superseded by the hash below.

## RTL simulation

Command: `powershell -ExecutionPolicy Bypass -File .\tests\run_sim.ps1`

- PASS: op4 reset hold with the DAC interlock disabled in both scan and WB
  ownership, op4 recovery from a deliberately stuck `WR_WAIT`, bitmap
  load/readback, fail-closed op15 launch, exact two-phase SET-then-RESET order
  over a mixed range,
  all-zero/all-one/alternating 1024-bit images, full-count launch and safe
  abort, op13 page boundary, per-packet reset cadence, and op12/op13
  compatibility.
- PASS: unchanged legacy protected-DAC/WB-supply-mask, serial scan, FPGA MAC,
  ADC trace, WB frame/UART, abort, and fault regression.
- The runner requires exact PASS markers; it does not rely only on XSim's
  process exit code because Vivado 2022.2 may return zero after `$fatal`.

### Two-phase scheduler correction

The physical program/read pair `e9107b27095840e28eb6b420ad803f96` /
`3502ff4562dc4e01a8284a3c50ebeae8` showed strong post-verification disturb:
187 zero targets passed their immediate RESET verification but later read back
as LRS, while only 60 immediately passing zero targets remained HRS.  The
source now scans all SET targets first and all RESET targets second, without
changing per-cell ramps, confirmation reads, result addressing, or mandatory
Caravel reset/READY cadence.  The updated RTL and both bitmap/legacy simulations
pass.  The two-phase source has now been synthesized, routed, hash-pinned,
physically deployed, and fully initialized as recorded below.  No physical
full-parity program plus independent read has yet been accepted on that image;
build/deployment success must not be represented as stored-parity success.

The zero-write forward/reverse/deterministic-random diagnostic under
`../evidence/read_order_probe_2026-10-23/` was acquired before this deployment
on the `541cfd...` interleaved image.  Only marginal cell `r17c31` changed
classification among 64 coordinate-aligned row-17/row-18 samples, and no
spare-row state changed.  Acquisition order is therefore not the dominant
cause of the failed interleaved-image parity record.

## ZCU106 implementation

Vivado 2022.2 completed synthesis, placement, routing, DRC, checkpoint, debug
probes, and bitstream generation for `xczu7ev-ffvc1156-2-e`.

- Timing: WNS `+0.525 ns`, TNS `0`, WHS `+0.010 ns`, THS `0`; all user timing
  constraints met.
- Routing: 19,944/19,944 routable nets fully routed; zero routing errors.
- DRC: zero errors and zero critical warnings. The seven ordinary warnings
  are the same rule/count set as the preserved baseline image: DPOP-3 (1),
  DPOP-4 (2), PDCN-1569 (3), and RTSTAT-10 (1).

Artifact SHA-256:

- bitstream: `b69c7ac2eebb9b1f2afea506ea099246f906dc68c03248fb9a204d5e9791368c`
- probes: `d49d9992d961bab1d451e8594ee4f4a9d253aa847a6015373a647e7dbeb24e70`
- routed checkpoint: `cad82cecff6d6046c4b079f8d38db9b78fdb69f0ebc9d9515d00a6b6ffc118f4`

`output/artifact_manifest.json` pins every generated artifact, active RTL/Tcl/
XDC source, host tool, and test source.  Its `bitstream_deployed` value is the
build-time state; the separate hash-pinned deployment receipt is authoritative
for the subsequent physical program action. `baseline/SHA256SUMS.txt` verifies all
33 preserved baseline source/artifact files; the preserved baseline bitstream
SHA-256 is
`ba7f5afee7dc5134828004ad48114ef9f2079b28b83de17650288d9cffe04bfb`.

## Physical deployment and startup

The two-phase bitstream was physically programmed on 2026-10-23 and supersedes
the interleaved `541cfd...` image and the earlier `164b...` development image.
`output/deployment_receipt.json` records the deployed SHA-256 as
`b69c7ac2eebb9b1f2afea506ea099246f906dc68c03248fb9a204d5e9791368c`
and the probes SHA-256 as
`d49d9992d961bab1d451e8594ee4f4a9d253aa847a6015373a647e7dbeb24e70`.
Receipt creation followed successful `BMP2` identity and corrected op4 hold
checks with both ADC/DAC interlocks disabled; the recorded post-program state
keeps the Caravel reset asserted and issues no array pulse.

Full initialization then passed on the deployed two-phase image.  The hardware log
records HPC0 mux address `0x75` selecting value `0x01`, the 2 MHz Si5351/PLLA
checks, completed DAC and 10 MSPS ADC startup, and ten consecutive valid
60 MHz LCLK / 10 MHz ADCLK return-clock windows.  It ended with
`FULL_CONTROL_STARTUP_PASS` and the CPU held until an operation.  This is
deployment/startup evidence only; post-programming physical parity verification
remains a separate gate.  The failed program/read evidence documented above
belongs to the superseded `541cfd...` image and is not evidence for or against
the physical accuracy of this newly deployed two-phase image.

## Host-tool checks

- Tcl files are syntactically complete (`info complete == 1`).
- PowerShell scripts parse without errors.
- `tests/run_row_order_tests.ps1` passes row/range validation, deterministic
  forward/reverse/random ordering, and a hardware-free mocked VIO integration
  run. The mock proves exactly one op1 transaction per requested cell, rejects
  SET/MAC/reserved op1 payload bits and op12/op15, validates CSV/JSON output,
  and injects a mid-read FPGA fault to prove final abort, read-profile
  restoration, hardware-manager closure, and `.partial`-only failed output.
- The parity packer compiles and emits exactly 32 words, 1,024 physical-cell
  rows, and the expected 576 parity-bit / 448 fill-cell mapping.
- The deployment tool has a caught-error op4 reset hold, scan-disable fallback,
  interlock disable, and hardware-manager closure. Bitmap program/read tools,
  used after normal DAC initialization, retain best-effort abort/read-profile
  restoration.
- Safe deployment independently pins both `.bit` and `.ltx` hashes and writes
  JTAG target/device plus artifact identities to its deployment receipt.
