# FMC Evaluation Board — SenseEval v1.2F / KC705

System snapshot dated **20 October 2026**. The active implementation is
[`output/kc705_cell_control`](output/kc705_cell_control). It adapts the evaluation
research board's scan-debug, Wishbone, and GUI logic to the SenseEval FMC PCB.

This folder contains all 20 saved FPGA bitstreams from the source workspace,
their available probes/checkpoints, controller and firmware sources, PCB design
files, simulations, measurements, test programs, and raw run records.
**Use the current image identified below for this assembled PCB.** Older images
are retained for traceability and include superseded pin-use, supply, diagnostic,
and startup configurations. They are not interchangeable with the current image.

## System and signal flow

```text
Browser at 127.0.0.1:8771
  -> local Python HTTP API
  -> SSH through Ubuntu VM
  -> Windows Vivado / JTAG
  -> KC705 FPGA, FMC J2
       -> Si5351A clock configuration via FMC management I2C
       -> DAC81416 SPI: supplies, biases, SET/RESET/read rails
       -> ADS5282 control and 10-MSPS LVDS acquisition
       -> Caravel scan control or Wishbone firmware command transport

Caravel supply/current path -> 56-ohm shunt -> preamplifier
  -> ADS5282 -> FPGA accumulation/trace -> GUI/API measurements

Ubuntu VM -> PCB FT232H -> Caravel housekeeping / SPI flash
```

The GUI follows the reference ScanDisk Monitor layout: cell map, operation
controls, API return log, and one logarithmic Read Trace with pulse-voltage bars.
Conductance shown in the GUI is an **estimate**, not a calibrated cell resistance.

## Contents

| Location | Purpose |
|---|---|
| `output/kc705_cell_control/build/` | Current `.bit`, matching `.ltx`, routed `.dcp`, timing/DRC and I/O audit |
| `output/kc705_cell_control/*.v`, `*.xdc` | Current RTL and exact electrical constraints |
| `output/kc705_cell_control/control.tcl`, `scan_ramp.tcl` | Runtime operations and bounded scan ramp |
| `output/kc705_cell_control/initialize.tcl` | Explicit FPGA, clock, DAC and ADC initialization |
| `output/kc705_cell_control/gui/` | Browser UI, API, SSH startup retry implementation |
| `output/kc705_cell_control/firmware/` | Caravel C source, binary, ELF, FT232H tools and firmware SDK |
| `output/kc705_cell_control/ip/` | Four Xilinx IP configurations retrieved from the build PC |
| `output/kc705_cell_control/tests/` | Model, GUI, RTL, ramp, protocol and transport tests |
| `output/kc705_cell_control/runs/` | Per-job parameters, decoded results, raw logs and traces |
| `output/kc705_cell_control/evidence/` | Deployment records, validation reports and screenshots |
| Other `output/` folders and `build_before_*`, `build_no_trace` | Historical bring-up, earlier images and diagnostic work |
| `hardware/` | Original schematic PDF/archive and editable KiCad board, schematic and libraries |
| `source_snapshot.json` | Source-to-copy inventory and original SHA-256 values |
| `package_state.json` | Bench/API state observed during packaging and dependency provenance |
| `SHA256SUMS`, `verify_package.py` | Final package integrity verification |

Historical readmes/logs describe the state when they were written. This README
describes the current controller; notably, scan SET/RESET now use ramps, WB holds
both SE and TM low, and the GUI has one reference-style Read Trace.

## Current deployment artifacts

All paths in this table are relative to `output/kc705_cell_control/`.

| Artifact | SHA-256 |
|---|---|
| `build/kc705_adc_capture.bit` | `fe31f0249b7081b4f6a00a721002317d618b0294cad9c5306f62853f5e34427c` |
| `build/kc705_adc_capture.ltx` | `6f800d28394e1f524304c3b59190f6ef819020bd2ff781928890fca4f9248e96` |
| `firmware/gui_wb_mode.bin` | `e7ad11e318b346edaae2fd0ff30736433fb27ef3bc5c39118ab4f1fc0a4107ef` |

FPGA: **XC7K325T-FFG900-2**, KC705. Build environment: Vivado **2026.1**.
The recorded image passed setup timing (+0.360 ns), hold timing (+0.059 ns),
and the critical DRC check. The 41 exported port-property records match the
audited baseline. Use the `.ltx` belonging to this `.bit`.

The FPGA image is loaded through JTAG into volatile configuration. A power cycle
requires checking/reinitializing the FPGA and peripheral state; this package
does not install an FPGA configuration-flash boot image.

## PCB wiring and fixed electrical settings

* **FMC VADJ is 1.8 V**, as measured on this KC705 after power cycling.
  Keep the supplied XDC pin mappings, I/O standards, drive, slew, pulls and
  termination unchanged. Runtime initialization does not issue VADJ/PMBus writes.
* FMC management I2C is a separate **3.3-V** bus at KC705 J2 **C30/C31**.
  It is not made 1.8 V by setting VADJ. The board was reworked by removing
  **R53, R54 and U18**, bridging **R53-2 to R58-2** and **R54-2 to R57-2**.
  Preserve this tested wiring; consult the schematic and rework evidence before
  using a differently assembled board.
* **NT22 connects DAC14 to VDDA1, target 3.0 V; NT12 is absent.**
  **DAC15 supplies VCCD2 at 1.8 V.** Runtime DAC commands cannot modify these
  protected supply channels or the reference/range configuration.
* R9, R10 and R11 are all **56 ohms** in the tested assembly. Earlier
  documents/simulations also contain previous shunt values.
* DAC internal-reference startup is included. U1 SDO is not connected:
  FPGA completion proves command transmission, not DAC register readback.
  Verify actual supply/bias voltages with a meter after assembly changes.
* ADC operation is 10 MSPS, offset binary, LSB first, with nominal internal
  94-ohm LVDS termination. Return clocks are checked at 10 MHz and 60 MHz.
* Caravel scan operation uses a 2-MHz Si5351 clock; WB uses 10 MHz.
  Each normal job restores scan read rails and holds Caravel CPU reset.

| ADC channel | Shunt / path | Preamplifier | Differential output pads |
|---|---|---|---|
| ADC1 | R9 / READ | U10 | R37 / R38 |
| ADC2 | R11 / RESET | U13 | R46 / R47 |
| ADC3 | R10 / SET | U11 | R39 / R40 |

Scan-debug cell reads principally use **DAC2/DAC3 and ADC3/R10** on this PCB.
Do not assume that the reference board's DAC channel numbers transfer directly.
Nominal preamplifier gain is 7; independent calibration remains pending.

Scan idle targets: DAC0=0.5 V, DAC1=2.5 V, DAC2=0.5 V, DAC3=2.5 V,
DAC5=2.3 V; DAC9/IREF=0.9 V, DAC10/VCOMP=0.9 V,
DAC11/BIAS_COMP2=0.6 V, DAC12/VBIAS=1.6 V, DAC13/DC_BIAS=1.0 V.
DAC4/6/7/8 are off (mask `0x01D0`).

WB uses DAC3 off, DAC4=0.5 V, DAC5=2.5 V, IREF=1.0 V and DC_BIAS=1.5 V;
other listed biases stay unchanged. Its power mask is `0x01CC`, disabling
physical DAC2/VCC_SET. Both SE and TM are actively low in WB; floating TXS0108E
inputs can otherwise select the wrong mode. Reset remains open-drain.

## Modes and ramp behavior

Scan GUI/API modes: `read`, `set`, `reset`, `cycle`, `column` (32 rows at one
column), and `array` (32 × 32). WB modes: `wb_read`, `wb_set`, `wb_reset`,
and `wb_cycle`. Do not infer additional WB array/column support from old scripts.
The approved programming test cells were **scan r0/c0** and **WB r0/c31**.

Scan SET/RESET use the reference ramp/read/confirm logic, with these PCB limits:

| Setting | SET | RESET |
|---|---|---|
| VCC sweep | 2.3, 2.4, 2.5 V | 2.3, 2.7, 3.0 V |
| WL sweep | 32 steps, 0.44–2.37 V | 32 steps, 0.94–2.88 V |
| Confirmation threshold | Current ≥35 µA | Current ≤5 µA |
| Consecutive confirmation reads | 10 | 10 |

GUI voltage fields are sweep ceilings. **Neither ramp may exceed 3.0 V.**
The DAC encoder also caps the output code at 39321 (ideal 2.999954 V), avoiding
rounding above the cap. This is a command limit, not an independent measurement
of analog overshoot or DAC accuracy.

Each step reads first, skips programming if the target is already confirmed,
otherwise applies one pulse, restores read rails (VCC=0.5 V, WL=2.5 V), reads
again, and confirms any threshold crossing. Default pulse length is 1.2 ms
(`hold=2400` at the 2-MHz scan clock). Invalid/clipped ADC feedback or Stop
terminates the sequence. Exhausting RESET without meeting its target stops
further requested cycles; completion does not imply a successful resistance change.

WB uses the Caravel firmware's native transaction sequence, including the
repeated program-packet workaround without an intervening reset. It does not
use the scan ADC-feedback ramp. Fifteen tagged/checksummed UART frames and
command echo are checked; raw TDC results remain uncalibrated.

## Running the system

The copied configuration records these existing bench addresses and paths:

| Component | Existing configuration |
|---|---|
| GUI host | This Windows PC; loopback port 8771 |
| Ubuntu VM / SSH jump | `ubuntu-24-04@100.98.132.51` |
| FPGA Windows PC through VM | `fpga@10.0.2.2`, host-key alias `100.86.99.88` |
| Remote controller folder | `C:/Users/fpga.DESKTOP-CVDV1JP/kc705_cell_control` |
| Vivado executable | `C:/AMDDesignTools2/2026.1/Vivado/bin/vivado.bat` |
| JTAG target | `localhost:3121/xilinx_tcf/Xilinx/00001f14c98801` |

Existing SSH keys/known-host identities are required; credentials are not part
of the package. Configure a different bench in `gui/server.py`, `bench.py` and
`i2c_host.tcl`. Merely copying this folder does not redeploy remote Tcl files.

1. Verify board wiring, power and the stated rails. Connect JTAG to the FPGA
   Windows PC and pass the PCB FT232H through to Ubuntu when flashing is needed.
2. Copy the current controller folder, including `build/`, `control.tcl`,
   `scan_ramp.tcl`, other Tcl helpers, and `evidence/`, to the configured remote
   controller directory. Do not deploy a historical sibling directory.
3. After power-up or when explicit reinitialization is needed, from the current
   controller directory run `python bench.py initialize`. This programs the
   FPGA, initializes Si5351/DAC/ADC, checks clocks, and leaves the CPU held.
   It does not flash Caravel firmware.
4. If Caravel firmware is missing, use Ubuntu's existing `caravel_venv` with
   PyFTDI/PyUSB, the packaged `firmware/` files and
   `python caravel_vm.py --flash gui_wb_mode.bin --hold-after`.
   Run this on Ubuntu with the PCB FT232H attached, while the bench is idle.
5. Start one GUI server from `output/kc705_cell_control`:

   ```powershell
   python gui/server.py --port 8771
   ```

   Open `http://127.0.0.1:8771/`, use **Check bench**, then a single **Read**.
   Dry run previews a request without hardware access; clear it to execute.
   Use Stop for a controlled abort and wait for the cleanup result.

Do not run two controller servers against the same hardware. The existing
server may still be running from the original workspace; close it before
starting the packaged copy. Export links provide averaged results and the
latest decimated raw trace.

## API, trace interpretation and SSH fix status

`POST /api/run` accepts the mode, row, col, four voltage ceilings, hold, cycles
and dry_run. `GET /api/status` reports current job and recorded measurements.
`POST /api/cancel {}` requests cleanup. CSV endpoints are `/api/export.csv`
and `/api/trace.csv`; the new backend also exposes `/api/run-log/<job-id>`.

Example scan ramp cycle, which changes cell state if `dry_run` is false:

```json
{"mode":"cycle","row":0,"col":0,"set_v":2.5,"set_wl":2.37,
 "reset_v":3.0,"reset_wl":2.88,"hold":2400,"cycles":1,"dry_run":true}
```

Current is calculated as
`(active_code - idle_code) / 2048 / (7 × 56)` amperes.
The GUI's estimated conductance is this current divided by the commanded
0.5-V read supply. Pulse bars show actual ramp steps. Typical 1.2-ms captures
have about 134 decimated points at 10-µs spacing; this is not a continuous
10-MSPS oscilloscope export.

The packaged **`ssh-startup-retry-v1` API fix passed 11 fault-injection tests**.
It permits three 30-second SSH connection attempts with 2/4-second backoff
only when OpenSSH diagnostics prove failure before remote execution.
It never replays a programming command after an ambiguous disconnect.
Unconfirmed cleanup blocks further hardware operations until recovery.

**At packaging time the original live API still reported no `api_revision`:**
its restart had been blocked, so the backend fix had not been activated there.
A newly started packaged server loads the fix. Confirm `/api/status` contains
`"api_revision":"ssh-startup-retry-v1"`. Network outages can still cause a clear
failure after retries; this fix cannot guarantee permanent connectivity.
`restart_gui.ps1` is an idle-checked manual helper for an existing local server.

## Validation and remaining limitations

* Scan read, SET, RESET, cycle, column and array operations have recorded tests.
  Earlier SET/RESET coverage used fixed pulses; newer cycle records exercise ramps.
* All four WB GUI modes returned valid nonzero selected-column TDC data on the
  corrected firmware/SE/TM/power-mask path. A physical high-resistance RESET
  state and fully calibrated WB conductance have not been demonstrated.
* Ramp job `80047979cb4b4d0b9c400f1271ba7b55`: SET was already above threshold
  (10 confirmation reads, no SET pulses); RESET exhausted 96 steps and ended
  near 16.725 µA, above the ≤5-µA target.
* Later GUI cycle `01bcf263918447aebc3f995c03fd0ed5` completed with 14 SET pulses,
  SET confirmed at 37.322 µA, and 96 RESET pulses ending at 14.939 µA.
  RESET again did not reach its target. The raw run log confirms cleanup.
* Earlier loose shunt connections and a saturated ADC2 analog path were found
  during bring-up. Current calibration and independent analog verification
  remain necessary after any wiring/shunt changes.
* A prior change in r0/c0 current across WB tests was not sufficient to prove
  exclusive physical WB cell-address isolation.
* The current stored bitstream is hardware tested. Rebuilding it from the
  newly collected IP/configuration package has not been hardware validated.

## Integrity, rebuilding and offline tests

From this folder, `python verify_package.py` checks every file in `SHA256SUMS`.
`source_snapshot.json` records the original copied files; the final checksum
manifest additionally covers collected dependencies and packaging documents.

Vivado build scripts retain their original workstation paths for provenance.
`output/kc705_cell_control/build_portable.tcl` uses the packaged IP definitions
and writes a separate `build_portable/` output. It does not overwrite the tested
`build/` image or program hardware. Build with Vivado 2026.1:

```text
vivado -mode batch -source build_portable.tcl
```

Firmware SDK sources were collected from the Ubuntu bench's `caravel_board`
checkout, commit `2812cfd3896e2b1004b5f4559e0601c90cd18f55`.
Use the included firmware Makefile with a RISC-V bare-metal GCC toolchain;
the existing ELF reports GCC 14.2.0. Rebuild outputs go under `rebuilt/`
so the deployed binary remains intact. During packaging, this Makefile and
the included SDK rebuilt the firmware on Ubuntu with a **byte-identical binary**
to the deployed image. See `evidence/package_firmware_build.json` and its log.
No hardware programming was performed for this verification.

From `output/kc705_cell_control`, offline checks include:

```text
python tests/test_model.py
python tests/test_ssh_transport.py
node tests/test_reference_gui.mjs
tclsh tests/test_scan_ramp.tcl
```

These tests do not access the bench. `tests/api_bench.py`, by contrast, submits
real hardware jobs; SET/RESET/cycle modes change cell state.
