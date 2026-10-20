KC705 J2 LPC audit - 18 October 2026
Open KC705_J2_LPC_audit.html. Current disposition: corrections and measurements required before mating/powering.
21 ngspice cases were executed. validation.json is NUMERICAL validation, not PCB qualification.
J2_signal_map.csv: 36 ordinary signals, all bank12.
measurement_worksheet.csv: ordered probe points and blank measurement fields.
Reproduce with Python3 + numpy/matplotlib and KiCad10 ngspice.dll. Set NGSPICE_DLL_DIR if necessary.
Run run_simulations.py then build_report.py. The original board folder and ZIP are expected two levels above.
The TI IBIS model is included with its original notices. No source PCB was modified.
No physical board measurements were performed remotely. Read all modeling limitations before using results.
