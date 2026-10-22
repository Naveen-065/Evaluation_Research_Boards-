# ZCU106 FMC evaluation-board reproducibility backup

This folder is a self-contained backup of the ZCU106 J5/HPC0 implementation
validated on 2026-10-23. It preserves the two-directory layout used by the
tested Tcl scripts:

- `zcu106_cell_control/`: ZCU106 constraints, build/deployment Tcl, routed
  checkpoint, programmed bitstream/probes, timing/DRC/I/O reports and
  deployment evidence.
- `kc705_cell_control/`: shared RTL, scan/MAC controller, GUI/API, Caravel
  firmware, tests and analysis. The historical directory name is retained so
  the validated relative paths remain unchanged.
- `results/`: the exact final 32x32 LRS and HRS reads used for the distribution
  plot, all five contiguous HRS resume configurations, and provenance metadata.

## Validated hardware and electrical setup

- Carrier: AMD/Xilinx ZCU106, FMC connector J5/HPC0.
- FMC `VADJ_FMC`: measured 1.79625 V (nominal 1.8 V).
- FMC management I2C C30/C31: 3.3 V bus through the documented board rework.
- Array: 32 rows x 32 columns; only one selected row is active per read.
- Scan clock: 2 MHz. Every scan packet receives a fresh 12 ms Caravel reset.
- The post-reset READY wait prefers the real READY handshake and falls back
  after the proven 1 ms Kintex-compatible interval.
- Vivado build used: 2022.2, part `xczu7ev-ffvc1156-2-e`.

Read `zcu106_cell_control/pin_compatibility.md` before connecting hardware.

## Verify the backup

From this directory:

```powershell
./verify_manifest.ps1
```

The deployed image SHA-256 is
`b1344941f1effc4a0fbf4314291f5f6567be2208c4d4bcdc8fc4cea792e36fcf`.
The routed build passed with WNS `+0.447 ns`, WHS `+0.010 ns`, no timing
violations and no DRC errors.

## Rebuild the FPGA image

```powershell
Set-Location zcu106_cell_control
& 'C:\Xilinx\Vivado\2022.2\bin\vivado.bat' -mode batch -source build_zcu106.tcl
```

The full build recreates the debug IP and writes `.bit`, `.ltx`, `.dcp` and
reports into `zcu106_cell_control/build/`. The checked-in DCP can also be used
with `rebuild_cached_impl.tcl` for an implementation-only rebuild.

## Program and initialize

Measure VADJ first, connect the mezzanine only to J5/HPC0, then run:

```powershell
Set-Location zcu106_cell_control
& 'C:\Xilinx\Vivado\2022.2\bin\vivado.bat' -mode batch -source initialize.tcl
```

For a conservative first connection, run `program_safe_and_check_i2c.tcl`
before full initialization. The scripts hold the CPU and restore the safe scan
read profile during cleanup.

## Caravel firmware

The exact deployed image is
`kc705_cell_control/firmware/gui_wb_mode.bin`. Source, ELF, Makefile and the FTDI
programming utility are stored alongside it. Inspect the available programmer
arguments before flashing:

```powershell
python kc705_cell_control/firmware/caravel_d2xx.py --help
```

The deployed firmware SHA-256 is
`e7ad11e318b346edaae2fd0ff30736433fb27ef3bc5c39118ab4f1fc0a4107ef`.

## Start the local GUI/API

Create `kc705_cell_control/runs/` if it is absent, then:

```powershell
$env:SENSEEVAL_TARGET = 'zcu106'
python -u kc705_cell_control/gui/server.py --port 8771
```

Open `http://127.0.0.1:8771/`. The API must report revision
`fpga-program-ramp-fast3-measured-v3` and a ready deployment before a hardware
operation is accepted.

## Reproduce the HRS/LRS distribution

Install `numpy` and `Pillow`, then run:

```powershell
python kc705_cell_control/analysis/plot_lrs_hrs_distribution.py
```

The script consumes `results/final_cell_reads.csv` (1024 unique unclipped cells
per state) and recreates the hollow-marker distribution plot under
`kc705_cell_control/output/plots/`. The measured medians are 36.06 uS for HRS
and 93.26 uS for LRS; the best single threshold is 68.51 uS with 97.61%
separation accuracy. Conductance is nominal SET/R10 delta current divided by
the 0.5 V read bias; gain calibration is not claimed.

To recreate the programming-voltage box plots from the compact per-cell export:

```powershell
python kc705_cell_control/analysis/plot_set_reset_transition_voltage.py
```

For SET, the plot reports the rail pair that first produced ten consecutive
reads at or above the 35 uA target. For RESET, no cell reached the <=5 uA
target; the plotted value is explicitly a descriptive 90%-of-observed-response
proxy, not a RESET transition voltage. Hollow markers are individual cells.
The underlying per-cell values and method summary are stored beside the PNG.

## Measured three-point full-array ramp

Normal programming now uses FPGA command 11 with three data-derived rail pairs:

- SET: `(VCC, WL) = (2.30, 0.44), (2.30, 1.09), (2.30, 1.75) V`.
- RESET: `(2.30, 0.94), (2.80, 1.83), (3.00, 2.88) V`.

Command 9 keeps the original 96-step ramp as a diagnostic fallback. On the
attached 1Kbit array, SET job `82f9e6aae8bf433695ba00f20ff4f6b7` completed
in 450.84 s and 1019/1024 cells met the >=35-uA target. It used 176 pulses total
and was 8.72x faster end-to-end than the earlier 96-step SET job. RESET job
`c4756ed4f9044d8f9f0649b0d206d2cb` completed in 313.06 s, but 0/1024 cells met
the <=5-uA HRS target after all three pulses. The scheduler is fast and SET is
effective; these capped RESET pairs are not an effective HRS recipe.

Reproduce the analysis with:

```powershell
python kc705_cell_control/analysis/analyze_fast3_ramp.py `
  --output results/fast3_ramp_1kbit
```

The compact per-cell CSV, summary JSON, and raw Tcl/Vivado text logs are in
`results/fast3_ramp_1kbit/`. The values are commanded DAC targets and nominal,
uncalibrated current estimates; the rails were not independently measured
during these jobs. End-to-end operation is interactive-minute scale rather
than real-time because Vivado/JTAG, reset/READY, reads, MAC readback and cleanup
still dominate the millisecond-scale FPGA ramp.

## Regression tests

```powershell
python -m unittest discover -s kc705_cell_control/tests
node kc705_cell_control/tests/test_gui.mjs
node kc705_cell_control/tests/test_reference_gui.mjs
& 'C:\Xilinx\Vivado\2022.2\bin\xtclsh.bat' kc705_cell_control/tests/test_scan_ramp.tcl
```

The live validation used LRS job `d42d176742d74a90bd4fef034aec5178`
and final HRS/MAC job `30ab5bc5867444e39657ef724e0e33de`. See
`results/run_metadata.json` for all HRS resume segments and source-data hashes.
