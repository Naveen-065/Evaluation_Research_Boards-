# FMC C30/C31 audit and ngspice study

## Routed use on the daughtercard

- J9 C30 (`FPGA_SCL`) connects only to R54 pad 2 and U18 pin 3.
- J9 C31 (`FPGA_SDA`) connects only to R53 pad 2 and U18 pin 4.
- R54 and R53 are 10 kOhm pull-ups to `+1V8`.
- U18 is a PCA9306. Its other bus side, pins 6 and 5, connects through
  `SI5351_SCL` and `SI5351_SDA` to Y3, the Si5351 clock generator.
- These contacts do not control the ADC, DAC, JTAG, or any power rail. Their
  only intended function is programming the Si5351 clock generator.

There is a routed functional error at Y3: net `SI5351_SDA` reaches physical
pin 4 whose symbol function is SCL, and `SI5351_SCL` reaches physical pin 5
whose symbol function is SDA. Therefore the host SCL and SDA functions arrive
swapped at Y3.

## Model

The simulation uses ngspice 46 bundled with KiCad 10. Actual resistor values:

- KC705 C30/C31: 4.7 kOhm pull-ups to 3.3 V.
- Daughtercard C30/C31: R54/R53, 10 kOhm pull-ups to 1.8 V.
- Daughtercard Y3 side: R58/R57, 10 kOhm pull-ups to 3.3 V.
- Corrected U18 bias: pins 7 and 8 joined and R56 = 200 kOhm.

U18 uses a generic level-1 NMOS functional equivalent because the available TI
model is encrypted HSPICE. The powered-off rail load is swept because regulator
reverse-current behavior and the actual unpowered board load are not known.
This is an electrical mechanism model, not a silicon damage or thermal model.

## Principal results

| Case | Result |
|---|---|
| Both boards powered, bus released | C30/C31 = 2.8204 V |
| Current forced into +1V8 | 102.0 uA per line; 204.1 uA total |
| One line pulled low with 10-ohm sink | connector = 12.1 mV; Y3 side = 21.1 mV |
| Total low-state sink current | 1.206 mA |
| KC705 on, card off, 10 kOhm equivalent +1V8 load | card +1V8 rises to 1.902 V |
| KC705 on, card off, 100 kOhm equivalent +1V8 load | card +1V8 rises to 3.074 V |
| Card on, KC705 off, 10 kOhm equivalent carrier load | KC705 3.3-V rail rises to 1.409 V |
| Card on, KC705 off, 100 kOhm equivalent carrier load | KC705 3.3-V rail rises to 1.751 V |

The 2.8204-V idle level is a valid high for the KC705 management-I2C mux in
the nominal powered case, and the modeled low level is good. The concerns are
continuous current into the 1.8-V rail, bidirectional back-power during unequal
power states, and the physical SCL/SDA crossing at Y3.

For initial FMC mating, C30/C31 can be isolated because the passive FPGA test
does not use them. Remove/isolate R53 and R54 and isolate U18 pins 3/4 from the
connector. A permanent functional repair can instead connect the 3.3-V KC705
management bus directly to the correct Y3 SCL and SDA pins with suitable
power-off isolation; no 1.8-to-3.3 translation is inherently required because
both endpoints are 3.3-V I2C devices.

Run `python simulate_i2c.py` to regenerate all `.cir`, `.log`, `.csv`, JSON,
and PNG outputs.
