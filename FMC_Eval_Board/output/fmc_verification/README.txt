KC705 FMC verification — 17 October 2026

Open KC705_FMC_verification.html for the findings, connector decision,
simulation limitations, ordered measurement checklist and probe points.

Current disposition: DO NOT CONNECT/POWER THE ASSEMBLED PAIR YET.
The report identifies corrections and checks required before FMC mating.
Physical assembly and measured voltages have not been verified remotely.

simulation_results.png        Four summary plots
simulation_summary.json      Numerical results and model assumptions
measurement_worksheet.csv    Blank measurement record
fmc_signal_map.csv           36 ordinary signal contacts for J2/J22
fmc_pin_map.csv              Complete connected-contact audit
*.cir / *.csv / *.log        16 ngspice circuits, outputs and logs
models/dac81416.ibs           TI source IBIS model
validation.json              Checks of outputs and signal mapping
pcb_drc.json                 Read-only KiCad DRC report
run_simulations.py           Simulation reproduction script
build_report.py              Report/worksheet generation and validation

Reproduction uses Python 3 with NumPy and matplotlib plus the ngspice
shared library bundled with KiCad 10.0. Set NGSPICE_DLL_DIR if needed.
The simulation script expects the original v1.2F project folder and ZIP
two directories above this folder for its source-integrity checks.
Individual .cir files can also be run directly in a compatible ngspice.

The HTML's links to the source PCB/PDF require the original workspace.
All simulation results, charts, pin maps and worksheet are in this package.
No source schematic or PCB was modified.
