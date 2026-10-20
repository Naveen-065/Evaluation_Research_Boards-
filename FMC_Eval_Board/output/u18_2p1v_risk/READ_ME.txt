2.1 V ON THE CARD'S +1V8 RAIL: RISK ASSESSMENT AND NGSPICE RUNS

User-confirmed configuration
Caravel/M.2 module absent. KC705 VADJ is 1.8 V. U18 bias rework has not
been made. The card's nominal +1V8 rail measures 2.1 V.

Decision
Do not accept 2.1 V as the operating rail or connect FMC on that basis.
The reading alone does not establish that any IC has been destroyed.
A steady 2.1 V is within U17's and U18's own reference/supply voltage limits.
However, U17 A-side outputs track that rail and directly reach FPGA inputs.
With VCCO=1.8 V, these inputs have a 2.0 V recommended DC maximum and
2.35 V absolute maximum. Thus 2.1 V is outside normal operation but below
the absolute limit. The latter is a stress ceiling, not an operating target.
Ringing, a further rail rise, or an unpowered FPGA bank changes the risk.

Connectivity correction
U18 pin3/pin4 go to FMC C30/C31, the management I2C channel. On KC705 this
passes through U49 PCA9548A, then to FPGA bank15 at fixed2.5 V. It is NOT
a direct connection to the 1.8 V FMC user-I/O bank. Referring to U18's
card-side signals as direct Kintex pins would be incorrect.
U17 A-side user signals directly reach HR bank12 through J2 LPC or HR
bank16 through J22 HPC. These banks are powered by VADJ.

Local IC assessment
- U17 TXS0108E VCCA operating1.4-3.6V (VCCA<=VCCB), absolute4.6V:
  2.1 V alone is not supply overvoltage for this IC.
- U18 PCA9306 VREF1 absolute7V; its allowed reference range includes2.1V
  with a suitable bias connection. The original direct VREF2 feed is still
  inappropriate and permits uncontrolled current into the lower rail.
- U20 identity differs between PCB and schematic (LVC1G125 versus AUP1T34).
  Both candidate types permit2.1V supply, but the actual marking matters for
  function. No destruction conclusion follows from that voltage alone.
- U7 output should be1.8V. A2.1V reading indicates the output is not being
  held at its intended voltage; it does not prove the regulator is destroyed.
- M.2 pins14/15/35 receive this rail, but the user says the module is absent.
- ADC U14 LVDD and DAC U1 VIO use the distinct +1V8A rail. The U17 reading
  does not establish their supply voltage. Measure +1V8A separately.

New ngspice simulation
Engine: ngspice46 shared library bundled with KiCad10.0.
The rail is held at specified voltages to calculate current entering it.
This is a boundary condition representing the observed voltage, not an LDO
model which proves that voltage remains stable under changing load.

U18 equivalent: three level1 NMOS devices, assumed VTO0.6V, KP0.02A/V^2,
W/L1, no body effect. Actual card pullups are10k. Carrier pullups are4.7k
to3.3V. Both lines are idle. Mux transfer behavior is not simulated.

At held +1V8=2.1 V, nominal equivalent-model results:
Case                              Card I2C idle   Total current into +1V8
Original U18, FMC disconnected       2.627 V          3.705 mA
Corrected U18, FMC disconnected      2.108 V          4.531 uA
Original plus carrier pullups        2.916 V          3.763 mA
Corrected plus carrier pullups       2.916 V          166.180 uA

The original3.705mA value is NOT a measurement or a reliable estimate of
the actual chip current. Sweeping assumed VTO0.4-0.8 and KP0.002-0.2 changed
it from0.209mA to64.120mA. This sensitivity prevents a destruction or thermal
conclusion from a generic model. The model is useful for identifying paths.

Carrier pullup backfeed is independently calculable from the resistors:
Each4.7k-to3.3V /10k-to2.1V pair produces an idle voltage of2.9163V and
81.63uA into +1V8. Two lines inject163.27uA, before U18's own bias current.
At a1.8V rail, the pair gives2.8204V and102.04uA per line. Consequently,
the U18 bias correction alone does not resolve the FMC pullup mismatch.
Do not interpret the corrected standalone result as full FMC approval.

Illustrative unpowered-FPGA current path
A separate generic clamp model connects a2.1V source through4k to an input
with a diode to VCCO. 4k represents TXS's high-state weak pullup only; its
edge accelerators and actual FPGA clamp curves are absent.
Generic diode: IS1e-12A, N1, RS5ohm. At VCCO0V, the model injects0.396mA
per pin. This demonstrates a possible backpower path, not its actual
current, a damage threshold, or permission to power the card into an off FPGA.
At VCCO1.8V, the model leaves the pin near2.099V. Negligible clamp current
does not turn an out-of-range input voltage into a qualified operating point.

Checks and scope
All DC analyses completed without solver warnings. U18 rail current balance
was checked to20nA; the generic clamp balance was checked to1nA.
No silicon breakdown, latchup, thermal/lifetime model, PCB ringing, power
sequencing, actual Kintex IBIS model or encrypted TI model was executed.
NGSPICE CANNOT PREDICT WHETHER OR WHEN A REAL IC WILL BE DESTROYED HERE.
It can expose paths/voltages to compare with manufacturer limits.

Next physical checks
Keep FMC disconnected; use the previous temporary EN-low diagnostic on U18
to establish its role in the2.1V rail. Correct the bias wiring and resolve
R53/R54's connection to the1.8V rail before using KC705 management I2C.
Verify the rail returns to1.8V and inspect startup/shutdown and actual
FMC signal waveforms with a scope. A steady DMM reading misses transients.
The full FMC bring-up checklist remains necessary for other interfaces.

Reproduction
Run python simulate_risk.py with numpy, matplotlib and KiCad's ngspice.dll.
DLLDIR is configured in spice_runner.py. Each .cir can also run in ngspice.
CSV files preserve sweeps, .log files preserve simulator output, results.json
holds numerical results and limitations, risk_results.png summarizes them.
No original PCB or schematic files were changed.

Primary references
AMD DS182, Tables1/2 (Kintex limits):
https://docs.amd.com/api/khub/documents/BhulK6GRrzUpQYw0lzrnMA/content
AMD UG810, Fig1-22 and FMC mapping (KC705 routing):
https://docs.amd.com/api/khub/documents/g0YC14NTyJ_D9ZQTSmzzWg/content
Official KC705 schematic local copy:
../../tmp/interface_limits/kc705_official/kc705_Schematic_xtp132_rev1_1.pdf
TI PCA9306:
https://www.ti.com/lit/ds/symlink/pca9306.pdf
TI TXS0108E:
https://www.ti.com/lit/ds/symlink/txs0108e.pdf
TI PCA9548A:
https://www.ti.com/lit/ds/symlink/pca9548a.pdf
TI U20 candidate parts:
https://www.ti.com/lit/ds/symlink/sn74lvc1g125.pdf
https://www.ti.com/lit/ds/symlink/sn74aup1t34.pdf
