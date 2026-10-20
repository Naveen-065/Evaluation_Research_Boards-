"""Build a J2-only audit from verified pin maps and newly executed SPICE outputs.
No board files are edited. Numerical validation is not hardware qualification.
"""
from pathlib import Path
import csv, json, math, hashlib, zipfile
import re
from html import escape as esc
P=Path(__file__).resolve().parent
S=json.loads((P/'simulation_summary.json').read_text())
rows=list(csv.DictReader((P/'source_signal_map.csv').open(encoding='utf-8-sig')))
assert len(rows)==36 and {r['lpc_bank'] for r in rows}=={'12'}

def table(head,rows):
    return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+esc(x)+'</th>' for x in head)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(str(x))+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table></div>'

directions={
 'FPGA_RX':'PCB -> FPGA','FPGA_TX':'FPGA -> PCB','READY_I':'PCB -> FPGA',
 'SI5351_CLK1_1V8':'PCB -> FPGA; ordinary input, not CC',
 'FPGA_MCLKIN_P':'FPGA -> ADC, differential clock','FPGA_MCLKIN_N':'FPGA -> ADC, differential clock',
 'SCAN_SI':'FPGA -> PCB; FTDI ownership required','RESET_B':'Shared reset; avoid push-pull contention',
}
pins=[]
for r in rows:
    net=r['net']
    direction=directions.get(net,'ADC -> FPGA' if net.startswith(('OUT','LCLK','ADCLK')) else 'FPGA -> PCB')
    pins.append([r['fmc_pad'],net,r['lpc_fpga_ball'],'12 (HR)',direction,r['other_pads']])
with (P/'J2_signal_map.csv').open('w',newline='',encoding='utf-8-sig') as f:
    w=csv.writer(f);w.writerow(['J2 contact','PCB net','FPGA ball','Bank','Intended direction','Accessible connected component pads']);w.writerows(pins)

points=[
 ['01','All power off','C23.1 to C23.2','+5V resistance to GND','Record settled resistance; investigate persistent near-zero.'],
 ['02','All power off','C26.1 / C30.1 / C51.1 / C54.1 to GND','3.3/1.8/3.3A/1.8A resistance','Record each; no universal pass resistance.'],
 ['03','All power off','NT25.1 to NT25.2','Local/carrier power link','Open for independent +5V-powered PCB; check no unintended alternate hard tie.'],
 ['04','All power off','NT12 and NT22','VDDA1 selection','Only intended source path fitted: NT12=LDO3.3, NT22=DAC OUT14.'],
 ['05','All power off','Bottom 1206 R63 pads / D30-D31','JTAG bypass','Continuity approximately probe lead resistance. Do not confuse top 10k R63.'],
 ['06','All power off','FMC J9 pads to circuit pads','Pin mapping / shorts','Verify 36 mapped signals, power, GND and adjacent-pad isolation; account for intentional R165=100 ohm.'],
 ['07','PCB powered alone','C23.1 to C23.2','+5V','5.0V nominal; capture startup/shutdown.'],
 ['08','PCB powered alone','C26.1 / C30.1 to GND','+3V3 / +1V8','3.3V / 1.8V nominal.'],
 ['09','PCB powered alone','C51.1 / C54.1 to GND','ADC AVDD / LVDD','Target3.3V /1.8V; datasheet ranges3.0-3.6 /1.7-1.9V; rails within10ms on/off.'],
 ['10','PCB powered alone','C39.1 / C9.1 / R14.2 to GND','-3VA / boost / downstream+12V','About-3V /12V /12V if R14 fitted. Unfitted R14 disconnects load rail.'],
 ['11','PCB powered alone','U1.9 via its bypass capacitor; R1-R8 supply ends','DAC VIO and pullup domain','As built1.8V; selected2.5V repair must be isolated from ADC1.8A.'],
 ['12','PCB powered alone','U17.2 / U17.19; R52.2','TXS VCCA/VCCB/OE','VCCA selected1.8 or2.5, VCCB3.3, OE low until supplies valid.'],
 ['12a','Corrected2.5V interface, loaded outputs','U17 A-port pins via mapped nodes','TXS input high/low margins','At VCCA2.5V: VIH>=2.1V,VIL<=0.15V. Check actual rails/tolerance; FPGA VOL0.4V guarantee alone does not meet0.15V.'],
 ['13','PCB powered alone','R54.2 / R53.2','FMC C30/C31 management bus','Isolate U18 AND1.8V pullups for first connection, or validate3.3V-domain repair.'],
 ['14','KC705 alone, card absent','KC705 J46.15 to J46.16','VADJ','Measure actual chosen voltage; default2.5V. Recheck after power cycle.'],
 ['15','KC705 alone, card absent','J2 accessible breakout/test fixture','Initial FPGA image','Known mapping; no unintended clocks, drive or pullups during card power transition.'],
 ['16','Corrected interfaces, safe test fixture','R8.1 / R7.1 / R6.1; U1.12/13 accessible traces','DAC control waveform','Stay0..VIO as design target; VIH>=0.7VIO,VIL<=0.3VIO; absolute[-0.3,VIO+0.3] not operating target.'],
 ['17','Corrected interfaces, safe test fixture','Mapped ordinary FPGA input nodes','Kintex HR input waveform','DC recommended[-0.2,VCCO+0.2]V; inspect transient overshoot againstDS182 tables4/5.'],
 ['18','Corrected interfaces, safe test fixture','Seven FPGA receive differential pairs','ADC data1-5 + frame + bit clock','100ohm receiver load; |Vdiff|0.1-0.6V settled and Vcm0.3-1.5V; typical legs1.025/1.375V.'],
 ['19','Corrected interfaces, safe test fixture','C61.2 / C60.2; then ADC sides C61.1/C60.1','ADC differential input clock','Verify100ohm R165 and0.1uF C60/C61 fitted; correct clock range/duty; enable differential clock mode.'],
 ['20','Before mating, all power off','Every rail to GND','Discharge and mechanical seating','No hot plugging; secure standoffs, inspect clearance and connector alignment.'],
 ['21','Mated only after corrections, passive image','Rail/current monitors; JTAG','Staged first connection','No unpowered receiver drive, unexplained heating/current or rail movement; enable one function at a time.'],
]
with (P/'measurement_worksheet.csv').open('w',newline='',encoding='utf-8-sig') as f:
    w=csv.writer(f);w.writerow(['Step','State','Probe point','Check','Expected / interpretation','Measured','Pass / fail','Notes'])
    for row in points:w.writerow(row+['','',''])

validation=[]
for name in S['cases']:
    data=list(csv.reader((P/(name+'.csv')).open()))
    assert len(data)>1 and all(math.isfinite(float(x)) for r in data[1:] for x in r)
    assert (P/(name+'.cir')).exists() and (P/(name+'.log')).exists()
    log=(P/(name+'.log')).read_text().lower()
    assert 'error:' not in log and 'timestep too small' not in log
    validation.append({'case':name,'rows':len(data)-1,'finite':True})
assert len(validation)==21
assert abs(S['cases']['i2c_opposed_pullups']['bus_V']-(3.3/4700+1.8/10000)/(1/4700+1/10000))<1e-8
assert all(S['cases']['dac_ti_ibis_'+c]['2.5']['pin_V']>S['cases']['dac_ti_ibis_'+c]['2.5']['absolute_max_V'] for c in ['typ','min','max'])
assert all(S['cases'][c]['drive_2p5_pin_V']>2.1 for c in ['dac_input2_1p8_series_0','dac_input1_1p8_series_33','dac_input1_1p8_series_1000','dac_input1_1p8_series_0_bare'])
assert abs(S['cases']['lvds_termination_100']['differential_peak_mV']-350)<0.1
assert S['pcb_local_matches_archive']
(P/'validation.json').write_text(json.dumps({'numerical_checks_passed':True,'hardware_qualified':False,'checks':validation,'additional_checks':['21 cases finite and no solver errors','I2C resistor-network analytical match','DAC overvoltage all provided INPUT1 corners, RESET nominal, series-resistor variants','nominal LVDS load calculation','36 J2 signals bank12','PCB matches original ZIP']},indent=2))

issues=[
 ['DAC controls at2.5V into VIO1.8V','G12/G13/H13/H14/H20 directly reach U1.12/13/14/18/19. Nominal absolute input ceiling2.1V.','Hardware: selectively re-reference DAC VIO and relevant pullups to2.5V, or use suitable level translation. Verify power states.','Cannot fix with XDC, reduced clock rate or a series resistor alone.'],
 ['TXS interface voltage / default enable','U17 VCCA=1.8V, VCCB=3.3V; R52 pulls OE high.','For2.5V architecture, selectively move VCCA and OE domain to2.5V; make OE default LOW and enable only after valid supplies.','Firmware after configuration alone cannot control the earlier power ramp.'],
 ['Parallel3.3V sources','NT25: J2 C39 -> local U6 output.','Keep NT25 open for independent5V-powered PCB; confirm no other source ties.','Do not parallel regulators or assume equal nominal voltage makes it safe.'],
 ['Management I2C mismatch and U18 bias','C30/C31 are KC7053.3V management I2C. Card pulls them to1.8V viaR54/R53; U18 pin7 directly3.3V.','Initially isolate U18 plusR53/R54. Permanent solution must fix reference bias, pullups and power-off isolation together.','VADJ or GPIO constraints cannot change the management bus domain.'],
 ['VDDA1 source conflict','Actual PCB: NT12 +3V3->vdda1, NT22 DACOUT14->vdda1.','Fit only selected source link. Verify actual assembly.','DAC programmed to3.3V does not make parallel source operation reliable.'],
 ['FTDI/shared reset contention','SCAN_SI shares FT232H ADBUS2/RTS# path; RESET_B shares FTDI and ground switch.','Configure/isolate competing FTDI outputs; reset should use verified open-drain/tri-state ownership.','Unplugging USB does not isolate an FTDI still powered from the PCB.'],
 ['U20 mismatch / weak clock high','PDF names AUP1T34; PCB valueLVC1G125 has /OE(pin1) tied3.3V, so would be disabled. Output domain presently1.8V.','Identify fitted device. Correct translation to bank domain, or do not use H19 and use KC705 local clock.','H19/AC24 is not a dedicated clock-capable pin; constraints do not change its physical routing.'],
 ['Sparse FMC signal returns','Only7 standard GND contacts connected; many grounds near active high-speed pairs are unconnected. C32 is GND but card has10k to3.3V.','Review/improve ground connection at connector, preferably board revision or engineered interposer; measure signal integrity.','No software or lumped SPICE fix can certify high-speed return paths.'],
 ['ADC channels6-8 absent from FMC','OUT6/7/8 appear at J8, not J9.','Use suitable added differential wiring/interposer or revise PCB if all8 required.','Cannot recover absent copper connections with an FPGA pin assignment.'],
 ['DAC readback absent','U1 SDO pin11 is unconnected.','Verify write commands by output measurements; add physical SDO route for digital readback.','Firmware cannot read an unconnected signal.'],
 ['JTAG bypass','Bottom1206 R63 connectsD30-D31; presenceH2 is grounded.','Fit/verify bypass to maintain JTAG path with card present.','Missing bypass may look like a dead FPGA; not a voltage-protection mechanism.'],
]

html='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>KC705 J2 LPC - pre-connection audit</title><style>
body{margin:0;background:#eef3f6;color:#142936;font:16px/1.6 system-ui,Segoe UI,sans-serif}main{max-width:1120px;margin:24px auto;padding:32px;background:white;border-radius:12px}h1{font-size:30px;line-height:1.2}h2{margin-top:34px;border-top:1px solid #cddbe4;padding-top:20px;font-size:23px}h3{font-size:18px}a{color:#076b96}.alert{border-left:6px solid #b83535;background:#fff0ed;padding:16px}.note{border-left:5px solid #147e94;background:#edf8fb;padding:14px}.scroll{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13px;margin:18px 0}th,td{border:1px solid #cad7df;text-align:left;vertical-align:top;padding:9px}th{background:#e7f0f5}li{margin:8px 0}code{background:#eaf0f4;padding:2px 4px}img{width:100%;height:auto}.small{font-size:13px;color:#45606e}nav{display:flex;gap:18px;flex-wrap:wrap}@media print{body,main{background:white;margin:0;padding:0}h2,h3{break-after:avoid}tr{break-inside:avoid}table{font-size:9px}.scroll{overflow:visible}nav{display:none}}
</style></head><body><main>
<h1>KC705 J2 LPC: electrical audit and pre-connection tests</h1>
<p>CaravelReRAM-SenseEval v1.2F | 18 October 2026 | 21 executed ngspice cases</p>
<div class="alert"><b>Disposition: do not power the assembled PCB/KC705 pair in the present unverified configuration.</b> J2 is the correct connector class, but the current netlist has incompatible I/O domains and supply-sharing paths. The simulation validates specific mechanisms; it does not certify soldering or the complete board.</div>
<p><b>Confirmed by user on18 October:</b> USB-C power; R14 fitted with0ohm; NT12 fitted; NT22 open. Thus VDDA1 is supplied by the local3.3V LDO, and the boost output is connected to local+12V loads. NT25 was described as “as in PCB files”: the board has its0603 footprint and connection, but the production BOM omits it, so actual population is unresolved. For USB-C power, NT25 must be open before mating. Verify both R63 locations and U20's actual marking. PCB connectivity takes precedence over the PDF where they differ.</p>
<nav><a href="#decision">J2 decision</a><a href="#issues">Issues and remedies</a><a href="#sim">Simulation</a><a href="#measure">Measurements</a><a href="#pins">J2 mapping</a></nav>

<h2 id="decision">J2 is pin-compatible; corrections and validation are required</h2>
<p>The PCB uses an LPC connector with C/D/G/H contacts. All36 connected ordinary signals map through KC705 J2 to <b>HR bank12</b>. J22 would map this same subset to HR bank16, with the same VADJ constraints; it does not solve these problems. This report uses only J2 pin assignments. Connector orientation, board clearance and mechanical seating still require inspection.</p>
<p><b>Architecture retaining native FPGA LVDS clocking: J2 bank12 at2.5V, with the affected card I/O domains corrected to2.5V or properly translated.</b> This retains native HR-bank LVDS_25 clock output and receive termination. Do not change the ADC's1.8V supply to2.5V. <b>Updated 1.8V alternative:</b> the existing input-clock hardware can be tested with D8 driven by a 50MHz LVCMOS18 clock and D9 actively driven LOW, both ordinary CMOS outputs, ADC DIFF_CLK=1, and C60/C61/R165 retained. An external clock driver is not necessarily required. Seven external receiver-end100ohm terminations and the remaining interface corrections are still required. See the <a href="../j2_clock_50mhz/J2_50MHz_clock_report.html">225-case follow-up clock simulation</a>, including its startup and model limitations. Neither architecture is hardware-qualified. The2.5V source, tolerance budget, isolation and enable sequence still need design review; never parallel a local2.5V regulator with KC705 VADJ.</p>
<ol>
<li><b>DAC branch:</b> isolate U1 VIO pin9, its bypassC1 and the R1-R8 pullup supply branch from+1V8A, then supply that branch at2.5V. Do not leave the toggle/clear/reset controls with marginal1.8V highs. DAC VIO supports1.7-5.5V. Leave U16 and ADC LVDD on1.8V. Exact cuts/jumpers must be checked on the physical board before rework.</li>
<li><b>TXS branch:</b> isolate U17 pin2 and its bypass supply from+1V8; use2.5V on VCCA while retaining3.3V VCCB. TXS permits this voltage combination. Replace R52's pullup function with a pulldown so OE defaults LOW, and supervise its release. Do not join the whole+1V8 rail to VADJ.</li>
<li><b>TXS logic margin:</b> supported supplies are not sufficient proof of interface margin. At VCCA2.5V, the TXS A-port requires VIH>=2.1V and VIL<=0.15V. Kintex LVCMOS25's guaranteed VOH=VCCO-0.4V/VOL<=0.4V at its stated test currents do not by themselves establish these margins, especially LOW. Evaluate loaded output levels and rail tracking across the intended conditions; if guaranteed margins cannot be established, use suitable direction-controlled translators with compatible input thresholds. A room-temperature scope trace alone is not a worst-case guarantee.</li>
<li><b>Other CMOS:</b> address ADC CS pullupR49, currently to+1V8; a2.5V high otherwise injects roughly70uA through10k toward that rail. Do not move it blindly to an always-on rail that can drive an unpowered ADC. Re-reference/remove it with a verified startup default. For U20, establish a2.5V output domain using the correct part, or physically isolate/omit U20 and use KC705's local clock. Ignoring H19 in firmware alone does not stop it driving an unpowered FPGA.</li>
<li><b>Supply sequence remains a separate requirement.</b> A2.5V voltage plan solves steady-state levels only. Use an appropriately sequenced I/O supply or fail-safe, enable-controlled isolation, so local pullups and carrier outputs cannot drive unpowered receivers. Scope both power-on and power-off. No default assumption about carrier-first or card-first startup is sufficient.</li>
</ol>
<p class="note"><b>What cannot work as-is:</b> bank12 cannot simultaneously provide native LVDS_25 outputs requiring2.5V and LVCMOS18 outputs requiring1.8V. Different XDC values cannot split one physical bank supply. With VADJ1.8V, LVDS_25 <em>input-only</em> use is permitted subject to input limits, external100ohm receiver termination and DIFF_TERM=FALSE; native LVDS_25 output is not.</p>
<p>Primary references: <a href="https://docs.amd.com/api/khub/documents/g0YC14NTyJ_D9ZQTSmzzWg/content">KC705 UG810, tables1-3/1-29 and p75</a>; <a href="https://docs.amd.com/api/khub/documents/IbGcnPFe6eF19RHma_Y~IA/content">UG471 pp91-93</a>; <a href="https://www.ti.com/lit/ds/symlink/dac81416.pdf">DAC81416</a>; <a href="https://www.ti.com/lit/ds/symlink/txs0108e.pdf">TXS0108E</a>.</p>

<h2 id="issues">Issue-by-issue disposition</h2>__ISSUES__
<p><b>Permanent U18 repair:</b> the KC705 C30/C31 bus is a3.3V management bus, independent of VADJ. A possible PCA9306 equal-voltage switch arrangement references VREF1 pin2 to3.3V, removes R53/R54's1.8V pullups, replaces pin7's direct3.3V tie with the200k bias arrangement prescribed by TI, and controls EN independently so the bus disconnects during invalid power states. Use the exact datasheet switch circuit; changing only R56 is insufficient. For initial J2 tests, isolating U18 <em>and</em> R53/R54 is simpler. It disables access to the local Si5351 through FMC until repaired. See <a href="https://www.ti.com/lit/ds/symlink/pca9306.pdf">PCA9306, switch configuration and power recommendations</a>.</p>
<p><b>Ground repair is not a blind jumper instruction:</b> confirm standard GND contacts against J2 before adding bonds. H2 is presence and C34 is GA0; they are not substitute signal-return pins. Long flying ground wires do not recreate the short return paths needed for a high-speed connector.</p>

<h2 id="sim">What the SPICE runs establish</h2>
<p>Executed21 DC/transient circuits in <b>ngspice46</b>, using KiCad10's shared library. Powered DAC cases use the actual TI INPUT1/INPUT2 IBIS clamp tables converted to behavioral current sources. RESET uses INPUT2; CS/LDAC use INPUT1 with their10k pullup, and a separate bare-input case represents SCLK/SDI. Other circuits are deliberately simplified sensitivity examples.</p>
__SIMTABLE__
<img src="simulation_results.png" alt="SPICE plots showing input overvoltage, hypothetical supply contention, back-power mechanism and line-ringing sensitivity">
<p class="small"><b>Do not reproduce the fault conditions on the KC705.</b> The generic-diode DAC currents, hypothetical unpowered-bank voltages and unterminated LVDS voltages are not vendor predictions. The latter model lacks output-compliance limits. The line model assumes25ohm driver resistance,50ohm impedance,1ns flight time and5pF load; no PCB stackup, vias, connector S-parameters or FPGA package model were extracted.33ohm is not a validated damping resistor for this PCB. Numerical validation means the solver/data checks passed, not that the PCB passed.</p>
<p>TI's supplied model has1.8/3.3/5.0V operating models, not2.5V. The proposed2.5V domain repair is supported by the datasheet range, but has not been simulated with an exact2.5V vendor I/O model. The encrypted PCA9306 HSPICE model could not be faithfully used in this ngspice setup. A complete bitstream, multi-rail startup/thermal analysis, actual solder joints and full-rate eye/timing validation are still required.</p>
<p><a href="simulation_summary.json">Numerical results and assumptions</a> | <a href="run_simulations.py">Reproduction script</a> | <a href="validation.json">Numerical checks</a> | <a href="https://www.ti.com/lit/zip/SLAM334">TI IBIS source</a>. Each case includes its .cir deck, .csv data and .log solver output.</p>

<h2 id="measure">Ordered physical verification after the audit</h2>
<p><b>Equipment:</b> DMM, current-limited bench supply, scope with short ground springs or a suitable differential probe, and a breakout/interposer if signal access is limited. Attach insulated test wires with all power removed. Scope ground clips go only to verified board GND; never to an LVDS negative leg or the-3V rail.</p>
<ol>
<li><b>Record assembly and make a correction plan.</b> Keep FMC/USB/external signals disconnected; remove the socketed Caravel module for initial board-only checks. Identify link population and fitted U20. Isolate the conflicting supply and I2C paths before powering. Confirm chosen VDDA1 source and who drives every shared signal.</li>
<li><b>Unpowered DMM checks.</b> Record rail-to-ground resistance in both polarities after settling; inspect sustained near-zero readings. Verify isolated supply domains are not shorted, JTAGD30-D31 bypass is correct, each FMC signal reaches its expected component pad, and neighboring connector contacts have no unintended bridges. Continuity alone cannot prove safety.</li>
<li><b>PCB-only USB-C power tests.</b> Use a verified5V USB-C source with current monitoring and adjustable current limiting, or a bench supply feeding VBUS through a suitable USB-C breakout. Do not combine USB power with a second direct bench supply. Initially use power only: a PC data connection can activate FTDI outputs. Establish an enabled-load current budget before prolonged full-board operation. An arbitrary low current limit can cause rail collapse and invalid sequencing; do not increase it blindly. Monitor current and temperatures, then measure every rail below. Since R14 is fitted, measure both C9 and the downstream+12V rail. Stop if they do not agree within expected trace/link drop.</li>
<li><b>Scope local startup/shutdown.</b> ADS5282 AVDD must be3.0-3.6V and LVDD1.7-1.9V, with the two rails rising/falling within10ms. Measure proposed2.5V I/O domains as well. Check signals relative to their receiver supply throughout the ramp, not merely their final voltage. A supply-fault test belongs on an isolated fixture, not the expensive FPGA.</li>
<li><b>KC705 alone.</b> Confirm J2 pin mapping for the exact board revision; measure VADJ at J46 pin15 relative to pin16GND. For the recommended2.5V plan confirm the actual2.5V value and its startup. Prepare a passive first-test image with no unexpected output clocks/drivers or pulls. Configuration-time behavior and the management bus must be included.</li>
<li><b>Qualify signals with access.</b> Check CMOS high/low levels and overshoot at receiving nodes. Check differential common mode and amplitude with correct receiver termination. At2.5V, choose one100ohm differential termination per FPGA receive pair (internal where permitted or external); avoid double termination. At1.8V use external100ohm and DIFF_TERM=FALSE. R165 terminates the opposite-direction ADC input clock, not the seven ADC-to-FPGA receive pairs.</li>
<li><b>Only then mate J2 with all supplies removed and rails discharged.</b> Seat and support the connector. Apply the validated sequence while monitoring both boards; verify JTAG first. Enable low-rate controls, then ADC reset/initialization, then the correctly configured differential clock and ADC test patterns, one stage at a time. Leave Caravel programming and DAC high-voltage outputs until these pass.</li>
</ol>
<p><b>Candidate USB-C sequence after the stated repairs:</b> with both boards off, mate J2; power KC705 with a verified passive image and valid bank supply; then enable PCB USB-C power; verify local rails; then enable interfaces. For shutdown, stop carrier drive and disable the shared interfaces while both boards are powered, remove PCB USB-C power, wait for card rails and outgoing signals to decay, then switch off KC705. This is conditional on measured configuration-time pulls, management-bus isolation and all input limits; it is not safe to assume it before those checks. A USB-powered card must not remain driving ADC/clock signals into a switched-off KC705. If arbitrary power order must be tolerated, add suitable power-off isolation rather than relying on an operating procedure.</p>
<p class="alert"><b>Stop immediately</b> for an unexpected supply tie, unresolved voltage mismatch, current-limit cycling, unstable/overvoltage rail, competing drivers, rapid unexpected heating, or a signal feeding an unpowered receiver. Do not regard a JTAG connection, an LED, or correct DC rail readings as qualification of the remaining interface.</p>
<h3>Measurement worksheet and electrical targets</h3>
<p>The following pads come from the PCB file. For the named rail capacitors, pad1 is the rail and pad2 is GND. Verify pad identity unpowered. <a href="measurement_worksheet.csv">Blank CSV measurement worksheet</a>.</p>
__POINTS__
<p>For Kintex-7 HR pins, recommended DC input range is-0.2V toVCCO+0.2V; at2.5V this is-0.2..2.7V. LVCMOS25 VIH>=1.7V and VIL<=0.7V. The HR absolute range-0.4V toVCCO+0.55V is a stress limit, not a design target. DS182 separately bounds transient overshoot/undershoot and injection current; do not use those allowances as a normal back-power design. LVDS_25 reception requires valid common-mode and differential levels as well as per-pin limits. [<a href="https://docs.amd.com/api/khub/documents/BhulK6GRrzUpQYw0lzrnMA/content">DS182 tables1,2,4,5,10,12</a>]</p>
<p>ADC output typical levels with100ohm load are1.025/1.375V on the legs, or+/-350mV differential (700mV differential peak-to-peak). These are typical targets, not guaranteed measurements on an unterminated board. [<a href="https://www.ti.com/lit/ds/symlink/ads5282.pdf">ADS5282 digital characteristics and sequencing</a>]</p>

<h2 id="pins">J2-only signal map</h2>
<p>All listed ordinary contacts are in bank12. C30/C31 management I2C, D30/D31 JTAG, H2 presence and supply contacts are separate from these36 pins. LCLK onG6/G7 and frame clock onH4/H5 reach MRCC pairs; ADC input clockD8/D9 reaches an SRCC pair. H19 is ordinary I/O. <a href="J2_signal_map.csv">Download J2-only CSV</a>.</p>
__PINS__

<h2>Source traceability and limits</h2>
<p>The local PCB matches the original ZIP member exactly: SHA256 <code>__HASH__</code>. No source schematic/PCB was edited. Source: <a href="../../CaravelReRAM-SenseEval_v1.2F/CaravelReRAM-SenseEval.kicad_pcb">original KiCad PCB</a>. The supplied PDF is not fully synchronized with that board, notably NT12's rail and U20's value; verified PCB nets and actual assembly must be reconciled before rework.</p>
<p>The previous read-only KiCad DRC found no unrouted items, but it reported schematic/board parity and duplicate-reference problems. That does not certify physical routing quality or the assembled board. The J2 mapping was cross-checked against the official KC705 schematic/UCF and user guide. Primary supporting references: <a href="https://docs.amd.com/v/u/en-US/Xilinx-XTP132-KC705-Schematics-Rev-1.1">KC705 schematic package</a>, <a href="https://ftdichip.com/wp-content/uploads/2024/09/DS_FT232H.pdf">FT232H</a>, <a href="https://www.ti.com/lit/ds/symlink/sn74aup1t34.pdf">AUP1T34</a>, <a href="https://www.ti.com/lit/ds/symlink/sn74lvc1g125.pdf">LVC1G125</a>.</p>
<p><b>Not demonstrated:</b> actual as-built continuity, absence of solder bridges, exact startup current, complete supply-fault behavior, regulator reverse-current behavior, all FPGA configurations, maximum-rate signal integrity, EMI/ESD robustness, or acceptable lifetime. The remaining physical checks are mandatory before claiming the interface works.</p>
</main></body></html>'''

simrows=[
 ['TI input model, VIO1.8V, carrier drive2.5V',f"CS pin {S['cases']['dac_ti_ibis_typ']['2.5']['pin_V']:.4f}V; bare SCLK/SDI {S['cases']['dac_input1_1p8_series_0_bare']['drive_2p5_pin_V']:.4f}V; absolute ceiling2.10V.",'Fails voltage limit. Small clamp current is not protection. RESET nominal and three INPUT1 corners also fail.'],
 ['Series resistor trial at2.5V',f"Extra33ohm: {S['cases']['dac_input1_1p8_series_33']['drive_2p5_pin_V']:.4f}V; extra1kohm: {S['cases']['dac_input1_1p8_series_1000']['drive_2p5_pin_V']:.4f}V.",'Neither fixes the voltage mismatch; no value is recommended as a substitute for translation.'],
 ['NT25 closed, hypothetical100mV supply mismatch','0.1A /0.4A /2A with assumed1ohm /0.25ohm /0.05ohm paths.','Sensitivity only; actual regulator reverse behavior unknown. Open-link case preserves independent3.3/3.4V nodes, no direct bridge current.'],
 ['I2C opposed pullups only','4.7k to3.3V plus10k to1.8V: bus2.8204V,102uA/line into1.8V.','Omits U18 and carrier mux; not a predicted complete-bus waveform. Confirms conflicting bias networks.'],
 ['Simplified LVDS source into receiver load','3.5mA gives350mV differential with100ohm;175mV with double50ohm load.','Receiver termination matters. Unterminated model lacks physical compliance; do not use its extremes as device predictions.'],
 ['Hypothetical line and power-off models','Unterminated assumed GPIO line overshoots; local pullups can lift an unpowered bank.','Qualitative checks motivating scope/sequence validation. No actual FPGA clamp or extracted PCB line model.'],
]
for token,value in [('__ISSUES__',table(['Issue','Evidence','Possible remedy','What does not solve it'],issues)),('__SIMTABLE__',table(['Simulation','Result','Interpretation'],simrows)),('__POINTS__',table(['Step','State','Probe point','Check','Target / interpretation'],points)),('__PINS__',table(['J2 contact','Net','FPGA ball','Bank','Direction / use','Connected pads'],pins)),('__HASH__',S['pcb_local_sha256'])]:html=html.replace(token,value)
def readable(text):
    text=re.sub(r'\b(bank|pin|pad|table|tables|section|figure|register|extra|through|with|about|target|at|to|All|all|default|supports|requires|drive|VIO|VCCA|VCCB|LVDD|AVDD|VADJ)(?=\d)',r'\1 ',text)
    text=re.sub(r'(\d)(mV|V|uA|mA|A|kohm|ohm|ms|ns|pF|uF|MHz|kHz)\b',r'\1 \2',text)
    text=re.sub(r'\b(with|through|pullup|across|before|after|via|its|by|on|from|the|bypass)(?=(?:R\d|C\d|U\d|J\d|NT\d))',r'\1 ',text)
    return text
html=''.join(x if x.startswith('<') else readable(x) for x in re.split(r'(<[^>]+>)',html))
assert '__' not in html
(P/'KC705_J2_LPC_audit.html').write_text(html,encoding='utf-8')
(P/'README.txt').write_text('''KC705 J2 LPC audit - 18 October 2026
Open KC705_J2_LPC_audit.html. Current disposition: corrections and measurements required before mating/powering.
21 ngspice cases were executed. validation.json is NUMERICAL validation, not PCB qualification.
J2_signal_map.csv: 36 ordinary signals, all bank12.
measurement_worksheet.csv: ordered probe points and blank measurement fields.
Reproduce with Python3 + numpy/matplotlib and KiCad10 ngspice.dll. Set NGSPICE_DLL_DIR if necessary.
Run run_simulations.py then build_report.py. The original board folder and ZIP are expected two levels above.
The TI IBIS model is included with its original notices. No source PCB was modified.
No physical board measurements were performed remotely. Read all modeling limitations before using results.
''',encoding='utf-8')
print(json.dumps({'simulations':len(validation),'J2_signals':len(pins),'worksheet_steps':len(points),'hardware_qualified':False,'report':str(P/'KC705_J2_LPC_audit.html')}))
