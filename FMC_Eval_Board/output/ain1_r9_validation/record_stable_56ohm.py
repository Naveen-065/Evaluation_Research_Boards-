"""Latest stable result after the user reported a loose test connection."""
from pathlib import Path
from datetime import datetime, timezone
import json

root=Path(__file__).resolve().parent
out=root/'r9_56ohm'
fresh=json.loads((out/'ads5282_analog_20261019_212705.summary.json').read_text())
zero=json.loads((out/'ads5282_analog_20261019_212500.summary.json').read_text())
mean=fresh['channels']['1']['candidate_lsb_first_code_mean']
baseline=zero['channels']['1']['candidate_lsb_first_code_mean']
direct=(mean-2048)/2048*1000
change=(mean-baseline)/2048*1000
measurements=json.loads((out/'meter_measurements.json').read_text())
measurements['prior_readings_before_loose_connection_found']=True
measurements['R9_direct_mV_after_connection_fixed']=None
measurements['note']='User reported a loose connection and requested recapture. New ADC1 response agrees approximately with the reported 50 mV amplifier output. Fresh R9 differential reading pending; do not use the earlier conflicting 4/9 mV values for gain identification.'
(out/'meter_measurements.json').write_text(json.dumps(measurements,indent=2)+'\n')
result={'recorded_at_utc':datetime.now(timezone.utc).isoformat(),
        'capture':fresh,'reference_near_zero_capture':zero['source_csv'],
        'ADC1_mean_code':mean,'ADC1_ideal_equivalent_mV_before_offset_correction':direct,
        'ADC1_change_from_near_zero_capture_mV':change,
        'reported_amplifier_differential_mV':50,
        'analog_voltage_agreement':'Approximately agrees with 50 mV meter report after loose connection was addressed.',
        'reference_is_calibrated_zero':False,
        'gain_validation':'Pending fresh direct R9 mV reading after loose connection fix.',
        'R9_user_confirmed_ohms':56,'Caravel_removed':True,'load_ohms_assumed_retained':3300,
        'R31_fitted_value_confirmed':False,'firmware_or_pin_settings_changed_after_restore':False,
        'previous_gain_inferences_superseded':'Earlier gain estimates combined conflicting non-simultaneous readings before a loose connection was found; do not identify R31 from them.'}
(out/'latest_measurement_state.json').write_text(json.dumps(result,indent=2)+'\n')
report=f'''<!doctype html><html lang="en"><meta charset="utf-8"><title>56 Ω shunt: latest ADC1 check</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;color:#193046;max-width:960px;margin:40px auto;padding:0 24px}}h1{{font-size:27px}}h2{{font-size:20px}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;padding:8px;border-bottom:1px solid #cdd6df}}.status{{background:#e5f3e9;padding:15px}}</style>
<h1>56 Ω shunt: ADC1 responds after connection fix</h1>
<p class="status">After the user reported a loose connection, the new capture returned to
<b>{mean:.2f} counts</b>. Its change from the preceding near-zero capture corresponds to
<b>{change:.2f} mV</b>, close to the reported <b>50 mV</b> across R37 pad 2 (+) and R38 pad 2 (−).</p>
<table><tr><th>Check</th><th>Result</th></tr>
<tr><td>ADC1 mean / range</td><td>{mean:.3f} / {fresh['channels']['1']['candidate_lsb_first_code_min']}–{fresh['channels']['1']['candidate_lsb_first_code_max']}</td></tr>
<tr><td>Ideal equivalent ADC differential, before offset correction</td><td>{direct:.3f} mV</td></tr>
<tr><td>Preceding near-zero mean</td><td>{baseline:.3f} counts</td></tr>
<tr><td>Voltage change using that reference</td><td>{change:.3f} mV</td></tr>
<tr><td>Packets / sample rate</td><td>{fresh['coherent_packets']} / 10 MSPS</td></tr>
<tr><td>Capture status and packet cadence</td><td>All checks passed</td></tr>
<tr><td>FMC pin and voltage configuration</td><td>Unchanged</td></tr></table>
<h2>Interpretation</h2><p>The ADC-to-FPGA voltage response agrees approximately with the meter report.
The preceding near-zero capture was not a calibrated zero-input measurement, and ADC offset/noise remain.
A fixed-pattern test and full-range calibration have not been performed.</p>
<h2>U10 gain remains to be measured</h2><p>The earlier input readings conflict: 0.529/0.520 V to ground imply
9 mV, whereas the direct reading was 4 mV. The user subsequently reported a loose connection.
Those readings should not be used to identify R31 or conclude U10's gain is wrong.</p>
<p>With the connection firm, measure R9 pad 2 (+) to pad 3 (−) directly. At a 50 mV output,
7× gain requires about 7.14 mV input. R31 = 1 kΩ gives gain 1 + 6000/1000 = 7;
the fitted R31 value is not confirmed.</p>
<h2>ngspice evidence</h2><p>The TI INA851 model includes U10's gain. For nominal 56 Ω / 3.3 kΩ
and source 0.529 V, it predicts about 8.827 mV across R9 and 61.79 mV signal after 7× gain.
The separate forced-4-mV simulation predicts approximately 28 mV signal at gain 7.
These are conditional predictions; the fresh input reading will select the appropriate comparison.</p>
<p>The same FPGA image was reloaded after the PCB was disconnected. Si5351 10 MHz register readback/PLLA lock,
DAC scan startup, ADC 10 MSPS startup, and all ten return-clock checks passed. No FMC electrical settings changed.</p>
<p><a href="r9_56ohm/latest_measurement_state.json">Latest capture comparison</a> ·
<a href="r9_56ohm/simulation.json">56 Ω ngspice simulations</a> ·
<a href="r9_56ohm/direct4mV/simulation.json">Forced 4 mV amplifier simulation</a></p></html>'''
(root/'comparison.html').write_text(report,encoding='utf-8')
livep=root.parent/'kc705_adc_capture/evidence/live_status.json'
live=json.loads(livep.read_text())
live.update(recorded_at_utc=result['recorded_at_utc'],capture=fresh,
            analog_validation_status='After loose connection addressed, ADC1 response approximately agrees with reported 50 mV U10 output; gain awaits fresh shunt reading.')
livep.write_text(json.dumps(live,indent=2)+'\n')
print('ADC1 mean:',mean,'uncorrected mV:',direct,'change mV:',change)
