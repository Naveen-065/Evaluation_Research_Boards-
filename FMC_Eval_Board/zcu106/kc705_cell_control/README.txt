SenseEval v1.2F / KC705 cell control
=================================

GUI: http://127.0.0.1:8771/

This local GUI adapts the Evaluation_Research_Boards- scan and Wishbone
protocols to this PCB. It uses the KC705 ADC receiver rather than Saleae
for scan current measurements. Select a mode and cell, preview the operation,
then clear "Preview only" to execute. Hardware jobs are serialized.

Modes
-----
Scan: read, SET + readback, RESET + readback, cycle, 32-row column read,
32x32 array read, and serial selected-cell Matrix MAC with FPGA accumulation.
Wishbone: native read, memory-controller SET/RESET writes, and a cycle
with intervening reads. A transaction collects fifteen checksum-checked,
tag-matched UART result frames and verifies the echoed command.

Normal programming uses FPGA command 11, a measured three-point ramp. SET uses
(VCC, WL) = (2.30, 0.44), (2.30, 1.09), (2.30, 1.75) V. RESET uses
(2.30, 0.94), (2.80, 1.83), (3.00, 2.88) V on DAC5 VCC_RESET/VDDA2 and
DAC4 VCC_WL_RESET. Requested GUI ceilings can exclude higher points; both rails
remain capped at 3.0 V. FPGA command 9 retains the original 96-step diagnostic
ramp. The nominal selection interval is 1.2 ms.
Current readings after a pulse determine whether the device changed; a
completed command alone does not.
Wishbone programming uses the reference firmware's repeated-packet
pipeline workaround, with flags 2 and PWM FF.

Hardware mapping and fixed settings
-----------------------------------
ADC1 = R9 READ -> U10 -> R37/R38.
ADC2 = R11 RESET -> U13 -> R46/R47.
ADC3 = R10 SET -> U11 -> R39/R40.
All three shunts are 56 ohms. Gain 7 is nominal; calibration is pending.
Scan-debug cell read uses DAC2/DAC3 and is observed principally on SET/R10.

VDDA1 = DAC14 via NT22, target 3.0 V. NT12 is absent.
VCCD2 = DAC15, target 1.8 V.
DAC2 is the current PCB's VCC_SET route; DAC6 remains disabled.
DAC10 uses a 0..5 V range on this PCB, including its 0.9 V bias code.
WB profile uses DAC4=0.5 V and DAC5=2.5 V with DAC3 off.
WB bias targets: DAC9 Iref=1.0 V, DAC10 Vcomp=0.9 V,
DAC11 Bias_comp2=0.6 V, DAC12 Vbias=1.6 V, DAC13 dc_bias=1.5 V.
Scan cleanup restores Iref=0.9 V and dc_bias=1.0 V.
Runtime DAC writes cannot alter DAC14, DAC15, range or reference registers.
Runtime analog settings are bounded to 0..3.0 V.

All 41 FPGA port properties are audited against the working scan-read
image: package pin, IOSTANDARD, direction, drive, slew, termination and
pull setting. No VADJ/PMBus commands are used.
TM is held low in Wishbone mode: this PCB's U17 TXS0108E has internal
pull-ups, so leaving TM floating can assert scan mode. SE and SI are released
as required by the WB protocol. All port electrical properties remain the
same. Reset remains open-drain.
Reference: https://www.ti.com/lit/ds/symlink/txs0108e.pdf, section 7.3.5.
ADC: 10 MSPS, 60 MHz LVDS bit clock, internal nominal 94-ohm termination,
offset-binary, LSB-first. The current validated ADC deserializer is retained.

Waveform and units
------------------
The top plot contains measured FPGA ADC snapshots before, during and after
the selection interval. Default read: about 134 points at 10 us spacing,
decimated from 10 MSPS. Longer pulses use 25 us spacing. This is a
decimated trace, not a full-rate oscilloscope capture.
Three paths are plotted separately. Per-read averages still integrate
about 640 idle samples and 11,995 active samples.
Delta current = (active code - idle code) / 2048 / (7 * 56) amperes.
It is supply-current change, not independently calibrated pure cell current.
Programming-pulse clipping is retained as waveform evidence but is not used to
decide cell state. Clipping in the restored read profile invalidates the current
estimate and stops further pulses.
Wishbone coarse/fine counts are not calibrated conductance.
ZCU106 job d3f03975f2594860b4c18931dd55ce45 confirmed r0/c0 SET at
36.045 uA after 14 DAC2/DAC3 pulses. Corrected RESET job
0fdab8852aab497fb48679616a8bf32e used DAC5=1.7 V and DAC4=2.5 V; its
readback was 36.10 uA before and 36.18 uA after. The routing is corrected, but
a <5-uA high-resistance state was not demonstrated on this cell.
CSV links export averaged measurements or the latest measured trace.

Startup / recovery
------------------
Run GUI:
  python gui/server.py --port 8771

Explicit bench initialization:
  python bench.py initialize

This loads the audited bitstream, sets Si5351 CLK0/CLK1 to 2 MHz, starts the
fixed DAC profile, initializes the ADC, verifies return clocks, and holds
Caravel reset. Use the existing Ubuntu FT232H helper to select external
clock bypass and clear housekeeping CPU reset:
  cd ~/kc705_cell_control/firmware
  ~/caravel_venv/bin/python caravel_vm.py --release

The GUI does not automatically flash firmware or reset the FPGA when a
read fails. After power cycling, explicit initialization is required.
The validated combined Caravel firmware is firmware/gui_wb_mode.bin.
Its backup/readback records are under firmware/evidence.

Each job restores the scan read profile and holds Caravel reset on exit,
including after a controlled cancellation. A communication failure can
prevent confirmation of cleanup; inspect the saved log before continuing.
The displayed voltage values are commanded targets, not meter readings.

API
---
POST /api/run JSON fields:
  mode, row, col, set_v, set_wl, reset_v, reset_wl, hold, cycles, dry_run
For mode=scan_mac, also provide weight_matrix (binary rectangular list),
input_vector (signed int8, one value per row), and program_matrix (boolean).
The FPGA never activates multiple rows. It reads each selected cell serially,
multiplies the ADC3 current delta by the input value, and accumulates signed
56-bit column results in fabric. If program_matrix is false, the physical array
is left unchanged and the matrix supplies only the requested dimensions.
hold is in 2 MHz scan-clock cycles; default 2400.
Allowed hold range is 20..12000 cycles (0.01..6 ms).
GET /api/status returns deployment state, jobs and real measurement history.
POST /api/cancel {} requests a controlled stop.
GET /api/export.csv and /api/trace.csv export measurements.

An example read request:
  {"mode":"read","row":0,"col":0,"dry_run":false}

Tests and evidence
------------------
tests/tb_control.v exercises scan packet order, DAC falling-edge SPI,
protected supply writes, ADC accumulation, real-sample trace storage,
Wishbone pulse encoding/UART bank capture, ADC fault and reset/abort.
tests/test_model.py checks limits, channel mapping, current math,
trace timestamps and Wishbone completeness/echo checks.
tests/test_gui.mjs runs the reference-frontend integration checks, including
all ten GUI payloads, saved pulse/read association, clipped and nonpositive
values, cross-job isolation and the Wishbone unverified state.
tests/api_bench.py executes actual hardware jobs through the GUI's API.

The current user-selected programming test cells are scan r0/c0 and
Wishbone r0/c31. Column/array tests are read-only.
Runs contain raw VIO words, decoded measurements, trace samples, logs and
parameters. Check the validation report for measured results and limitations;
software simulations and preview checks are not hardware measurements.

Measured three-point 1Kbit validation (2026-10-23)
-------------------------------------------------
Full-array SET job 82f9e6aae8bf433695ba00f20ff4f6b7 completed in 450.84 s:
1019/1024 cells met the >=35-uA target, 962 needed no pulse, and 176 total
pulses were applied. This was 8.72x faster end-to-end than the earlier
96-step SET job d42d176742d74a90bd4fef034aec5178.

Full-array RESET job c4756ed4f9044d8f9f0649b0d206d2cb completed in 313.06 s.
All 1024 cells received all three pulses and 0/1024 met the <=5-uA target.
Therefore the three-point scheduler is validated for speed and SET accuracy,
but the tested capped RESET rail pairs are not a working HRS recipe.
Run analysis/analyze_fast3_ramp.py to reproduce the per-cell CSV and summary.
The displayed values are commanded DAC targets, not independently measured
rails. End-to-end operation is interactive-minute scale, not real-time; JTAG,
mandatory Caravel reset/READY, reads, MAC readback and Vivado startup dominate.

Reference front end
-------------------
The front end uses the evaluation research board's ScanDisk Monitor layout,
logo, colors and logarithmic Read Trace, with its pulse-voltage subplot.
The separate raw ADC waveform panel and extra current/history cards are
removed. Raw ADC samples remain available from /api/trace.csv.

The displayed conductance is an estimate: SET/R10 delta current divided by
the commanded 0.5 V read supply. The current uses 56 ohms and nominal gain 7.
This is not a calibrated cell-only conductance. WB TDC words are not converted
to conductance; they appear in API return with their validation status.
The chart groups each program pulse with its own following read. It never
uses pulse current as read conductance or pairs across cells or jobs.
Zero/negative currents cannot appear on a logarithmic axis and are omitted.

Select a saved run to pin its trace, or use FOLLOWING to track the newest job.
All saved runs shows the most recent 80 grouped points across available
history. The heatmap retains the most recent measured value for each cell.
The API supports the ten operation choices shown; no unsupported reference
buttons, password field or raw Wishbone write control are presented.

Static files are read from disk on each request. Reload the browser after
front-end edits; a server restart is not needed for these files.

SSH connection handling
-----------------------
API revision ssh-startup-retry-v1 allows 30 seconds to establish SSH and
at most three attempts, with 2/4-second backoff. Only recognized OpenSSH
diagnostics proving failure before remote execution allow another attempt.
An arbitrary exit 255, broken pipe, or failure after Vivado output never
replays the operation. An uncertain interrupted hardware run blocks further
operations until its cleanup has been checked. Check bench remains available.
The API and GUI show the current attempt and a specific final error; Run log
links to the most recent 32 KiB of that job's raw output.

GET /api/status reports api_revision and transport settings so an operator
can confirm the running backend has the fix. Backend changes require a
server restart; changing these source files alone does not update a running
Python process. tests/test_ssh_transport.py injects connection faults without
network access or hardware programming.
