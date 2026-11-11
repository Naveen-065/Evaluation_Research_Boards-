"""Record the user's fitted R9 confirmation without rerunning unchanged simulations."""
from pathlib import Path
import json

root = Path(__file__).resolve().parent
p = root/'r9_bom_audit/audit.json'
audit = json.loads(p.read_text())
audit['bom'].pop('actual_fitted_value_confirmed', None)
audit['bom'].update(R9_user_confirmed_ohms=0.470,
                    R9_confirmation_source='User: yes its .470 ohms',
                    R10_R11_fitted_values_confirmed=False)
audit['interpretation'][2] = ('User confirmed fitted R9 is 0.470 ohms; the 470 ohm simulations '
                             'are comparison cases only and do not describe the fitted R9.')
p.write_text(json.dumps(audit, indent=2)+'\n')

rows = [r for r in audit['simulations'] if r['R9_ohms']==0.47]
r = next(r for r in rows if r['R31_ohms']==1000)
capture = audit['captures'][-1]
table = ''.join(f"<tr><td>{x['R31_ohms'] if x['R31_ohms'] is not None else 'Open'}</td>"
                f"<td>{x['nominal_gain']:.5g}</td><td>{x['ideal_ADC_signal_V']*1000:.5g}</td>"
                f"<td>{x['ideal_ADC_increment_counts']:.5g}</td>"
                f"<td>{x['ngspice_ADC_increment_counts']:.5g}</td></tr>" for x in rows)
report = f'''<!doctype html><html lang="en"><meta charset="utf-8">
<title>Confirmed R9 = 0.470 ohms: U10 gain and ADC1</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;color:#193046;max-width:1000px;margin:40px auto;padding:0 24px}}h1{{font-size:27px}}h2{{font-size:20px}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;padding:8px;border-bottom:1px solid #cdd6df}}.status{{background:#fff1d5;padding:15px}}code{{font-size:15px}}</style>
<h1>R9 = 0.470 Ω → U10 gain → ADC1</h1>
<p class="status"><b>R9 = 0.470 Ω confirmed by the user.</b> Caravel is removed. Load path:
AQ1_C00 → R9 → VCC_READ → 3.3 kΩ → ground. R31's fitted value is still unconfirmed.
The earlier 470 Ω assumption came from the schematic label and does not describe this fitted R9.</p>
<h2>Calculation including U10</h2>
<p>Using the previous measured source voltage of 0.539 V and the design value R31 = 1 kΩ:
INA851 input gain = 1 + 6000/R31 = 7. The PCB leaves G02 pins open, so output-stage gain = 1.
Overall differential gain = 7. R33, R34, R37 and R38 are series resistors and do not set this nominal DC gain.</p>
<p><code>I = 0.539 / (3300 + 0.470) = {r['ideal_load_current_A']*1e6:.4f} µA<br>
Vshunt = I × 0.470 = {r['ideal_shunt_drop_V']*1e6:.4f} µV<br>
VADC,diff(signal) = 7 × Vshunt = {r['ideal_ADC_signal_V']*1e3:.6f} mV<br>
ADC LSB = 2 V / 4096 = 0.48828125 mV<br>
Expected signal increment = {r['ideal_ADC_increment_counts']:.6f} counts</code></p>
<p>The ideal outputs at 1.5 V common mode would be about
{1.5+r['ideal_ADC_signal_V']/2:.6f} V and {1.5-r['ideal_ADC_signal_V']/2:.6f} V.
Actual offsets can move both these voltages and the ADC baseline.</p>
<h2>ngspice results</h2>
<p>TI INA851 PSpice macro-model executed in ngspice 46; an ideal 12-bit, 2 Vpp differential
ADC transfer is applied to its output. The gain-7 simulated loaded-minus-unloaded increment is
{r['ngspice_ADC_increment_counts']:.6f} counts. The approximately 0.10-count difference from
the ideal formula is model behavior, not a measured hardware calibration.</p>
<table><tr><th>R31 (Ω)</th><th>Gain</th><th>Ideal ADC signal (mV)</th><th>Ideal increment</th><th>ngspice increment</th></tr>{table}</table>
<p>These are comparisons, not instructions to replace R31. At this small stimulus, unknown amplifier/ADC
offsets and noise prevent establishing actual gain from a single near-midscale capture.</p>
<h2>FPGA evidence</h2>
<p>After confirmation that Caravel was removed: {capture['samples']} coherent packets at
{capture['sample_rate_hz']/1e6:g} MSPS. ADC1 candidate decoded mean =
{capture['ch1']['candidate_lsb_first_code_mean']:.5f}, range
{capture['ch1']['candidate_lsb_first_code_min']}–{capture['ch1']['candidate_lsb_first_code_max']},
standard deviation = {capture['ch1']['candidate_lsb_first_code_stdev']:.4f} counts.
Capture status and cadence checks pass. Serial bit order has not yet been independently validated by
a known pattern or sufficiently large known analog signal. This is not a calibrated current measurement.</p>
<h2>Evidence and remaining check</h2>
<p>Confirm fitted R31's marking/value to establish intended gain. Direct R9 mV and amplified-output
readings are pending. A new loaded DAC voltage measurement is also pending; calculations use the earlier 0.539 V reading.</p>
<p>The assembly BOM associates R9/R10/R11 with C7420029 while labelling them 470R.
The <a href="https://www.lcsc.com/product-detail/C7420029.html">selected part is 0.47 Ω</a>.
Only R9's fitted value is user-confirmed.
<a href="https://www.ti.com/lit/ds/symlink/ina851.pdf">INA851 gain reference</a>;
<a href="https://www.ti.com/lit/ds/symlink/ads5282.pdf">ADS5282 transfer reference</a>.</p>
<p><a href="r9_bom_audit/audit.json">Full simulation and capture record</a> ·
<a href="comparison_assumed470ohm.html">Archived 470 Ω assumption (not the fitted R9)</a></p>
</html>'''
current = root/'comparison.html'
archive = root/'comparison_assumed470ohm.html'
if current.exists() and not archive.exists():
    old = current.read_text(encoding='utf-8')
    warning = '<p class="status"><b>Archived assumed-470 Ω case. User confirmed R9 = 0.470 Ω. Do not apply these 470 Ω current conversions to the fitted board.</b> <a href="comparison.html">Corrected report</a></p>'
    archive.write_text(old.replace('<h1>', warning+'<h1>', 1), encoding='utf-8')
current.write_text(report, encoding='utf-8')
print('Confirmed R9:', audit['bom']['R9_user_confirmed_ohms'], 'ohms')
print('Nominal U10 gain:', r['nominal_gain'])
print('Current uA:', r['ideal_load_current_A']*1e6)
print('Shunt uV:', r['ideal_shunt_drop_V']*1e6)
print('ADC signal mV:', r['ideal_ADC_signal_V']*1e3)
print('Ideal / ngspice increment:', r['ideal_ADC_increment_counts'], r['ngspice_ADC_increment_counts'])
print('Updated report:', current)
