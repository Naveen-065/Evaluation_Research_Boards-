U18 ONLY: ORIGINAL 2.1 V RAIL AND POSSIBLE REWORK FAULTS

User confirmed that the cut, bridge and R56 replacement have NOT been made.
The 2.1 V measurement is therefore from the original board, not a failed repair.

Conclusion
Correct U18's bias wiring for enabled 1.8 V / 3.3 V translation: disconnect
pin 7 from its direct 3.3 V feed, join pins 7 and 8, and use R56=200 kohm
to pull that joined node toward 3.3 V. Changing C58 to 100 pF is optional;
retaining 100 nF affects enable/disable timing, not the final DC bias.
The simulations identify possible mechanisms, not a unique hardware fault.

Actual PCB connections (v1.2F)
U18 is PCA9306: pin1 GND, pin2 +1V8, pin3 FPGA_SCL, pin4 FPGA_SDA,
pin5 SI5351_SDA, pin6 SI5351_SCL, pin7 direct +3V3, pin8 EN.
R56 pad1 is +3V3 and pad2 is EN; original R56 is 10 kohm.
R53/R54 are 10 kohm low-side pullups; R57/R58 are 10 kohm high-side pullups.
The previously inspected cut isolates the pin7/C58 island from +3V3.

Reversible diagnostic BEFORE cutting, on this original unmodified circuit
1. Disconnect FMC and turn all power off. Let the rails discharge.
2. Fit a temporary 470 ohm resistor between R56 pad2 (U18 EN/pin8) and GND.
   Leave existing R56=10 kohm in place. Do not connect this to pin7 or a
   signal pin. Verify connections under magnification before powering.
3. Repower the PCB independently with suitable current limiting. Measure
   EN to GND: expected about 0.15 V. This follows the 10k/470 divider and
   strongly reduces the MOS gate voltage; TI does not give a guaranteed
   EN-low input threshold, so verify the actual measured voltage.
4. Measure U18 pin2 to GND and idle low-side pins3/4. Translation is disabled
   during this test. Power off before removing the temporary resistor.

Interpretation
- If pin2 returns to approximately 1.8 V, the enabled U18 path is strongly
  implicated. Perform the permanent bias correction before normal I2C use.
- If pin2 remains 2.1 V while EN is close to ground, normal enabled-channel
  conduction is not a sufficient explanation. Damaged U18 leakage, solder
  bridging, or another source of current may remain. A technician can remove
  U18 with power off and remeasure with FMC disconnected to isolate the IC.
- If voltage remains high even with U18 removed, inspect PCB shorts and
  other +1V8 circuitry. Replacing U18 alone would not address that result.

Actual ngspice results, assumed 1 mA active rail load
Configuration                      Rail     EN      Low-side SCL idle
Original                           2.392 V  3.300 V  2.649 V
R56=200k only                      2.392 V  3.300 V  2.649 V
Pin7/8 bridge but no cut            2.392 V  3.300 V  2.649 V
Cut but no pin7/8 bridge            1.800 V  3.300 V  2.538 V
Cut + bridge + R56=200k             1.800 V  2.421 V  1.811 V
Original + temporary 470ohm EN-GND  1.800 V  0.148 V  1.800 V

A correct supply reading alone does not prove safe low-side I2C levels.
The cut-without-bridge experiment is an example: the rail regulates but EN
remains too high, coupling the 3.3 V side into low-side bus pins.

Other U18-specific cases tested
- Incomplete cut: hypothetical 10 ohm to 1 Mohm residual paths from 3.3 V
  to the joined node bypass R56. Low-resistance paths retain elevated bias
  and rail voltage. These resistances are not measurements of this board.
- R56 left at 10k after cut+bridge: at 50 uA active rail load, simulated
  rail=2.220 V versus 1.800 V with 200k. At 1 mA both regulate; low load
  makes the larger bias current matter. Thus do not treat 10k as equivalent.
- Correct 200k wiring with zero active load: the source-only regulator
  equivalent permits the rail to rise to 2.673 V. Adding a 100k rail-to-GND
  bleed restores 1.800 V in that model. This is a bias-current test, not a
  claim that the actual fixed regulator has a 10 mA minimum load requirement.
- Representative damage bypass: an assumed 1k internal path from pin7
  to pin2 leaves 2.300 V at 1 mA even with EN low. This illustrates why the
  disable test cannot exclude damaged silicon; it does not characterize
  actual damage or imply this resistance is present on the board.

If the complete repair is later made but pin2 still measures 2.1 V
Measure pins7 and8 individually relative to GND and compare:
- Different readings: bridge is absent/open or probing the wrong pins.
- Both near3.3V: inspect incomplete cut, bypass bridge, wrong R56 value,
  pin2 connection and device condition. This is a clue, not a unique fault.
- Both roughly2.7V with pin2=2.1V: bias may simply track the already raised
  rail. At very small rail load, the residual microamp bias may matter;
  after checking the wiring, a temporary100k from +1V8 to GND tests that.
  A voltage drop with added load supports a weak-source explanation but
  does not independently prove which component supplies that current.

Simulation scope and reproducibility
Engine: ngspice-46 shared library from KiCad10.0 on Windows.
PCA9306 equivalent: three level-1 NMOS devices, VTO=0.6V, KP=0.02 A/V^2,
W/L=1, no body effect. These are assumed, not vendor-fitted parameters.
Regulator: source-only behavioral1.8V feedback source, no output sink.
Rail capacitor10uF, leakage10Mohm, bus capacitances50pF. Actual board load
and output sink behavior are unknown. No values were fitted to measured2.1V.
No encrypted TI HSPICE model was executed. No silicon damage model, regulator
loop stability, component tolerances or complete FPGA interface validation.
Each DC solution is checked against rail current balance with a20nA limit.
Numerical recovery warnings in corrected_10k.log precede valid converged
solutions; all final vectors pass the current-balance check.

Run: python simulate_u18_faults.py
Requires numpy, matplotlib and KiCad's ngspice.dll. DLLDIR is configured
in spice_runner.py. Individual .cir files can also be loaded in ngspice.
CSV and LOG files preserve individual runs. results.json records all cases.
u18_fault_results.png summarizes the results. Board source files unchanged.

Primary reference
TI PCA9306 datasheet, especially sections8.1.2,8.1.7,8.4,9.2.2.1 and10:
https://www.ti.com/lit/ds/symlink/pca9306.pdf
