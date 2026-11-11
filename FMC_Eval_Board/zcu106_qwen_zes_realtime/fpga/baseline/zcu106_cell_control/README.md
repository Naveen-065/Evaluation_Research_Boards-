# ZCU106 HPC0 port

This port maps the existing FMC evaluation project to ZCU106 HPC0/J5.  The
mezzanine uses only the LPC subset of the HPC connector: LA00 through LA16,
CLK0, and the standardized management-I2C pins C30/C31.

## Electrical requirements

- `VADJ_FMC` must be **1.8 V**. The ZCU106 power-up default is 1.8 V, but both
  HPC sockets share this rail, so measure it before first programming and do
  not attach another card that requests a different VADJ.
- FMC LA and CLK0 signals are constrained as LVCMOS18/LVDS.
- C30/C31 are the **3.3 V management-I2C bus**, not VADJ I/O. On ZCU106 the PL
  reaches this bus through U45 and selects HPC0 with U135 at address `0x75`,
  channel value `0x01`.
- The mezzanine must have the management-I2C rework documented in the top-level
  `FMC_Eval_Board/README.md`. An unmodified board is not safe to connect to the
  carrier's 3.3 V management bus.

## Build

Run with Vivado 2022.2 or newer:

```powershell
& 'C:\Xilinx\Vivado\2022.2\bin\vivado.bat' -mode batch -source build_zcu106.tcl
```

The build fails on critical DRC or negative setup/hold slack. Outputs are in
`build/`.

## First deployment

After measuring VADJ at 1.8 V, run:

```powershell
& 'C:\Xilinx\Vivado\2022.2\bin\vivado.bat' -mode batch -source program_safe_and_check_i2c.tcl
```

This leaves the ADC and DAC interlocks off, selects only HPC0, and makes one
read-only access to Si5351 register 0. It does not start the analog rails or ADC.

