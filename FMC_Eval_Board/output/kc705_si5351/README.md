# KC705 to Si5351 management-I2C test

The KC705 image maps the generic open-drain I2C bridge to the carrier's fixed
management bus: K21 is SCL, L21 is SDA, both use LVCMOS25, and the transaction
rate is 100 kHz. KC705 R307 already pulls U49 RESET_B high.

The staged tests are:

1. `program_bridge.tcl` loads the volatile JTAG image.
2. `check_kc705_mux.tcl` verifies both lines idle high, writes `0x04` to U49 at
   address `0x74`, and reads the control byte back.
3. `check_si5351.tcl` reads Si5351 status register 0 at address `0x60`, then
   rewrites register 2 with its original value and verifies readback. It does
   not change a clock setting.
4. `program_si5351_2mhz.tcl` applies and verifies the same 25 MHz crystal to
   2 MHz CLK0-2 configuration used in the Evaluation_Research_Boards project.

The bitstream is volatile. Power off before inserting or removing the FMC card,
then reload the bridge after powering the KC705 again.

Before connecting the card, R53 and R54 must be removed and the PCB's crossed
Si5351 SCL/SDA routing must be corrected. The required U18 high-side crossover
is physical pin 6 to the PCB pad/net leading to Y3 pin 4 (SCL), and physical
pin 5 to the PCB pad/net leading to Y3 pin 5 (SDA).

Live carrier-only result on 2026-10-18: SCL=1, SDA=1; U49 acknowledged and its
control register read back `0x04`. The Si5351 address returned address-write
NACK code 4 while the daughtercard was disconnected. A repeated U49 test passed
after that NACK, confirming the bus was released and recovered normally.
