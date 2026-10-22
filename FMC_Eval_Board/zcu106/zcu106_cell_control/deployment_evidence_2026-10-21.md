# ZCU106 deployment evidence — 2026-10-21

- Hardware target: `localhost:3121/xilinx_tcf/Xilinx/11672`
- FPGA: `xczu7` (`xczu7ev-ffvc1156-2-e` build target)
- Device DNA observed: `400200000139E761449063C5`
- Tool: Vivado 2022.2
- Live VADJ reading: **1796.25 mV**, read from the carrier INA226 monitor using
  the carrier-only preflight image.
- Full image: programmed successfully; FPGA DONE asserted.
- Safety state verified live: `run_enable=0`, `dac_enable=0`,
  `adc_clock_running=0`, `adc_reset_n=0`, and `dac_reset_n=0`.
- Timing: WNS 1.616 ns, WHS 0.010 ns, no failing endpoints.
- Routing: 13,518/13,518 routable nets fully routed; no routing errors.
- DRC: no errors or critical warnings. Four warnings originate in generated
  debug-hub/VIO logic and unused diagnostic loads.
- ZCU106 U135 mux readback passed for both slot selections.
- Si5351 address `0x60` returned NACK on both HPC0/J5 and HPC1/J4. Therefore
  the attached setup did **not** prove the final C30/C31 path through the
  mezzanine. Likely causes are: mezzanine absent, unpowered, or its documented
  I2C rework is incomplete. No DAC or ADC startup was attempted.

