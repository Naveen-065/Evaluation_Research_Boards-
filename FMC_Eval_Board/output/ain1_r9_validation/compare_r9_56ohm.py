"""Compare the reinitialized 56-ohm capture with the preceding 0.47-ohm test."""
from pathlib import Path
from datetime import datetime, timezone
import json

root = Path(__file__).resolve().parent
out = root/'r9_56ohm'
sim = json.loads((out/'simulation.json').read_text())
new = json.loads((out/'ads5282_analog_20261019_211713.summary.json').read_text())
old = json.loads((root/'load_3k3/ads5282_analog_20261019_202359.summary.json').read_text())
row = next(r for r in sim['results'] if r['R31_ohms']==1000)
measurements = {'R9_pad2_to_ground_V':.529, 'R9_pad3_to_ground_V':.520,
                'R9_direct_differential_mV':None,
                'difference_of_ground_referenced_readings_mV':9.0,
                'R31_fitted_ohms':None, 'U10_direct_output_differential_mV':None,
                'note':'Ground-referenced readings reported to 0.001 V; direct mV measurements pending.'}
(out/'meter_measurements.json').write_text(json.dumps(measurements,indent=2)+'\n')
mean_key = 'candidate_lsb_first_code_mean'
delta = new['channels']['1'][mean_key]-old['channels']['1'][mean_key]
old_drop = .539*.47/(3300+.47)
expected_delta = 2048*7*(row['ideal_shunt_drop_V']-old_drop)
inferred_gain = delta/(2048*(row['ideal_shunt_drop_V']-old_drop))
inferred_rg = 6000/(inferred_gain-1)
result = {
    'recorded_at_utc':datetime.now(timezone.utc).isoformat(),
    'R9_user_confirmed_ohms':56, 'Caravel_removed_user_confirmed':True,
    'load_ohms_assumed_retained':3300, 'R31_ohms_assumed':1000,
    'measured_R9_drop_V':None, 'measured_loaded_DAC_V':.529,
    'meter_measurements':measurements,
    'old_capture':old['source_csv'], 'new_capture':new['source_csv'],
    'old_mean':old['channels']['1'][mean_key], 'new_mean':new['channels']['1'][mean_key],
    'observed_increment_counts':delta, 'expected_increment_counts_between_shunts':expected_delta,
    'expected_new_signal_from_zero_counts':row['ideal_ADC_increment'],
    'ngspice_new_signal_from_zero_counts':row['ngspice_ADC_increment'],
    'source_voltage_measured_V':sim['source_voltage_V'], 'predicted_shunt_drop_mV':row['ideal_shunt_drop_V']*1000,
    'predicted_ADC_signal_mV':row['ideal_ADC_signal_V']*1000,
    'capture_checks_pass':new['all_capture_checks_pass'], 'coherent_packets':new['coherent_packets'],
    'sample_rate_hz':new['mean_packet_rate_hz'],
    'gain_validation':'Pending fresh shunt voltage measurement and fitted R31 confirmation',
    'conditional_effective_gain':inferred_gain,
    'conditional_equivalent_R31_ohms':inferred_rg,
    'inference_conditions':['Assumes nominal 56 ohm and 3.3 kohm, stable ADC/amplifier offsets across reinitialization, correct ADC transfer/decoding, and prior 0.47-ohm source of 0.539 V.',
                            'This is not a measurement or identification of fitted R31. Direct amplifier input/output mV measurements are required.'],
    'serial_alignment_known_pattern_validated':False,
    'hardware_restored':{'same_bitstream_sha256':'7BEE1A0ED7C6C977C6D4ED08F32199E1E37A7B5EACA5F0B35B940FB9DC72F856',
                         'program_done_and_startup_pass':True,
                         'si5351_10MHz_readback_and_PLLA_lock_pass':True,
                         'DAC_scan_sequence_completed':True,
                         'ADC_10MSPS_sequence_completed':True,
                         'ADC_return_clock_windows_passed':10,
                         'FMC_electrical_settings_changed':False,
                         'DAC_ADC_register_readback':False},
    'excluded_capture':'ads5282_analog_20261019_211229.csv: acquired before reinitialization following PCB disconnection',
    'interpretation':'ADC1 changes in the expected direction while other channels remain near their earlier values; signal-path response is observed, but the magnitude does not yet validate gain 7. No calibrated current is claimed.'
}
(out/'comparison.json').write_text(json.dumps(result,indent=2)+'\n')
channels=''.join(f"<tr><td>{ch}</td><td>{old['channels'][str(ch)][mean_key]:.3f}</td><td>{new['channels'][str(ch)][mean_key]:.3f}</td></tr>" for ch in range(1,6))
report=f'''<!doctype html><html lang="en"><meta charset="utf-8"><title>56 Ω shunt test: FPGA and ngspice</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;color:#193046;max-width:960px;margin:40px auto;padding:0 24px}}h1{{font-size:28px}}h2{{font-size:20px}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;padding:8px;border-bottom:1px solid #cdd6df}}.status{{background:#fff1d5;padding:15px}}</style>
<h1>56 Ω shunt: ADC1 response after reinitialization</h1>
<p class="status"><b>ADC1 increased by {delta:.2f} counts.</b> User replaced R9 with 56 Ω and confirmed Caravel is removed.
The assumed retained load is VCC_READ → 3.3 kΩ → ground. User measured 0.529 V and 0.520 V at R9's sense pads.
Direct mV readings and fitted R31 confirmation are pending.</p>
<h2>Hardware restored</h2><p>Reloaded the same FPGA bitstream; no FMC pin, IO-standard or VADJ changes.
Si5351 10 MHz register readback and PLLA lock passed. The original DAC scan profile and ADC 10 MSPS
startup sequences completed. All ten returned-clock windows passed (ADCLK 10 MHz, LCLK 60 MHz).
SPI sequence completion establishes command transmission, not DAC/ADC register readback.</p>
<h2>Captured values</h2><p>{new['coherent_packets']} coherent packets, one every 100 ns. Capture status and cadence checks passed.</p>
<table><tr><th>ADC channel</th><th>Previous 0.47 Ω shunt</th><th>New 56 Ω shunt</th></tr>{channels}</table>
<p>ADC1 range: {new['channels']['1']['candidate_lsb_first_code_min']}–{new['channels']['1']['candidate_lsb_first_code_max']};
standard deviation {new['channels']['1']['candidate_lsb_first_code_stdev']:.3f} counts.
LSB-first decoding is consistent with the commanded format; independent known-pattern validation is pending.</p>
<h2>Simulation including U10 gain</h2><p>Using the new 0.529 V source reading, assumed 3.3 kΩ load, and R31 = 1 kΩ:
U10 gain = (1 + 6000/1000) × 1 = 7.</p>
<table><tr><th>Quantity</th><th>Prediction</th></tr>
<tr><td>Current: 0.529 / (3300 + 56)</td><td>{row['ideal_current_A']*1e6:.3f} µA</td></tr>
<tr><td>Across R9</td><td>{row['ideal_shunt_drop_V']*1000:.4f} mV</td></tr>
<tr><td>ADC differential signal after U10 ×7</td><td>{row['ideal_ADC_signal_V']*1000:.4f} mV</td></tr>
<tr><td>Ideal ADC increase from zero input</td><td>{row['ideal_ADC_increment']:.3f} counts</td></tr>
<tr><td>ngspice loaded-minus-unloaded increase</td><td>{row['ngspice_ADC_increment']:.3f} counts</td></tr>
<tr><td>Expected increase from previous 0.47 Ω test</td><td>{expected_delta:.3f} counts</td></tr>
<tr><td>Observed increase</td><td>{delta:.3f} counts</td></tr></table>
<p>TI INA851 macro-model runs in ngspice 46; ADC transfer is ideal static 12-bit / 2 Vpp.
The observed magnitude is lower than this conditional prediction. The two meter readings differ by about 9 mV,
consistent with the divider calculation within their reported precision.</p>
<p>If the resistor values are nominal, the ADC decoding/transfer is correct, and offsets remained stable,
the change corresponds to effective gain {inferred_gain:.3f}, equivalent to R31 ≈ {inferred_rg/1000:.3f} kΩ.
This does not identify the fitted resistor. Measure directly between R37 pad 2 (+) and R38 pad 2 (−),
and directly across R9 sense pads, to distinguish amplifier gain from ADC conversion/offset effects.</p>
<p>The initial capture before reinitialization is excluded: the user had disconnected the PCB for rework,
so FPGA sequence-complete flags did not establish the daughter's current register state.</p>
<p><a href="r9_56ohm/comparison.json">Comparison evidence</a> · <a href="r9_56ohm/simulation.json">ngspice results</a> ·
<a href="comparison_0p47ohm.html">Previous 0.47 Ω report</a></p></html>'''
current=root/'comparison.html'
archive=root/'comparison_0p47ohm.html'
if not archive.exists():
    archive.write_text(current.read_text(encoding='utf-8'),encoding='utf-8')
current.write_text(report,encoding='utf-8')
live_path=root.parent/'kc705_adc_capture/evidence/live_status.json'
live=json.loads(live_path.read_text())
live.update(recorded_at_utc=result['recorded_at_utc'],capture=new,
            last_reinitialization_reason='PCB disconnected to replace R9 with 56 ohms',
            R9_user_confirmed_ohms=56,Caravel_installed=False,
            independent_gain_validation_pending=True)
live_path.write_text(json.dumps(live,indent=2)+'\n')
print(json.dumps(result,indent=2))
