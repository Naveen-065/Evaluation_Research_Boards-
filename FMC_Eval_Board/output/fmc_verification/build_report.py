from pathlib import Path
import csv, json, math, hashlib, zipfile
from html import escape

P = Path(__file__).resolve().parent
s = json.loads((P/'simulation_summary.json').read_text())
raw = list(csv.DictReader((P/'fmc_pin_map.csv').open(newline='', encoding='utf-8-sig')))
signals = [r for r in raw if r['lpc_bank']]
assert len(signals) == 36
assert {r['lpc_bank'] for r in signals} == {'12'}
assert {r['hpc_bank'] for r in signals} == {'16'}
with (P/'fmc_signal_map.csv').open('w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=list(raw[0]))
    w.writeheader(); w.writerows(signals)

checks = []
for name in s['cases']:
    for ext in ['cir','csv','log']:
        assert (P/f'{name}.{ext}').is_file(), (name, ext)
    with (P/f'{name}.csv').open(newline='') as f:
        rows = list(csv.reader(f))
    assert len(rows) > 1
    assert all(math.isfinite(float(v)) for row in rows[1:] for v in row)
    checks.append({'case':name, 'rows':len(rows)-1, 'finite':True})
assert len(checks) == 16
assert abs(s['cases']['i2c_opposed_pullups']['bus_V'] - (3.3/4700+1.8/10000)/(1/4700+1/10000)) < 1e-9
assert all(s['cases'][f'dac_ti_ibis_{c}']['2.5']['pin_V'] > s['cases'][f'dac_ti_ibis_{c}']['2.5']['absolute_max_V'] for c in ['typ','min','max'])
assert abs(s['cases']['lvds_termination_100']['differential_peak_mV'] - 350) < .1
assert s['pcb_local_matches_archive']
(P/'validation.json').write_text(json.dumps({'simulation_cases':checks, 'checks':'16 cases finite; opposed-pullup analytical check; all three DAC corners exceed absolute maximum at 2.5 V; nominal LVDS load check; 36 signal mappings; PCB archive equality', 'passed':True}, indent=2))

points = [
 ('PCB input','C23 pad 1','+5V','5.0 V nominal'),
 ('Digital supply','C26 pad 1','+3V3','3.3 V nominal'),
 ('Digital supply','C30 pad 1','+1V8','1.8 V nominal'),
 ('ADC analog supply','C51 pad 1','+3V3A','3.0–3.6 V; target 3.3 V'),
 ('ADC/DAC I/O supply','C54 pad 1','+1V8A','ADC LVDD 1.7–1.9 V; target 1.8 V'),
 ('Negative analog rail','C39 pad 1','-3VA','-3 V nominal; verify polarity'),
 ('Boost output','C9 pad 1 / R14 pad 1','12VPWR','12 V nominal'),
 ('Switched analog rail','R14 pad 2','+12V','12 V nominal if R14 fitted and boost running'),
 ('Carrier VADJ, card disconnected','KC705 J46 pin 15 to pin 16','VADJ','Selected voltage; default is 2.5 V'),
 ('TXS enable','R52 pad 2','FPGA_LOE','Hold LOW during preparation/ramping; <=0.63 V at VCCA=1.8 V'),
 ('Management clock','R54 pad 2','FPGA_SCL / FMC C30','3.3 V domain after correction; must not remain pulled to 1.8 V'),
 ('Management data','R53 pad 2','FPGA_SDA / FMC C31','3.3 V domain after correction; must not remain pulled to 1.8 V'),
 ('DAC chip select','R8 pad 1','AQ1_nCS','0–VIO in operation; nominal high 1.8 V'),
 ('DAC load control','R7 pad 1','AQ1_nLDAC','0–VIO in operation; nominal high 1.8 V'),
 ('DAC reset','R6 pad 1','AQ1_nRST','0–VIO in operation; nominal high 1.8 V'),
 ('ADC chip select','R49 pad 2','FPGA_nCS','Logic state controlled by test design'),
 ('ADC reset','R50 pad 2','FPGA_nADCRST','Default pull-down; release only when ready'),
 ('ADC power down','R51 pad 1','ADC_PD','Default pull-down; HIGH is power-down, not proven isolation'),
 ('ADC input clock','C61 pad 2 / C60 pad 2','FPGA_MCLKIN_P/N','Connector side of AC coupling; scope differentially'),
]
with (P/'measurement_worksheet.csv').open('w', newline='', encoding='utf-8-sig') as f:
    w=csv.writer(f); w.writerow(['Check','Probe point','Net','Expected / condition','Measured','Pass / fail','Notes'])
    for row in points: w.writerow([*row,'','',''])

def table(headers, rows):
    return '<table><thead><tr>'+''.join('<th>'+escape(x)+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+escape(str(x))+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table>'

pin_table=table(['FMC contact','PCB net','J2 LPC ball / bank','J22 HPC ball / bank'],[(r['fmc_pad'],r['net'],r['lpc_fpga_ball']+' / '+r['lpc_bank'],r['hpc_fpga_ball']+' / '+r['hpc_bank']) for r in signals])
point_table=table(['Purpose','Probe point','Net','Expected / condition'],points)
html='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>KC705 FMC pre-connection verification</title><style>
body{font:16px/1.55 system-ui,Segoe UI,sans-serif;color:#172735;background:#edf2f5;margin:0}main{max-width:1100px;margin:28px auto;padding:36px;background:white;border-radius:12px}h1{font-size:30px;margin:0 0 8px}h2{font-size:23px;border-top:1px solid #dce4e9;padding-top:24px;margin-top:30px}h3{font-size:18px}a{color:#076c9b}table{border-collapse:collapse;width:100%;margin:18px 0;font-size:14px}td,th{border:1px solid #ccd8df;text-align:left;vertical-align:top;padding:9px}th{background:#eaf1f6}code{background:#edf2f5;padding:2px 4px}li{margin:10px 0}.stop{padding:18px;border-left:6px solid #b33333;background:#fff0ef}.note{padding:14px;background:#edf7fb;border-left:4px solid #1681a1}.small{font-size:13px;color:#465763}img{max-width:100%;height:auto}nav a{margin-right:16px} @media print{body{background:white}main{margin:0;padding:0}table{font-size:10px}h2{break-after:avoid}tr{break-inside:avoid}.stop{border:2px solid #b33333}}
</style></head><body><main>
<h1>KC705 FMC pre-connection verification</h1><p>CaravelReRAM-SenseEval v1.2F • 17 October 2026 • Electrical review and 16 ngspice simulations</p>
<div class="stop"><b>Current disposition: do not connect or power the assembled pair yet.</b> Direct DAC I/O is incompatible with KC705 default 2.5 V VADJ. The I²C translator wiring also needs correction or isolation. Fitted NT25 parallels local and carrier 3.3 V supplies. Simulation does not qualify the actual soldered board.</div>
<p><b>Assembly status:</b> your latest answer was “fitted” to NT25, NT22, R14 and bottom-side 1206 R63. This report provisionally treats all four as installed. NT12, U20’s actual part marking, and the intended external power source remain unconfirmed. Earlier statements that these links were absent must not be used for this power-up.</p>
<nav><a href="#connector">Connector choice</a><a href="#issues">Required corrections</a><a href="#simulation">Simulation evidence</a><a href="#procedure">Measurement sequence</a><a href="#points">Probe points</a><a href="#pins">Signal map</a></nav>

<h2 id="connector">Which socket works?</h2>
<p><b>Use J2 LPC after resolving the electrical issues.</b> J9 on this PCB is a 160-contact LPC connector, using C/D/G/H rows. The signal mapping also fits the LPC subset of J22 HPC; it does not need the extra HPC contacts.</p>
<table><tr><th>KC705 socket</th><th>Used ordinary signals</th><th>Supply</th><th>Conclusion</th></tr><tr><td>J2 LPC</td><td>All 36 mapped signals in HR bank 12</td><td>Shared VADJ; default 2.5 V</td><td>Preferred socket for this card</td></tr><tr><td>J22 HPC</td><td>Same 36 contacts map to HR bank 16</td><td>Same VADJ</td><td>Possible with different FPGA pin constraints; no voltage advantage</td></tr></table>
<p>Mapping follows <a href="https://docs.amd.com/api/khub/documents/g0YC14NTyJ_D9ZQTSmzzWg/content">AMD UG810 tables 1-28 and 1-29</a>. Mechanical clearance, polarity, connector seating and the actual carrier revision still require inspection. VADJ selection and XDC I/O standards are separate: changing XDC does not change the physical supply.</p>
<p><b>There is no single VADJ setting that fixes the existing full interface:</b></p>
<ul><li><b>1.8 V option:</b> direct DAC/TXS CMOS uses LVCMOS18. ADC LVDS reception can use input-only LVDS_25 with <code>DIFF_TERM=FALSE</code>, external 100 Ω at each FPGA receiver, and compliant input levels. The ADC clock must come from an appropriate external source/driver; native HR LVDS_25 output is unavailable at 1.8 V.</li>
<li><b>2.5 V option:</b> native HR LVDS_25 clock output is supported, but every affected 1.8 V CMOS path needs suitable level translation, including power-off behavior. ADC SPI inputs powered from AVDD=3.3 V themselves tolerate 2.5 V; the DAC and TXS A-side are the main conflicts.</li></ul>
<p>See <a href="https://docs.amd.com/api/khub/documents/IbGcnPFe6eF19RHma_Y~IA/content">UG471 pp91–93</a> and <a href="https://docs.amd.com/api/khub/documents/BhulK6GRrzUpQYw0lzrnMA/content">DS182 tables 1, 2 and 12</a>. Check all other enabled KC705 functions sharing VADJ before changing it.</p>

<h2 id="issues">Issues to resolve before mating</h2>
<ol>
<li><b>DAC input overvoltage.</b> U1 DAC81416 VIO is +1V8A. FMC G12/G13/H13/H14/H20 directly reach SCLK, SDI, CS, LDAC and RESET. Normal inputs must stay within 0–VIO; absolute limit is VIO+0.3 V, or 2.1 V at nominal VIO. Do not use 2.5 V outputs here. <a href="https://www.ti.com/lit/ds/symlink/dac81416.pdf">TI DAC81416 ratings</a>.</li>
<li><b>NT25 ties two 3.3 V sources.</b> Pad 1 is FMC C39 / 3V3FMC; pad 2 is local +3V3 from U6. For independent USB/bench 5 V power, remove/open NT25 and verify isolation before mating. Do not use a fitted link as an improvised power-sharing scheme. The exact regulator reverse current was not modeled.</li>
<li><b>U18 PCA9306 has an incorrect bias connection and incompatible low-side pullups.</b> Actual PCB pin 7 is directly tied to +3V3, pin 2 to +1V8, and pin 8 pulled up through R56=10 kΩ. TI requires a current-limited reference bias; the standard translator circuit ties EN/VREF2 together through a high-value bias resistor. KC705 C30/C31 are a separate 3.3 V I²C bus, regardless of VADJ, while R54/R53 pull them toward 1.8 V. <b>For an initial test without FMC I²C, isolate/remove U18 and R53/R54.</b> Removing U18 alone leaves the conflicting pullups. This also avoids energizing the incorrectly biased translator during standalone tests. A permanent repair must address the voltage domains and bias together; changing only R56 to 200 kΩ is insufficient. See <a href="https://www.ti.com/lit/ds/symlink/pca9306.pdf">PCA9306 sections 8.1 and 10</a>.</li>
<li><b>Check VDDA1 source selection.</b> The actual PCB has NT12 from local +3V3 to vdda1 and NT22 from AQ1_C14 (DAC U1 OUT14, pin 29) to vdda1. If both are fitted, a DAC output and the 3.3 V supply are tied together. Select the intended source, with the other link open; do not rely on the DAC reset state to avoid contention. The DAC powers up with a 10 kΩ output-to-ground path, so both fitted does not necessarily create a hard short at reset, but enabling channel 14 at a different voltage creates source contention. This corrects the earlier PDF-only interpretation of NT12. R14 instead joins boost 12VPWR to local +12V; it does not join the KC705 12 V FMC pins, which are unconnected on this card.</li>
<li><b>Control ownership on shared signals.</b> U17 TXS0108E is enabled by default through R52. Hold its OE low during initial testing and supply ramps. SCAN_SI (C18) is also FT232H ADBUS2, an RTS# output in UART mode; ensure it is an input or isolated before the FPGA drives that signal. RESET_B (D15) is shared with FTDI, the module and a pushbutton to ground. Prevent competing push-pull drivers. Unplugging FTDI USB does not isolate a locally powered FTDI. <a href="https://www.ti.com/lit/ds/symlink/txs0108e.pdf">TXS0108E</a>; <a href="https://ftdichip.com/wp-content/uploads/2024/09/DS_FT232H.pdf">FT232H table 3.4</a>.</li>
<li><b>Verify the fitted U20.</b> PCB value is SN74LVC1G125DCKR: pin 1 tied to 3.3 V would hold /OE high and disable the clock output. The PDF instead names SN74AUP1T34, for which those supply pins implement the intended translation. Inspect its marking before expecting a clock at FMC H19. H19 is also an ordinary, not dedicated clock-capable, FPGA input.</li>
<li><b>JTAG and signal returns.</b> Bottom-side 1206 R63 should link FMC D30 TDI to D31 TDO, close to 0 Ω; do not confuse it with top-side 0805 R63, a 10 kΩ EEPROM pullup. Card-present H2 inserts the FMC into KC705’s JTAG path. Only seven standard ground contacts are assigned GND in the supplied PCB (D22/D25/D28/D37/D39/G1/G8); many adjacent return contacts are unconnected. C34 is GA0 and H2 is presence, not ordinary ground returns. C32 is a standard ground contact but is wired through R55=10 kΩ to +3V3. This is a layout/pin-assignment concern requiring review for high-speed operation, even if low-speed bring-up succeeds.</li>
</ol>

<h2 id="simulation">What was actually simulated</h2>
<p>Ran <b>16 DC/transient cases in ngspice 46</b> using KiCad 10’s shared library. The three powered DAC cases use TI’s actual IBIS input clamp tables, converted to behavioral current sources. The remaining cases are explicitly simplified equivalent circuits. They establish failure mechanisms and sensitivity, not exact fault currents or full-board safety.</p>
<table><tr><th>Case</th><th>Result</th><th>Meaning / model limit</th></tr>
<tr><td>DAC, TI IBIS nominal: VIO 1.8 V, drive 2.5 V</td><td>Pin 2.4981 V; source current 76.4 µA with the modeled pullup</td><td>Exceeds 2.1 V absolute limit despite small current. Also fails all three tested IBIS voltage/process/temperature corners.</td></tr>
<tr><td>Opposed I²C pullups: 4.7 kΩ to 3.3 V and 10 kΩ to 1.8 V</td><td>2.8204 V; 102.0 µA toward 1.8 V per line</td><td>Resistor-only result; the incorrectly biased PCA9306 is not included, so this is not a prediction of the full bus.</td></tr>
<tr><td>NT25 supply conflict, 100 mV mismatch</td><td>0.1 A / 0.4 A / 2 A for assumed total 1 Ω / 0.25 Ω / 0.05 Ω</td><td>Illustrates why regulated outputs must not be directly paralleled. Actual path resistance and regulator reverse behavior are unknown.</td></tr>
<tr><td>Powered card pullups into an unpowered bank</td><td>Generic model raises bank to 0.84–1.35 V after 500 ms</td><td>Assumed eight 4 kΩ pullups, 100 µF and two rail loads; no vendor powered-off FPGA model. Do not perform this fault experiment on KC705.</td></tr>
<tr><td>LVDS simplified 3.5 mA source</td><td>100 Ω gives 350 mV differential magnitude; 50 Ω gives 175 mV</td><td>Check correct receiver termination. The 1 kΩ diagnostic case exceeds the model’s physical validity; its voltage is not a device prediction.</td></tr>
<tr><td>Assumed 1.8 V GPIO line</td><td>Unterminated example: -0.712 to 2.514 V; added 33 Ω example: about 0–1.8 V</td><td>Assumed 25 Ω driver, 50 Ω line, 1 ns flight time, 5 pF input, no clamps. Demonstrates why a scope is necessary. 33 Ω is not a validated value for this PCB.</td></tr></table>
<img src="simulation_results.png" alt="Four simulation plots: DAC overvoltage, supply contention, unpowered rail injection, and transmission-line ringing">
<p class="small">The two generic DAC diode cases are illustrative only; do not substitute them for the TI powered IBIS results or use the powered IBIS model for VIO=0. TI’s encrypted PCA9306 HSPICE model was not usable faithfully in ngspice. Full FPGA IBIS/S-parameter simulation, extracted board parasitics, thermal behavior, soldering faults, firmware and complete supply sequencing are outside this simulation.</p>
<p><a href="simulation_summary.json">Numerical results</a> · <a href="run_simulations.py">Reproduction script</a> · <a href="validation.json">Validation checks</a> · <a href="https://www.ti.com/lit/zip/SLAM334">TI DAC81416 IBIS source</a>. Individual .cir, .csv and .log files are included beside this report. The script needs Python, NumPy, matplotlib, KiCad’s ngspice DLL and the original project/archive at their existing relative locations.</p>

<h2 id="procedure">Step-by-step measurement sequence</h2>
<p class="note"><b>Equipment:</b> DMM, current-limited bench supply, oscilloscope with short ground springs or a suitable differential probe, and ideally a breakout/interposer. If FMC pads are inaccessible, attach insulated temporary test wires with all power removed and check clearance before mating. Do not probe tightly spaced live contacts by hand. A DMM alone cannot qualify overshoot, clock amplitudes or power sequencing.</p>
<ol>
<li><b>Record the actual assembly, with everything disconnected.</b> Confirm NT25, NT22, NT12, R14 and both R63 locations by inspection and continuity. Check connector orientation, bent contacts, solder bridges and component markings, especially U20. Photograph or record the final link states in the worksheet.</li>
<li><b>Resolve source conflicts and isolate bad interfaces first.</b> For independently powered testing open NT25. Select one VDDA1 source. Correct U18 or isolate U18 plus R53/R54. Establish the chosen 1.8/2.5 V interface plan. Hold U17 OE low and resolve FTDI driver ownership. These are preconditions to power tests, not things to discover by connecting the FPGA.</li>
<li><b>DMM resistance and continuity, unpowered.</b> Confirm ground at the probe reference. Measure +5, +3V3, +1V8, +3V3A, +1V8A, -3 V and +12 V to ground in both polarities; allow capacitors to charge and record settled values. A persistent near-zero reading needs investigation; no universal resistance cutoff proves a board safe. Confirm open NT25 separates its pads, and the chosen VDDA1 links give the intended continuity. Verify bottom R63 D30–D31 continuity and no short to neighboring contacts.</li>
<li><b>First PCB-only power.</b> Keep FMC, USB and other power sources disconnected. After correcting/isolating U18, feed the verified 5 V input from a current-limited bench supply. Set the current limit from the enabled-load startup budget, preferably testing isolated power stages first. A full-board startup current budget has not been established here, so an arbitrary 100 mA or 1 A limit is not a qualified setting. If the supply enters current limit, stop and diagnose instead of simply increasing it: rail collapse can violate supply sequencing. Stop for unexpected heating or current. Never combine the bench supply with USB without confirming source isolation.</li>
<li><b>Measure every rail at the accessible points below.</b> Target 5.0, 3.3, 1.8, 3.3A, 1.8A, -3 and +12 V as applicable; check regulator tolerances as well as downstream device limits. Scope startup, ripple and shutdown. ADS5282 requires AVDD 3.0–3.6 V, LVDD 1.7–1.9 V, with the two supplies powered up/down within 10 ms of each other. Stop if any supply overshoots its load’s rating. Confirm VDDA1 is the intended source voltage, not a contested midpoint.</li>
<li><b>Check standalone FMC-facing voltages.</b> With no carrier attached, measure all 36 signal contacts through their accessible nodes and compare them with the pin map. DAC control pullups should be around 1.8 V. Scope clocks and ADC outputs; do not mistake a DMM average for a valid waveform. Test generators must use the correct logic levels. Do not feed 2.5/3.3 V into DAC inputs for verification.</li>
<li><b>Measure the KC705 separately.</b> With the card absent, verify VADJ between <b>J46 pin 15 and pin 16 GND</b>. Confirm numbering from UG810 before touching it. Expect 2.5 V at default settings. If adopting 1.8 V, use the documented KC705 voltage-control procedure and remeasure after a power cycle. Do not assume a jumper change or XDC command changed the rail.</li>
<li><b>Prepare and verify a passive initial FPGA design and a startup sequence.</b> Use the correct J2 or J22 ball map. Unused/shared outputs must remain high impedance; disable unintended pulls and clocks; hold TXS OE low. Check configuration-time behavior too. During start/stop, neither board may drive an unpowered receiver outside its input rating. Controlled carrier-first startup can be considered only after verifying all carrier outputs/pulls are inactive until card rails are valid; shut down card outputs before its rails and keep the carrier powered until card signals decay. If these conditions cannot be guaranteed, add isolation/interposer circuitry. ADC power-down is not a proven high-impedance disconnect.</li>
<li><b>Qualify the waveforms before enabling the complete interface.</b> At nominal 1.8 V VCCO, FPGA recommended input limits are -0.2 to 2.0 V (use measured VCCO+0.2 for the upper bound). DAC operation should stay 0–VIO; 2.1 V is its nominal absolute ceiling, not an operating target. For LVDS, measure both P/N to ground and P−N: common mode must be 0.3–1.5 V and settled differential magnitude 0.1–0.6 V. Typical ADC output is about 1.025/1.375 V on the legs, ±350 mV differential, or 700 mV differential peak-to-peak. With 1.8 V VADJ, fit external 100 Ω at each of the seven FPGA receive pairs; R165 is on the opposite-direction ADC input clock and does not terminate these seven pairs.</li>
<li><b>First mating and staged operation.</b> Only after the above conditions pass, remove all power, verify rails have discharged, mount the card in J2 LPC and secure it. Use the validated supply sequence and monitor both boards’ currents/rails. Confirm the JTAG chain before enabling outputs. Enable one interface at a time: safe CMOS controls at low rate, DAC commands, ADC reset/configuration, then clock and ADC test patterns. Configure ADS5282 DIFF_CLK (register 0x42) before using its differential input clock. Check each stage for contention, heating, rail movement and waveform violations. Do not hot-plug.</li>
</ol>
<p><b>Stop conditions:</b> wrong VADJ; a populated NT25 with independent supplies; both VDDA1 sources connected; uncorrected U18; two drivers on one net; unexplained current/heating; input voltage beyond operating limits; startup or shutdown feeding an unpowered device; or missing LVDS termination. Passing DC rail checks alone does not clear these conditions.</p>

<h2 id="points">Accessible probe points</h2><p>These pad numbers come from the supplied PCB file. Confirm each ground pad with the DMM while unpowered. The table gives nominal targets, not a claim that the fabricated board has already been measured. <a href="measurement_worksheet.csv">Open the blank measurement worksheet</a>.</p>
__POINTS__

<h2 id="pins">Complete ordinary-signal map</h2><p><a href="fmc_signal_map.csv">36-signal CSV</a> · <a href="fmc_pin_map.csv">Full connected-contact audit</a>. FMC power, I²C, JTAG and presence contacts are separate from these ordinary bank pins.</p>
__PINS__

<h2>Source integrity and remaining limitations</h2>
<p>Electrical connectivity was checked against <a href="../../CaravelReRAM-SenseEval_v1.2F/CaravelReRAM-SenseEval.kicad_pcb">the KiCad PCB</a>, with <a href="../../CaravelReRAM-SenseEval_v1.2F.pdf">the supplied schematic PDF</a> as supporting context. They differ in material places, including VDDA1 links and U20’s part value, so the PDF alone is not authoritative for fabrication. The extracted PCB matches the ZIP member byte-for-byte: <code>fdca0330dc568658c43d27be3abe488d13d14b2eec15ef8ff8d3f24107006200</code>.</p>
<p>KiCad DRC reported zero unconnected items; its 76 board violations were library/silkscreen categories. It also found 130 schematic-parity items, including net/field differences and duplicate references. These are not 130 demonstrated shorts, and zero unconnected items does not prove correct design or soldering. <a href="pcb_drc.json">Full DRC output</a>. The source PCB was not modified.</p>
<p>Additional primary references: <a href="https://docs.amd.com/v/u/en-US/Xilinx-XTP132-KC705-Schematics-Rev-1.1">KC705 XTP132 schematic</a>, <a href="https://www.ti.com/lit/ds/symlink/ads5282.pdf">ADS5282 datasheet</a>, <a href="https://www.ti.com/lit/ds/symlink/sn74aup1t34.pdf">SN74AUP1T34</a>, <a href="https://www.ti.com/lit/ds/symlink/sn74lvc1g125.pdf">SN74LVC1G125</a>. The populated device identities, actual rail currents, signal integrity at full rate and FPGA configuration still require hardware verification.</p>
</main></body></html>'''
html=html.replace('__POINTS__', point_table).replace('__PINS__',pin_table)
(P/'KC705_FMC_verification.html').write_text(html, encoding='utf-8')
print(json.dumps({'cases_validated':len(checks), 'signal_pins':len(signals), 'report':str(P/'KC705_FMC_verification.html'), 'worksheet_rows':len(points)}, indent=2))
