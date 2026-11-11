"""Final measured-input comparison after loose connection was addressed."""
from pathlib import Path
from datetime import datetime, timezone
import json
import simulate_ain1 as base

root=Path(__file__).resolve().parent
out=root/'r9_56ohm'
simdir=out/'direct8mV'
simdir.mkdir(exist_ok=True)
base.ROOT=simdir
engine=base.Spice()
results=[]
for rg in [1000,1200]:
    runs={}
    for state,drop in [('zero',0),('measured',.008)]:
        # Sources impose the measured input differential. This isolates U10
        # gain; it is not a prediction of the load's actual resistance.
        net=base.netlist(rg,analysis='.op',load=f'VSENSE_N vcc_read 0 {.529-drop}',dac=.529)
        net=net.replace('R9 dac0 vcc_read 470\n','R9 dac0 vcc_read 56\n')
        d=engine.run(f'rg_{rg}_{state}',net)
        vp=float(d['v(amp1_p)'][0]);vn=float(d['v(amp1_n)'][0])
        runs[state]={'AMP1_P_V':vp,'AMP1_N_V':vn,'ADC_differential_V':vp-vn}
    signal=runs['measured']['ADC_differential_V']-runs['zero']['ADC_differential_V']
    results.append({'R31_ohms':rg,'nominal_gain':1+6000/rg,'runs':runs,
                    'ngspice_output_signal_mV':signal*1000,
                    'ideal_output_signal_mV':8*(1+6000/rg),
                    'ngspice_ADC_signal_counts':signal*2048})

latest=json.loads((out/'latest_measurement_state.json').read_text())
fresh=latest['capture']
measured_output_mV=50.0
input_mV=8.0
result={'recorded_at_utc':datetime.now(timezone.utc).isoformat(),
        'R9_ohms':56,'R9_direct_drop_mV':input_mV,
        'reported_U10_output_mV':measured_output_mV,
        'current_from_meter_shunt_uA':input_mV/1000/56*1e6,
        'approximate_meter_voltage_ratio':measured_output_mV/input_mV,
        'ADC1_mean_code':latest['ADC1_mean_code'],
        'ADC1_ideal_equivalent_mV_before_offset_correction':latest['ADC1_ideal_equivalent_mV_before_offset_correction'],
        'ADC1_change_from_near_zero_capture_mV':latest['ADC1_change_from_near_zero_capture_mV'],
        'apparent_current_from_ADC_change_if_gain7_uA':latest['ADC1_change_from_near_zero_capture_mV']/1000/7/56*1e6,
        'gain7_current_is_calibrated':False,
        'R31_fitted_value_confirmed':False,'simulations':results,
        'simulation_scope':'Forced 8 mV input to TI INA851 model at assumed 0.529 V source-side input; ideal static ADC transfer. Not a full physical-load reconstruction.',
        'conclusion':'Shunt-to-amplifier-to-ADC/FPGA response is observed and amplifier output agrees approximately with ADC voltage change. Exact gain and calibrated current remain unverified.',
        'limitations':['Meter accuracy and resolution were not supplied; input/output readings are approximate.',
                       'The near-zero reference capture was not a deliberate calibrated zero-input measurement.',
                       'R31 must be identified or gain measured at multiple stable input points before choosing a replacement.',
                       'The 1200-ohm case is a comparison only; it does not identify the fitted resistor.',
                       'Earlier 4 mV / 9 mV input readings predated discovery of a loose connection and are superseded by the fresh direct 8 mV report.']}
(simdir/'comparison.json').write_text(json.dumps(result,indent=2)+'\n')
m=json.loads((out/'meter_measurements.json').read_text())
m.update(R9_direct_mV_after_connection_fixed=8.0,
         U10_direct_output_differential_mV=50.0,
         note='Fresh direct R9 reading is 8 mV after loose connection fix. Previously reported U10 output is approximately 50 mV and agrees with the post-fix FPGA voltage response. Exact gain/offset calibration pending.')
(out/'meter_measurements.json').write_text(json.dumps(m,indent=2)+'\n')
latest.update(R9_direct_mV_after_connection_fixed=8.0,
              current_from_meter_shunt_uA=result['current_from_meter_shunt_uA'],
              approximate_meter_voltage_ratio=6.25,
              gain_validation='Approximate reported ratio 6.25; nominal gain7 not independently established. Fitted R31 and calibration remain unverified.',
              final_comparison='direct8mV/comparison.json')
(out/'latest_measurement_state.json').write_text(json.dumps(latest,indent=2)+'\n')
rows=''.join(f"<tr><td>{r['R31_ohms']} Ω</td><td>{r['nominal_gain']:.3f}</td><td>{r['ideal_output_signal_mV']:.3f} mV</td><td>{r['ngspice_output_signal_mV']:.3f} mV</td></tr>" for r in results)
report=f'''<!doctype html><html lang="en"><meta charset="utf-8"><title>56 Ω shunt: measured 8 mV input</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;color:#193046;max-width:960px;margin:40px auto;padding:0 24px}}h1{{font-size:27px}}h2{{font-size:20px}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;padding:8px;border-bottom:1px solid #cdd6df}}.status{{background:#e5f3e9;padding:15px}}</style>
<h1>56 Ω shunt: observed ADC1 response</h1>
<p class="status">After addressing a loose connection, the user measured <b>8 mV across R9</b>.
The reported U10 output is about <b>50 mV</b>; the FPGA change from the near-zero capture is
<b>{result['ADC1_change_from_near_zero_capture_mV']:.2f} mV</b>.
This supports the signal path. Exact gain and calibrated current remain unverified.</p>
<table><tr><th>Quantity</th><th>Result</th></tr>
<tr><td>R9 / direct voltage drop</td><td>56 Ω / 8 mV, user-reported</td></tr>
<tr><td>Current from meter: 0.008 / 56</td><td>{result['current_from_meter_shunt_uA']:.1f} µA</td></tr>
<tr><td>U10 measured output / approximate voltage ratio</td><td>50 mV / 6.25×</td></tr>
<tr><td>ADC1 average / sample rate</td><td>{result['ADC1_mean_code']:.2f} / 10 MSPS</td></tr>
<tr><td>ADC equivalent differential before offset correction</td><td>{result['ADC1_ideal_equivalent_mV_before_offset_correction']:.2f} mV</td></tr>
<tr><td>ADC change from preceding near-zero capture</td><td>{result['ADC1_change_from_near_zero_capture_mV']:.2f} mV</td></tr></table>
<p>The near-zero capture is not a calibrated zero-input reference. Its subtraction is a provisional
comparison; it does not establish current accuracy. With an assumed gain of 7, the ADC voltage change
would imply {result['apparent_current_from_ADC_change_if_gain7_uA']:.1f} µA, compared with about
{result['current_from_meter_shunt_uA']:.1f} µA from the shunt reading.</p>
<h2>ngspice includes U10's gain</h2><p>INA851 differential gain = (1 + 6000/R31) × 1 because
the PCB leaves its G02 pins open. R31 = 1 kΩ gives 7× and predicts 56 mV for an 8 mV input.
The vendor macro-model produces the following signal changes relative to its own zero-input output:</p>
<table><tr><th>Assumed R31</th><th>Gain</th><th>Ideal signal</th><th>ngspice signal</th></tr>{rows}</table>
<p>The 1.2 kΩ case is a comparison only. These approximate readings cannot identify the fitted R31.
Read its marking or measure it with power off (accounting for in-circuit paths), or perform a stable
multi-point input/output gain measurement before selecting a replacement.</p>
<h2>Validation and limits</h2><p>{fresh['coherent_packets']} coherent packets were captured, one every 100 ns;
status and cadence checks passed. The bitstream was restored unchanged, along with Si5351 10 MHz,
the existing DAC scan profile and ADC 10 MSPS settings. All ten return-clock checks passed.
FMC electrical settings were unchanged. ADC/DAC SPI register readback and full-pattern testing were not performed.</p>
<p>Earlier 4 mV and 9 mV input estimates preceded discovery of a loose connection. The fresh 8 mV direct
reading supersedes them for this comparison. Fitted R31 and meter precision remain unconfirmed.</p>
<p><a href="r9_56ohm/direct8mV/comparison.json">Measured-input simulation and comparison</a> ·
<a href="r9_56ohm/latest_measurement_state.json">Latest FPGA capture evidence</a></p></html>'''
(root/'comparison.html').write_text(report,encoding='utf-8')
livep=root.parent/'kc705_adc_capture/evidence/live_status.json'
live=json.loads(livep.read_text())
live.update(recorded_at_utc=result['recorded_at_utc'],R9_measured_drop_mV=8.0,
            analog_validation_status='After connection fix, 8 mV across R9 and approximately 50 mV U10 output reported; FPGA response agrees approximately with output, exact U10 gain and current calibration pending.')
livep.write_text(json.dumps(live,indent=2)+'\n')
print(json.dumps(result,indent=2))
