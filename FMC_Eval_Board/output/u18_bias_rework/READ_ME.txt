U18 PCA9306 bias rework - PCB inspection and ngspice experiments

Conclusion
The annotated cut, U18 pin 7-to-8 bridge, and R56 replacement with 200 kohm
implement the appropriate translator bias connection on the inspected PCB.
Changing R56 alone does not remove the direct +3V3 connection to pin 7.
This is a wiring correction supported by an illustrative SPICE simulation;
it is not a verified diagnosis of every cause of the measured 2.1 V rail.

Inspected board
CaravelReRAM-SenseEval_v1.2F/CaravelReRAM-SenseEval.kicad_pcb
SHA256: fdca0330dc568658c43d27be3abe488d13d14b2eec15ef8ff8d3f24107006200
Check that the physical board matches this revision before cutting.
No original board or schematic files were changed.

Rework, with all supplies disconnected and FMC unplugged
1. Replace R56 (currently 10 kohm) with 200 kohm.
2. Cut the indicated vertical red front-copper +3V3 trace above C58.
   In the PCB coordinates this is x=91.4 mm, near y=135.0 mm, on the
   0.2 mm-wide segment from y=134.3 to 137.03 mm. Remove only the surface
   copper; do not cut into buried copper. Inspect the gap under magnification.
3. Join U18 pin 7 (VREF2) to pin 8 (EN), the upper two right-side pads in
   the supplied image. Avoid bridging pin 6, immediately below pin 7.
4. The capacitor left attached to this isolated branch is C58, 100 nF.
   Replace it with 100 pF for the usual bias filter, or retain it with
   allowance for a slower enable response. C57 is separate 1.8 V decoupling.

Resulting connections
  +3V3 --- R56 200 kohm ---+--- U18 pin 7 VREF2
                          +--- U18 pin 8 EN
                          +--- C58 --- GND
  +1V8 ----------------------- U18 pin 2 VREF1
The I2C pullups on each side retain their respective 1.8 V and 3.3 V supplies.
The inspected copper has no alternate +3V3 feed into the isolated pin-7/C58
island. Verify this on the physical assembly; a solder bridge can defeat it.

Simulation performed
ngspice-46 shared library supplied with KiCad 10.0, executed through Python.
TI's available encrypted HSPICE model was inspected but NOT executed.
The included .cir files use a generic three-NMOS functional equivalent:
one reference transistor and two I2C pass transistors. A source-only,
idealized 1.8 V regulator allows injected current to raise its output.
This does not model the actual regulator's minimum load or control loop.

Nominal assumptions: MOS threshold 0.6 V, KP 0.02 A/V^2, W/L=1;
10 uF rail capacitance; 50 pF per I2C node; PCB pullups 10 kohm.
Active rail load is assumed, not measured. No parameter was fitted to 2.1 V.

Nominal DC results with 1 mA active rail load
Configuration                     +1V8 rail   EN/pin 8   Reference current
Original circuit                    2.392 V    3.300 V     949 uA
R56 changed to 200 kohm only         2.392 V    3.300 V     949 uA
Cut + bridge + R56 200 kohm          1.800 V    2.421 V     4.40 uA

These are MODEL RESULTS, not predictions of the exact hardware voltages.
Sweeping MOS threshold 0.4-0.8 V and KP 0.002-0.2 A/V^2 at 1 mA load
gave original rail values from 1.800 to 2.801 V; the corrected rail stayed
near 1.800 V. This demonstrates the load/model sensitivity of the fault.

With the corrected wiring, the bidirectional open-drain pulse test passed
lows in both directions. Released levels were about 1.81 V and 3.29 V.
It is a functional check, not an I2C timing qualification.

Startup, with both supplies ramping over 100 us and 1 mA active load:
  C58=100 nF: bias reached 99% of its final value at about 26 ms.
  C58=100 pF: bias reached 99% by the end of the imposed 100 us ramp.
The latter is not a measured intrinsic switching time. The nominal R*C
products are 20 ms and 20 us respectively. If retaining 100 nF, allow at
least 100 ms in initial bench testing and verify settling before bus use.

Very-light-load limitation
Even the corrected circuit injects a few microamps into +1V8. With zero
active load and only a 10 Mohm leakage resistor, the equivalent-model rail
rose to 2.673 V. Adding a 100 kohm bleed from +1V8 to GND restored 1.800 V
in that model. A 100 kohm bleed draws 18 uA at 1.8 V. This can address the
PCA9306 bias-current issue when rail load is too small, but is not a repair
for a faulty regulator or a substitute for correcting U18 wiring. An actual
regulator's own minimum-load requirement must be checked separately.

Bench verification before connecting KC705
Power off: pin 7-to-8 should be near zero ohms. Confirm the cut is open and
there is no direct copper short from the joined bias node to +3V3 or GND.
Do not require an exact 200 kohm in-circuit reading: parallel semiconductor
paths and capacitor charging can affect the resistance measurement.

Power the PCB independently with suitable current limiting, FMC unplugged.
Measure relative to PCB ground after settling:
  R56 supply-side pad:             about 3.3 V
  U18 pin 2 / U17 VCCA:            about 1.8 V
  U18 joined pins 7 and 8:         roughly 2.4 V, device-dependent
  U18 pins 3 and 4, bus idle:      about 1.8 V
  U18 pins 5 and 6, bus idle:      about 3.3 V
The 2.4 V bias node is not the 1.8 V rail. If the rail remains 2.1 V, do not
connect FMC; investigate rail loading, other backfeed paths, and the LDO.
This analysis does not certify other FMC signals, VADJ matching, sequencing,
or KC705 compatibility. Those still require the complete interface checks.

Reproducing the run
Install Python with numpy and matplotlib. The script currently loads
C:/Program Files/KiCad/10.0/bin/ngspice.dll; adjust DLLDIR if needed.
Run: python simulate_rework.py
Alternatively load individual .cir files in ngspice and run their .dc/.tran
analyses. Raw vectors are in the matching CSV files; simulator logs are
included. results.json contains assumptions, numerical results and engine
version. simulation_results.png summarizes the experiments.
The startup warning about a missing spinit is from the embedded installation;
the circuits specify their models and options and all analyses completed.

Primary reference
Texas Instruments PCA9306 datasheet, sections 8.1.2, 8.1.7, 9.2.2.1, 10, 11:
https://www.ti.com/lit/ds/symlink/pca9306.pdf
The datasheet specifies the joined EN/VREF2 bias arrangement, describes
possible LDO output rise from bias current, and discusses filter capacitance.
