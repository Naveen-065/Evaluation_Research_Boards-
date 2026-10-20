# KC705 J2 PCB-safe static image

This image maps exactly the 36 populated ordinary J2 contacts used by the
CaravelReRAM-SenseEval PCB. It does not map or drive management I2C C30/C31,
JTAG, PRSNT, power, ground, or reserved contacts. It has no VIO or arbitrary
per-pin control; every FPGA output takes only its compiled PCB-safe idle level.

The seven ADC differential pairs are input-only `LVDS_25` with
`DIFF_TERM=FALSE`. All ordinary single-ended Bank 12 pins are `LVCMOS18`.
`SCAN_SI` C18 and shared `RESET_B` D15 remain inputs because they have other
owners. The ADC input-clock contacts D8/D9 also remain inputs in this static
image; a later operational image must implement the separately validated
1.8 V clock method.

## Driven state after configuration

| Level | J2 contacts | PCB meaning |
|---|---|---|
| About 1.8 V | C15, H13, H14, H16 | UART TX idle; DAC nCS/nLDAC and ADC nCS inactive |
| About 0 V | C19, D17, D18 | Scan clock/enable/test inactive |
| About 0 V | G12, G13, G15, G16 | DAC/ADC SPI clocks and data idle |
| About 0 V | G18, G19 | ADC_PD deasserted; U17 translator disabled |
| About 0 V | H17, H20 | ADC and DAC reset asserted |

The remaining 21 contacts stay inputs/high impedance. They can float with the
card absent and are not expected to read 1.8 V. `LVCMOS18` defines electrical
limits; it does not turn an input into a supply output.

## Build and program

With Vivado 2026.1:

```text
vivado -mode batch -source build_safe_io.tcl
vivado -mode batch -source program_safe_io_static.tcl
```

The program script targets the known KC705 cable, requires exactly one
`xc7k325t`, clears any debug-probe association, and verifies internal DONE,
the DONE pin, and EOS.

Never insert or remove the FMC card while either board is powered. This is a
volatile JTAG image: a KC705 power cycle removes it. Before a mated test, set
the KC705 configuration mode so an unrelated flash image cannot boot, power
the rails in the validated sequence, and reload this safe image over JTAG.
FPGA firmware cannot control G19 before configuration; the PCB power sequence
must account for R52 pulling U17 OE high during that interval.

C30/C31 remain the separate 3.3 V KC705 management bus. This image neither
changes nor tests the already-validated U18/R53/R54 arrangement.
