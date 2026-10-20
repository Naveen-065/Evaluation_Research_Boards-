from pathlib import Path
import json
from html import escape
from datetime import datetime
import zipfile

out=Path(__file__).resolve().parent
s=json.loads((out/'simulation_summary.json').read_text())
cases=s['cases']
rows=[]
for key,label in [('existing_low_steady','Keep PCB; D9 actively LOW'),
                  ('existing_float_steady','Keep PCB; D9 floating'),
                  ('remove_r165_steady','Remove R165 only; D9 actively LOW')]:
    c=cases[key]
    rows.append(f'<tr><td>{label}</td><td>{c["diff_low_plateau_median_V"]:.3f} / {c["diff_high_plateau_median_V"]:.3f} V</td><td>{c["adc_p_min_V"]:.3f} to {c["adc_p_max_V"]:.3f} V</td><td>{c["adc_n_min_V"]:.3f} to {c["adc_n_max_V"]:.3f} V</td></tr>')
stress=[]
for mode in ['existing_low','remove_r165']:
    for kind in ['lumped_sensitivity','assumed_line_sensitivity']:
        cs=[c for c in cases.values() if c['mode']==mode and c['kind']==kind]
        stress.append(f'<tr><td>{mode}</td><td>{kind}</td><td>{min(c["adc_p_min_V"] for c in cs):.3f} V</td><td>{max(c["adc_p_max_V"] for c in cs):.3f} V</td></tr>')
assumptions=''.join(f'<li>{escape(x)}</li>' for x in s['assumptions'])
html=f'''<!doctype html><html lang="en"><meta charset="utf-8"><title>J2 clock: 1.8 V, 50 MHz</title>
<style>body{{font:16px/1.55 system-ui,sans-serif;max-width:1050px;margin:32px auto;padding:0 22px;color:#172633}}h1,h2{{line-height:1.2}}h1{{font-size:32px}}h2{{font-size:22px;margin-top:32px}}table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{padding:9px;border:1px solid #bdcbd5;text-align:left}}th{{background:#eaf2f6}}.notice{{padding:16px;background:#fff1d6;border-left:5px solid #c58115}}code,pre{{background:#edf2f5}}pre{{padding:15px;overflow:auto}}img{{width:100%}}a{{color:#005d91}}small{{color:#526373}}</style>
<h1>Existing J2 clock circuit at 1.8 V and 50 MHz</h1>
<p><b>Clock-only conclusion: no solder changes are required to create a plausible bench-test configuration.</b> Keep C60, C61 and R165. Drive J2 D8 with a 50 MHz LVCMOS18 clock and J2 D9 actively LOW. Configure the ADC differential clock receiver. This supersedes the earlier claim that C60 must be rewired or an external LVDS driver is always needed.</p>
<p class="notice"><b>Simulation supports a candidate, not a verified working board.</b> {s['case_count']} completed ngspice sensitivity runs; numerical checks passed: {s['all_numerical_checks_passed']}. No Kintex IBIS or ADC comparator/PLL model was available. Some assumed line/startup cases exceed ADC voltage limits, so this is not unconditional connection approval. The clock input, 300 MHz return clock, 600 Mbit/s data and remaining power/I2C faults still need validation.</p>
<p><b>BOM checked inside the original ZIP:</b> jlcpcb/production_files/BOM-CaravelReRAM-SenseEval.csv line 28 lists C60/C61 as LCSC C49062, Samsung CL03A104KP3NNNC, 100 nF, 10 V, X5R, +/-10%, 0201. Line 48 lists R165 as LCSC C25076, UNI-ROYAL 0402WGF1000TCE, 100 ohms, +/-1%, 0402. These procurement values match the simulation; the physical assembly has not been inspected. The BOM uses footprint names in its Comment column, so part numbers were checked against the supplier catalog.</p>
<h2>Existing copper and configuration</h2>
<pre>FPGA AE23 / J2 D8 ---+--- C61 100 nF --- ADC U14.58 CLKP
                    |
                 R165 100 ohms
                    |
FPGA AF23 / J2 D9 ---+--- C60 100 nF --- ADC U14.59 CLKN
  driven LOW

ADC DIFF_CLK=1: each clock pin has internal 5 kohm bias to about 1.5 V.</pre>
<p>The low-driven D9 supplies the reference through C60. It has finite output impedance, so R165 causes some CLKN ripple. D9 must not be left floating. These are two ordinary LVCMOS18 output buffers, not a native LVDS output.</p>
<ol><li>Set and verify KC705 VADJ at 1.8 V. XDC does not set the physical rail.</li>
<li>Use LVCMOS18 on both outputs. DRIVE=24 is supported by the HR bank. SLEW=SLOW is an initial bench choice; the generic simulation is not tied to a Vivado DRIVE/SLEW setting.</li>
<li>ADC register 0x42=0x8001 with other fields default selects DIFF_CLK=1. 0x8003 also enables duty-cycle correction. Default DIFF_CLK=0 is unsuitable with this AC-coupled topology.</li>
<li>Hold the clock LOW until both boards and the ADC configuration are ready. Then start continuous 50 MHz clocking. Allow approximately 5 ms for nominal AC-bias settling before evaluating capture; verify actual settling.</li></ol>
<p>Illustrative integration files: <a href="clock_forwarding_example.v">ODDR/OBUF Verilog</a> and <a href="clock_constraints_example.xdc">clock-only XDC fragment</a>. These are not compiled or timing-closed complete designs.</p>
<h2>Nominal simulation results</h2>
<p>Model: ideal 1.8 V source, 25 ohms resistance per FPGA output, 1 ns transitions, 100 nF coupling, 5 kohm ADC bias to 1.5 V, assumed 5 pF per ADC input, no transmission line in this table. The 25 ohms value is illustrative; it does not represent a verified DRIVE=24 buffer.</p>
<table><tr><th>Case</th><th>Differential LOW / HIGH plateaus</th><th>CLKP range</th><th>CLKN range</th></tr>{''.join(rows)}</table>
<p>With the existing circuit, the simple resistor calculation gives 12 mA through R165 during the high half-cycle and about 1.2 V peak-to-peak differential clock. The unattenuated static upper bound at 1.89 V and 99 ohms is about 19.1 mA. DRIVE is not a current limiter; transient currents differ.</p>
<p>Floating D9 can produce impressive-looking edge spikes while the settled differential plateaus approach zero. Peak-to-peak amplitude alone must not be interpreted as valid clock drive.</p>
<img src="clock_comparison.png" alt="Three simulated clock topologies comparing ADC input and differential waveforms">
<h2>Startup, pauses and line sensitivity</h2>
<p>With 100 nF and 5 kohms, the nominal bias time constant is about 0.5 ms. Short steady-state simulations use analytically initialized capacitor charges. Separate runs model the first edges after a long LOW or HIGH pause. They do not simulate the board power sequence or claim the bias settles in 420 ns.</p>
<p>Generic sweeps use output resistance 10/25/60 ohms, supply 1.71/1.89 V, bias 1.425/1.575 V, and additional assumed 50-ohm line ladders with 0.5/1.5 ns delay, 0.5/2 ns edges and 2 ohms total trace loss. These are sensitivity ranges, not vendor PVT corners.</p>
<table><tr><th>Topology</th><th>Model group</th><th>Lowest CLKP</th><th>Highest CLKP</th></tr>{''.join(stress)}</table>
<p>Do not treat these extreme hypothetical numbers as predictions of the PCB. They expose why driver and routing information matter. Compare measured clock pins with their voltage limits throughout start/stop. Removing R165 increases clock amplitude and can worsen ringing and restart excursions; removal is not automatically safer or necessary.</p>
<h2>Minimum physical work for the complete interface</h2>
<p><b>Clock path: zero changes for the first controlled trial.</b> The complete FMC interface is a separate matter. At VCCO=1.8 V, use LVDS_25 input receivers with DIFF_TERM=FALSE and external receiver termination. The five data pairs and two returned-clock pairs need their 100-ohm termination solution. PCB pad connectivity confirms each receive net connects only U14 and J9, with no resistor pads. R165 does not terminate those signals. Put the termination at the FPGA receiving end; a resistor placed arbitrarily far away on the card is not equivalent.</p>
<p>Retain the earlier power audit requirements: NT25 must not join the independently powered 3.3 V regulators; management I2C remains a 3.3 V bus; verify U18/pullup corrections and avoid driving an unpowered FPGA. This clock analysis does not clear these issues or the incomplete FMC ground returns.</p>
<h2>Bench acceptance sequence</h2>
<ol><li>With both boards disconnected and unpowered, confirm C60/C61 and R165 population and the independent power/I2C corrections. Verify external return-pair terminations.</li>
<li>Verify the KC705 1.8 V startup setting with the card disconnected. Use the full audited power sequence; mate only with both boards unpowered.</li>
<li>With both sides valid, set DIFF_CLK=1, hold D9 LOW, then start D8 clock. Begin at 10 MHz if desired, then test the requested 50 MHz.</li>
<li>Probe CLKP and CLKN at the ADC with suitable low-capacitance probes. Do not attach a 50-ohm scope input directly to either ADC clock pin. Record startup, steady state, stop and restart; examine each pin and their difference, duty cycle, and extra zero crossings.</li>
<li>ADC absolute digital-input limits are -0.3 V to min(3.9 V, AVDD+0.3 V); stay comfortably inside, including ringing. These are damage limits, not a functional clock guarantee. A 1.2 Vpp result is a model expectation, not a prescribed acceptance threshold.</li>
<li>After bias settling, check the ADC output test pattern and frame alignment. At 50 MSPS the returned LCLK is 300 MHz and each serialized channel is 600 Mbit/s. Verify error-free capture for the application and sweep phase/timing margins; decimation follows capture.</li>
<li>Then compare a known analog input before/after decimation for noise and distortion. SPICE here cannot predict clock jitter or final SNR.</li></ol>
<h2>Evidence and reproducibility</h2>
<ul><li><a href="https://www.ti.com/lit/ds/symlink/ads5282.pdf">TI ADS5282, pages 3, 23 and 35</a>: clock modes and internal bias.</li>
<li><a href="https://docs.amd.com/v/u/en-US/ds182_Kintex_7_Data_Sheet">AMD DS182, Table 9</a>: LVCMOS18 HR 24 mA drive option.</li>
<li><a href="https://docs.amd.com/v/u/en-US/ug471_7Series_SelectIO">AMD UG471</a>: input-only LVDS at other VCCO, termination requirements.</li>
<li><a href="https://www.lcsc.com/product-detail/C49062.html">LCSC C49062 capacitor</a>; <a href="https://www.lcsc.com/product-detail/C25076.html">LCSC C25076 resistor</a>: resolution of BOM part-number values.</li>
<li><a href="simulation_summary.json">All numerical results and assumptions</a>; <a href="case_summary.csv">summary CSV</a>; <a href="simulate_clock.py">simulation script</a>; netlists/ and logs/ contain every case.</li></ul>
<ul>{assumptions}</ul><small>Run UTC: {escape(s['run_utc'])}. Source PCB SHA256: {s['pcb_sha256']}. Source design and physical hardware were not changed.</small></html>'''
(out/'J2_50MHz_clock_report.html').write_text(html,encoding='utf-8')
with zipfile.ZipFile(out.parent/'J2_50MHz_clock_simulation.zip','w',zipfile.ZIP_DEFLATED) as z:
    for p in out.rglob('*'):
        if p.is_file() and p.suffix not in ['.pyc'] and '__pycache__' not in p.parts:
            z.write(p,Path('j2_clock_50mhz')/p.relative_to(out))
print(out/'J2_50MHz_clock_report.html')
