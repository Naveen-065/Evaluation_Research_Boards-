# DAC81416 U1 reference-network audit

## Decision

The assembled board does not implement TI's internal-reference network correctly.

- Adding at least 150 nF from U1 pin 33 (`REF`) to ground is required to claim the datasheet reference-noise performance. Its absence is not a direct overvoltage or short-circuit hazard, and the DAC may appear to operate without it.
- Replacing C6 with 330 pF is required before relying on the internal reference. The assembled 100 nF is 303.03 times the specified compensation capacitance. This is a compensation-node error, not extra supply decoupling.

For ADC-only testing, U1 can remain reset/powered down and these defects do not expose the FPGA to a DC overvoltage. Do not enable the DAC/internal reference until the rework is complete. Longer firmware delay is not a substitute for correcting C6 because the unpublished internal loop stability cannot be established.

## BOM, schematic, and PCB findings

- BOM: C6 is grouped with C1-C5 as `100nF`, 1206, LCSC C97946.
- PCB: C6 pad 2 connects only to `Net-(U1-REFCMP)` and pad 1 connects to GND.
- PCB: U1 pin 34 (`REFCMP`) connects to C6 through approximately 2.92 mm of 0.2 mm F.Cu.
- PCB: U1 pin 33 (`REF`) is assigned the isolated `unconnected-(U1-REF-Pad33)` net. There is no trace, via, test point, or capacitor on the net.
- PCB: U1 pin 35 (`REFGND`) connects to GND.
- FPGA DAC sequence: frame `24'h040000` enables the internal 2.5 V reference, so both datasheet components apply to the intended operating mode.

TI's DAC81416 pin table says to connect 150 nF from REF to ground and 330 pF between REFCMP and REFGND. Section 6.3.2 calls 150 nF the recommended minimum for noise filtering and 330 pF the typical compensation capacitor.

## ngspice results and limits

ngspice 46 was run through KiCad's shared library. TI publishes a 0.1 ohm internal-reference output impedance, but its downloadable IBIS model marks REF and REFCMP as `NC`; it has no analog reference-loop model. The simulations are therefore bounded sensitivity checks rather than a transistor-level DAC simulation.

### REF load-pulse sensitivity

The model uses the published 2.5 V source and 0.1 ohm output impedance. A 5 mA, 5 ns load pulse is used only as a repeatable sensitivity stimulus.

| REF capacitor | Maximum simulated REF droop |
|---|---:|
| Missing | 0.500 mV |
| 150 nF | 0.161 mV |

This demonstrates the transient reservoir/filtering role of the capacitor. It does not predict the DAC's actual noise spectrum or internal switching-current waveform.

### REFCMP sensitivity

For any internal resistance, replacing 330 pF with 100 nF causes:

- RC time constant: 303.03 times larger
- Corresponding RC pole frequency: 0.0033 times the intended value

Illustrative example using an assumed 100 kohm internal resistance:

| REFCMP capacitor | Time constant | 99.9% RC settling | Normalized value 1 ms after enable |
|---|---:|---:|---:|
| 330 pF | 33 us | 228 us | 0.99965 |
| 100 nF | 10 ms | 69.1 ms | 0.09516 |

The absolute numbers in this example are not DAC predictions because the internal resistance and loop transfer function are unpublished. The 303.03 ratio is exact from the two capacitor values. An RC model cannot prove whether the real reference loop is stable with 100 nF, which is why a successful DC voltage measurement would not validate the current assembly.

## Rework

1. Remove C6, currently 100 nF, and fit 330 pF C0G/NP0 in its footprint. A smaller capacitor placed nearer U1 is electrically preferable, but replacing the existing footprint is the simplest correction.
2. Add at least 150 nF from U1 pin 33 REF to a quiet ground, preferably U1 pin 35 REFGND or a very short nearby ground connection. A 150 nF or 220 nF X7R part meets the stated minimum. Use insulated fine wire and anchor the capacitor; do not bridge across pin 34.
3. Before enabling the DAC, power the card with U1 held reset/powered down and verify no solder bridge among pins 32-35. Then release the DAC only after REF measures approximately 2.5 V and remains clean on an oscilloscope.

## Reproduction files

- `simulate_reference_network.py`: builds and runs every ngspice case and regenerates the plots/tables.
- `ref_load_pulse_*.cir`: REF output-equivalent netlists.
- `refcmp_R*_*.cir`: REFCMP RC-sensitivity sweep netlists.
- `summary.json`, `refcmp_rc_sweep.csv`, and `ref_load_pulse.csv`: numerical results.
- `ngspice_reference_results.png`: SPICE plots.
- `u1_reference_layout.png`: local geometry reconstructed from KiCad pad and segment coordinates.
