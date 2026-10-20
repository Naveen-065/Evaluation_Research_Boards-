KC705 / SenseEval v1.2F — Caravel scan-debug cell read

UI: python gui/server.py --port 8770
Open http://127.0.0.1:8770

Hardware-specific adaptation of Evaluation_Research_Boards- scan-debug protocol.
No SET or RESET programming pulses are provided by this read controller.
Read packet = {0, row[4:0], col[4:0], row[4:0]}, LSB first.
Reset Caravel, wait for firmware READY, 128 clocks idle, one TM setup clock,
18 active-low SE clocks (dummy + 16 data + trailing zero), 2400 clocks hold.
Si5351 CLK0/1 = 2 MHz; ADC has a separate 10 MHz clock and remains 10 MSPS.
Integration omits the last scan-clock interval before TM falls (~11,995 samples).

CONFIRMED PHYSICAL CHANGES, 2026-10-20
Caravel installed. Temporary 3.3 kOhm load removed.
R9, R10 and R11 each 56 ohms per user. NT12 removed. NT22 fitted.
NT22 connects DAC14 to VDDA1; target 3.0 V, DAC code 999A on 0..5 V range.
DAC15/VCCD2 remains 1.8 V. DAC5/VDDA2 remains 2.3 V.
Supply channels 5/14/15 are enabled before other analog biases; 10 ms delay.
Do not reuse the previous NT12 profile: it leaves DAC14 powered down.

FMC pin locations, voltage standards, LVDS input termination, management-I2C
electrical settings and existing ADC/DAC port properties are preserved.
SCAN_SI C18/AD21 becomes bidirectional (output only when enabled).
RESET_B D15/AK24 becomes open-drain bidirectional, never drives high.
Both remain LVCMOS18. U17 OE is driven high only by the explicit interface enable.
READY_I is input-only. FT232H ACBUS1 must remain input, ACBUS0 disables UART buffers.

ADC1 = R9 READ / U10, ADC2 = R11 RESET / U13, ADC3 = R10 SET / U11.
Correction verified against PCB pads and schematic: R46/R47 feed ADC2; R39/R40 feed ADC3.
Evaluation scan read uses the SET path with VCC_SET=0.5 V, WL_SET=2.5 V.
All three currents are shown to reveal which supply path responds.
ADC signed differential voltage = (mean_code - 2048) / 2048 volts.
Current estimate = differential voltage / (gain * shunt resistance).
Default gain 7 from 1k R31/R32/R41; fitted gain is not independently calibrated.
Delta current subtracts this read's preceding idle sample mean. It is not a
zero-current calibration and is not automatically pure cell current.
ADC4/5 are retained in JSON/CSV. Clipped results are excluded from the cell map.

RESULT PACKING
result0: [7:0] state, [8] busy, [9] done, [10] fault, [14:11] fault code,
[15] accepted toggle, [31:16] packet, [32] enabled, [33] ready, [34] reset pin,
[35] feedback activity, [36] ADC healthy, [37] clipping, [79:64] idle count,
[95:80] active count, [255:96] five 32-bit idle sums (ADC1 first).
result1: [159:0] five 32-bit active sums (ADC1 first), [219:160] raw ADC snapshot,
[255:224] signature 53435231. OP_SET is always zero.

VERIFICATION / DEPLOYMENT
tb_scan_read.v tests address serialization, timings, sums and fault aborts.
tb_dac_scan.v decodes SPI traffic, checks supply order, codes, settling and reset.
gui/test_server.py tests decoding, units and rejection of invalid captures.
Build must pass setup/hold timing and DRC before programming.
Compare build/port_properties.tsv with ../kc705_adc_capture/build/port_properties.tsv.
Only scan_si/reset_b directions and their output drive/slew are intended differences.

Use the matching FPGA bit/ltx and firmware/scan_read.bin together.
New firmware configures GPIO21/22/35/36 as user inputs and GPIO25..34 as analog;
GPIO1 asserts READY only after pad transfer. D5 stays on after configuration.
Flash via Ubuntu FT232H, with sector backup and full readback verification.
The firmware programmer supports --hold-after and --release for staged startup.
No ReRAM-cell write is performed by firmware.

The GUI accepts hardware reads only after evidence/deployment.json records a
verified deployment and matching file hashes. It does not silently program a bitstream.
Logs/evidence and runs/reads.jsonl retain real results; no demo values are generated.
Network route: existing SSH keys via Ubuntu VM to Windows host 10.0.2.2;
HostKeyAlias verifies the original known Windows host 100.86.99.88.
