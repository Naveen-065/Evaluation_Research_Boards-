# ZCU106 1Kbit bitmap scheduler

This directory is a self-contained, new-folder-only extension of the validated
ZCU106 J5/HPC0 1Kbit scheduler. The original source snapshot is preserved under
`baseline/` with `baseline/SHA256SUMS.txt`; no file under
`FMC_Eval_Board/output/` is modified.

The completed simulation/build evidence and exact new artifact hashes are in
`VERIFICATION.md` and `output/artifact_manifest.json`.

The current two-phase image has bitstream SHA-256
`b69c7ac2eebb9b1f2afea506ea099246f906dc68c03248fb9a204d5e9791368c`.
It is physically deployed and passed safe reset hold plus full board
initialization; `output/deployment_receipt.json` is the deployment authority.
No full parity program plus independent read has yet been accepted on this
image, so deployment status must not be interpreted as physical-parity success.

The active RTL source also contains a later, simulation-verified per-cell
watchdog for a mid-packet `dac_ready` loss: it issues op4, records that cell as
failed, and continues without changing SET-before-RESET order. That source
change post-dates the deployed hash above and is **not** present in the active
FPGA until a new full build and hash-pinned deployment are completed.

`baseline/zcu106_artifacts_2026-10-23/` also preserves the previously deployed
known-good `.bit`, `.ltx`, `.dcp`, and implementation reports. Its bitstream
SHA-256 is `ba7f5afee7dc5134828004ad48114ef9f2079b28b83de17650288d9cffe04bfb`.

The extension turns a complete 1024-bit parity image into one FPGA-owned array
job. The host performs 32 short VIO writes and 32 independent readbacks, then
the FPGA walks physical cells serially. A target bit of `1` means LRS/SET; `0`
means HRS/RESET. The scheduler skips pulses for cells that are already in the
requested state but still performs ten verification reads and records the
measured current. RESET targets use the existing reliable 96-point ramp and up
to three bounded extra sweeps. SET targets use the measured three-step ramp.
Operation 15 visits all SET targets in increasing physical-index order first,
then all RESET targets in increasing physical-index order. This makes RESET the
last operation on requested HRS cells, reducing the observed case where a later
neighboring SET disturbed a RESET cell that had already passed verification.
Result records remain keyed by physical index, so op13 and the CSV format stay
row-major despite the phased execution order.

The array is physically row-major:

```text
physical_index = 32 * row + column
word_index     = physical_index / 32
bit_index      = physical_index % 32
```

The 72-byte ZS-EDAC parity buffer contains 576 bits. `tools/pack_zs_parity.py`
maps parity bit `i` to physical index `i` (rows 0..17) and explicitly fills
cells 576..1023. The byte-internal bit order is a host policy (`lsb0` by
default) and is recorded in the generated manifest; change it only if the
board-side ZS integration defines the opposite order.

## VIO protocol additions

The existing 64-bit command framing is unchanged: bit 63 toggles per command,
bit 62 enables the interface, bits 61:58 select the operation, and bits 57:0
are the payload.

Operation 14, `BITMAP_WORD`, uses this payload:

| Bits | Meaning |
|---|---|
| 57 | Clear validity before this write |
| 56 | Read-only transaction |
| 55:51 | Bitmap word 0..31 |
| 50:32 | Reserved; must be zero |
| 31:0 | Write data; ignored for a read |

Success returns signature `BMP2` (`0x424d5032`) in result1[255:224], the
transaction flags/index, the post-command 32-bit validity mask, and the actual
word. An invalid command returns `BME2`. Disabling the scan interface clears
the bitmap and validity mask, so stale parity cannot be programmed after an
image/interface reset.

Operation 15, `BITMAP_PROGRAM`, is accepted only after all 32 words are valid:

| Bits | Meaning |
|---|---|
| 57 | Use reliable RESET ramp for zero targets |
| 56:47 | Physical start index |
| 46:37 | Count minus one |
| 36:22 | Base pulse hold clocks (20..12000) |
| 21:20 | Additional RESET sweeps (0..3) |
| 19:0 | Reserved; must be zero |

Progress/completion signatures are `BPR2` and `BPD2`. The established op13
result paging remains intact. Each 32-bit per-cell word is:

| Bits | Meaning |
|---|---|
| 15:0 | Signed compact ADC current code |
| 25:16 | Programming pulse count |
| 26 | Target verified/pass |
| 27 | A programming pulse clipped |
| 28 | Requested target bit (bitmap jobs only) |
| 29 | Bitmap-record marker |
| 31:30 | Reserved |

For legacy op12 jobs bits 31:28 remain zero, preserving the existing decoder.
The op15 completion summary also contains SET/RESET target and failure counts.

The core packet engine is unchanged. Every initial read, program step, and
confirmation read still asserts a fresh Caravel reset and observes READY (or
the established bounded fallback). Scan packets are never streamed
continuously.

## Build and simulation

From this `fpga` directory:

```powershell
powershell -ExecutionPolicy Bypass -File .\tests\run_sim.ps1
powershell -ExecutionPolicy Bypass -File .\tools\build_bitstream.ps1
```

Simulation checks fail-closed launch, all-word load/readback, all-zero/all-one/
alternating 1024-bit images with a non-wrapping full-count launch and safe
abort, exact SET-then-RESET ordering over a mixed range, recovery after a
deliberate mid-packet DAC-interlock loss, reset/READY packet cadence, op13
paging across the physical 13/14 page boundary, and op12/op13 compatibility.
The runner requires exact PASS markers because XSim 2022.2 can return zero
after `$fatal`.

The build script runs the full ZCU106 implementation and creates
`output/artifact_manifest.json` with SHA-256 for the bitstream, probes,
checkpoint, reports, and active RTL/Tcl/XDC sources. A successful build alone
does not deploy the image.

## Safe deployment and host tools

Deployment is deliberately a separate, hash-pinned action:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\program_bitstream.ps1
```

It independently verifies both the bitstream and probes SHA-256 values from
the build manifest, targets exactly one local `xczu7`, programs the pinned
`.bit` plus `.ltx`, verifies the wrapper-local `BMP2` protocol, explicitly
keeps `run_enable=0` and `dac_enable=0`, and then requires a completed op4
digital reset hold without an array pulse. Op4 is the only core command allowed
through the disabled DAC interlock; it can only own the digital scan pins and
assert Caravel RESET_B. All array-touching commands remain fail-closed. The
receipt records this state, JTAG target/device identity, normalized artifact
paths, and both hashes. Caught post-program errors best-effort reassert op4,
fall back to scan high-impedance if that cannot acknowledge, disable both
interlocks, and always close the hardware manager. Deployment is not invoked
by the build.

The superseded image with bitstream SHA-256
`164b4d4a9e2ccde80e362fed75d9cbd73dceb3bdad06917638051d8c6dd0eaab`
must not be used for deployment: it gated op4 behind `dac_ready`. A status of
`...0e00008100` means the wrapper accepted the host toggle and is busy, while
the inner core is IDLE with its interface disabled. On that old image the only
non-driving recovery is to write an all-zero `scan_command` (command bit 62
clear), which resets the wrapper and tri-states the scan pins. The corrected
image's hash is pinned in `output/artifact_manifest.json`.

Pack a ZS parity buffer and program it:

```powershell
python .\tools\pack_zs_parity.py parity.bin .\output\parity.hex
& 'C:\Xilinx\Vivado\2022.2\bin\vivado.bat' -mode batch `
  -source .\tools\bitmap_program.tcl -tclargs `
  .\output\parity.hex .\output\parity_run 0 1024 2400 2
```

`bitmap_program.tcl` loads and independently reads back all 1024 requested
bits before op15. It emits live physical progress and writes a per-cell CSV and
JSON manifest. Programming failures are data, not a job abort: the FPGA stores
the failed result and continues to the next cell. Its caught-error cleanup,
like the direct read tool, requests a best-effort abort, restores the safe read
profile, and closes the hardware manager before preserving the original error.

Read the actual array without the legacy SenseEval hash gate:

```powershell
& 'C:\Xilinx\Vivado\2022.2\bin\vivado.bat' -mode batch `
  -source .\tools\bitmap_read.tcl -tclargs .\output\array_read 0 1024
```

The read tool issues only op1 reads, reports progress, and writes CSV/JSON with
physical coordinates, current, conductance, and observed bit. Classification
uses the measured separator of 34.2563054 uA at the 0.5-V read bias
(68.5126108 uS). Before reading it performs a non-mutating `BMP2` identity
transaction, and it restores the read profile even after a caught read error.

### Read-order diagnostic (no programming pulses)

`tools/row_order_read.tcl` reads one or more complete physical rows while
controlling the order of the 32 columns. This is intended to distinguish a
cell/state effect from acquisition-order or settling effects. It accepts
`forward`, `reverse`, or seeded `random`; a random seed creates one reproducible
permutation that is applied identically to each selected row. Rows may be
individual numbers or ascending ranges, and duplicate or out-of-range rows are
rejected before Vivado opens the hardware manager.

```powershell
# Rows 0, 3, and 7 through 9, forward columns 0..31.
& 'C:\Xilinx\Vivado\2022.2\bin\vivado.bat' -mode batch `
  -source .\tools\row_order_read.tcl -tclargs `
  .\output\row_probe_forward '0,3,7-9' forward

# The same rows using a reproducible randomized column permutation.
& 'C:\Xilinx\Vivado\2022.2\bin\vivado.bat' -mode batch `
  -source .\tools\row_order_read.tcl -tclargs `
  .\output\row_probe_random '0,3,7-9' random 20261023
```

The script can issue only op1 READ, protected op2 read-profile DAC changes,
op4 safe abort/reset hold, and a read-only op14 `BMP2` identity query. It has no
path to op12 or op15, so it cannot create SET/RESET pulses. Each cell remains a
separate op1 command: the existing FPGA packet engine asserts a fresh Caravel
reset and waits for READY (or its bounded established fallback) before every
packet. CSV and JSON retain `acquisition_index`, physical row/column/index, the
column-order metadata, current, conductance, and state. On success or error the
tool explicitly requests safe abort and restores the full read profile before
closing JTAG. Output is first written as `.csv.partial` and `.json.partial`;
the final `.csv`/`.json` names are promoted only after all selected rows and
the final abort/read-profile restoration complete successfully. The CSV
columns are `acquisition_index,row,column,physical_index,column_order,seed,`
`current_uA,conductance_uS,observed_bit,observed_state,threshold_uA`. JSON
contains the same cell measurements plus the selected rows, exact 32-element
column permutation, mode, seed, threshold, and final LRS/HRS counts.

Run its hardware-free parser/order tests with:

```powershell
powershell -ExecutionPolicy Bypass -File .\tests\run_row_order_tests.ps1
```

## Safety and current status

- Programming rails retain the 3.0-V hard cap.
- The proven DAC2/DAC3 RESET path and read-profile restoration are unchanged.
- Hardware deployment is intentionally not part of build or simulation.
- A full-array mixed program remains device-limited: already-correct cells
  need eleven reset/READY read packets; difficult HRS targets can require up
  to three complete 96-step sweeps. The host/VIO round trips have been removed
  from the per-cell ramp, but analog convergence still dominates latency.
