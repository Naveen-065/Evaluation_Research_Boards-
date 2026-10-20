"""DC sensing range for fitted R9=56 ohms, including U10 and ideal ADC limits.

No hardware is accessed. Noise figures are derived separately from an existing
10-MSPS FPGA capture, not from this DC simulation.
"""
from pathlib import Path
import json, csv
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import simulate_ain1 as base

root=Path(__file__).resolve().parent
out=root/'current_range_56ohm'
out.mkdir(exist_ok=True)
base.ROOT=out
engine=base.Spice()
shunt=56.0
source=.529
rows=[]
arrays={}
for gain,label in [(7.0,'nominal_gain7'),(6.25,'illustrative_gain6p25')]:
    rg=6000/(gain-1)
    net=base.netlist(rg,analysis='.dc ILOAD 0 0.0032 0.000001',dac=source)
    net=net.replace('R9 dac0 vcc_read 470\n','R9 dac0 vcc_read 56\n')
    data=engine.run(label,net)
    current=np.arange(len(data['v(dac0)']))*1e-6
    drop=data['v(dac0)']-data['v(vcc_read)']
    diff=data['v(amp1_p)']-data['v(amp1_n)']
    raw_code=2048+2048*diff
    digitized=np.clip(np.rint(raw_code),0,4095).astype(int)
    crossing=int(np.flatnonzero(diff>=1)[0])
    i_full=float(np.interp(1,diff[crossing-1:crossing+1],current[crossing-1:crossing+1]))
    fitmask=(diff>.1)&(diff<.8)
    slope,intercept=np.polyfit(current[fitmask],diff[fitmask],1)
    with (out/f'{label}.csv').open('w',newline='') as f:
        writer=csv.writer(f)
        writer.writerow(['current_A','shunt_drop_V','VCC_READ_V','AMP1_P_V','AMP1_N_V','ADC_differential_V','ideal_ADC_code_unclipped','ideal_ADC_code_clipped'])
        writer.writerows(zip(current,drop,data['v(vcc_read)'],data['v(amp1_p)'],data['v(amp1_n)'],diff,raw_code,digitized))
    result={'case':label,'nominal_gain':gain,'R31_ohms_assumed':rg,
            'ngspice_fitted_gain':float(slope/shunt),
            'ngspice_zero_current_output_offset_V':float(diff[0]),
            'nominal_ADC_positive_full_scale_mA':1000/(shunt*gain),
            'ngspice_ADC_plus1V_crossing_mA':i_full*1000,
            'current_per_ADC_count_uA':1e6/(2048*shunt*gain),
            'shunt_drop_at_nominal_full_scale_mV':1000/gain,
            'load_voltage_at_nominal_full_scale_V':source-1/gain,
            'shunt_power_at_nominal_full_scale_mW':(1/(shunt*gain))**2*shunt*1000,
            'capture_IS_NOT_hardware_full_scale_test':True}
    rows.append(result)
    arrays[label]=(current,diff,digitized,data)

capture=json.loads((root/'r9_56ohm/ads5282_analog_20261019_212705.summary.json').read_text())
std_codes=capture['channels']['1']['candidate_lsb_first_code_stdev']
lsb_uA=rows[0]['current_per_ADC_count_uA']
samples=[]
current,diff,codes,data=arrays['nominal_gain7']
for uA in [0,1,5,10,50,100,143,500,1000,2000,2300,2500,2551,3000]:
    i=uA*1e-6
    samples.append({'current_uA':uA,'shunt_drop_mV':i*shunt*1000,
                    'ideal_U10_signal_mV':i*shunt*7*1000,
                    'ngspice_ADC_differential_mV':float(np.interp(i,current,diff))*1000,
                    'ideal_offset_free_ADC_code_unclipped':2048+2048*i*shunt*7,
                    'ideal_offset_free_ADC_code_clipped':int(np.clip(round(2048+2048*i*shunt*7),0,4095)),
                    'VCC_READ_V':source-i*shunt,
                    'outside_nominal_ADC_span':i*shunt*7>=1})
summary={'shunt_ohms':shunt,'source_V_assumed':source,'U10_supplies_V':[12,-3],
         'U10_output_common_mode_V':1.5,'U10_clamp_rails_V':[0,3.3],
         'ADC_model':'Ideal static 12-bit, 2 Vpp differential, offset-binary; no ADC transistor/noise/kickback model',
         'current_sweep_A':[0,.0032,1e-6],'results':rows,'examples':samples,
         'nominal_gain7_headroom_target_mA':2.3,
         'existing_capture_noise':{'file':capture['source_csv'],'samples':capture['coherent_packets'],
             'sample_rate_hz':capture['mean_packet_rate_hz'],'stddev_counts':std_codes,
             'equivalent_RMS_current_noise_uA_assuming_gain7':std_codes*lsb_uA,
             'three_sigma_current_scale_uA':3*std_codes*lsb_uA,
             'is_guaranteed_minimum_measurable_current':False,
             'note':'Short hardware capture noise estimate, not an ngspice noise result or a zero-offset calibration.'},
         'ADC_datasheet_offset_equivalent_current_uA':{'typical_0p2_percent_FS':.002*2/(56*7)*1e6,
                                                      'max_abs_1p25_percent_FS':.0125*2/(56*7)*1e6,
                                                      'note':'ADC-only offset before calibration; not total system accuracy.'},
         'shunt_voltage_budget_examples':[{'allowed_drop_mV':v,'maximum_current_uA':v/1000/56*1e6} for v in [10,50,100]],
         'limitations':['R31 fitted value and exact gain have not been independently calibrated; gain6.25 is sensitivity analysis only.',
                        'This is a DC sweep. 10 MSPS sampling does not establish flat 5 MHz current bandwidth or dynamic settling.',
                        'DAC is an ideal source here; its load regulation, output-current limits and device-under-test supply requirements may impose lower usable currents.',
                        'ADC reaches its span boundary before the INA851 model clips in this sweep; no damage threshold is inferred.',
                        'Only forward DAC-to-load current is simulated; reverse-current operation of the physical DAC is not validated.',
                        'Component tolerances, reference errors, offset drift and noise require calibration and hardware validation.'],
         'sources':['https://www.ti.com/lit/ds/symlink/ina851.pdf','https://www.ti.com/product/ADS5282','https://www.ti.com/lit/ds/symlink/ads5282.pdf']}
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')

plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10})
fig,(ax,bx)=plt.subplots(1,2,figsize=(12,4.7))
for gain,label,color in [(7,'nominal_gain7','#2057a5'),(6.25,'illustrative_gain6p25','#9e650d')]:
    i,v,c,d=arrays[label]
    ax.plot(i*1000,c,color=color,lw=2,label=f'Gain {gain:g}'+(' (assumed)' if gain==7 else ' (illustrative)'))
ax.axvline(rows[0]['ngspice_ADC_plus1V_crossing_mA'],color='#aa3333',ls='--',lw=1)
ax.axhline(4095,color='#777',ls=':',lw=1)
ax.annotate('ADC span limit ≈ 2.55 mA\nfor gain 7',(2.55,4095),xytext=(.6,3650),arrowprops={'arrowstyle':'->','color':'#aa3333'},color='#8b2222')
ax.set(xlabel='Forward shunt current (mA)',ylabel='Ideal ADC code applied to ngspice output',xlim=(0,3.2),ylim=(1950,4250),title='56 Ω shunt: current-to-code range')
ax.grid(alpha=.2);ax.legend(loc='lower right')
bx.plot(current*1000,data['v(vcc_read)'],color='#246c45',lw=2,label='VCC_READ after R9')
bx.axvline(2.3,color='#555',ls=':',lw=1,label='2.3 mA: nominal headroom target')
bx.scatter([rows[0]['nominal_ADC_positive_full_scale_mA']],[rows[0]['load_voltage_at_nominal_full_scale_V']],color='#aa3333',zorder=3)
bx.annotate('At ADC limit: about 143 mV\nlost across R9',(2.55,.386),xytext=(.2,.405),arrowprops={'arrowstyle':'->','color':'#aa3333'},color='#8b2222')
bx.set(xlabel='Forward shunt current (mA)',ylabel='Load voltage (V)',xlim=(0,3.2),ylim=(.33,.55),title='Shunt burden with DAC held at 0.529 V')
bx.grid(alpha=.2);bx.legend(loc='upper right',fontsize=9)
fig.text(.5,.012,'DC simulation: TI INA851 model + ideal ADC transfer. Actual current accuracy and dynamic bandwidth are not established.',ha='center',fontsize=9)
fig.tight_layout(rect=(0,.05,1,1))
fig.savefig(out/'current_range.png',dpi=170)
plt.close(fig)

example_table=''.join(f"<tr><td>{r['current_uA']:g}</td><td>{r['shunt_drop_mV']:.3f}</td><td>{r['ideal_U10_signal_mV']:.3f}</td><td>{r['ideal_offset_free_ADC_code_clipped']}</td><td>{'Clipped' if r['outside_nominal_ADC_span'] else 'In range'}</td></tr>" for r in samples)
html=f'''<!doctype html><html lang="en"><meta charset="utf-8"><title>Current range: R9 56 Ω</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;color:#193046;max-width:1050px;margin:40px auto;padding:0 24px}}h1{{font-size:28px}}h2{{font-size:20px}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;padding:8px;border-bottom:1px solid #ccd5de}}img{{max-width:100%}}.note{{padding:16px;background:#edf3fa}}</style>
<h1>Current range with R9 = 56 Ω and nominal U10 gain 7</h1>
<p class="note"><b>Nominal forward range: 0 to 2.55 mA.</b> ngspice reaches the ADC's +1 V differential boundary at
{rows[0]['ngspice_ADC_plus1V_crossing_mA']:.4f} mA. An upper target of 2.3 mA leaves about 10% nominal span headroom.
This is a simulated sensing range, not a hardware current-limit or accuracy guarantee.</p>
<img src="current_range.png" alt="ADC code saturates around 2.55 mA for gain7; load voltage decreases with shunt current.">
<h2>Transfer and resolution</h2><p>VADC,signal = I × 56 × 7 = 392 I (volts for current in amperes).
The ADC's nominal differential span is −1 to +1 V; zero input is code 2048. The positive half uses about 2048 codes.
Imax ≈ 1 / 392 = 2.551 mA; one code = (2/4096)/392 = {lsb_uA:.4f} µA.</p>
<table><tr><th>Current (µA)</th><th>R9 drop (mV)</th><th>U10 ideal signal (mV)</th><th>ADC code, zero offset</th><th>Status</th></tr>{example_table}</table>
<h2>Small currents and accuracy</h2><p>The last stable 205-sample capture had standard deviation
{std_codes:.3f} counts. At nominal gain7 this is approximately {std_codes*lsb_uA:.2f} µA RMS;
three standard deviations correspond to {3*std_codes*lsb_uA:.2f} µA. These are short-capture noise estimates,
not guaranteed minimum measurable currents. One-count resolution is not one-count accuracy.</p>
<p>Zero-offset calibration is needed for small absolute currents. The ADC datasheet's typical ±0.2%FS and
maximum ±1.25%FS offsets correspond to approximately ±10.2 µA and ±63.8 µA at nominal gain7,
before including amplifier, shunt and reference errors. Averaging steady DC can reduce uncorrelated random noise,
but cannot remove systematic offset/gain errors; no averaging improvement was measured here.</p>
<h2>Load disturbance and actual gain</h2><p>At 2.55 mA the shunt drops approximately 143 mV, leaving about
0.386 V at the load if the DAC holds 0.529 V. If only 10 mV drop is acceptable, current is limited to 179 µA;
50 mV allows 893 µA. These load-voltage requirements may be stricter than the ADC range.</p>
<p>If the actual gain were 6.25, the nominal span limit would instead be 2.857 mA and one count 1.395 µA.
That gain is included only as sensitivity analysis from the approximate meter ratio; it is not a calibrated gain.
No FPGA, ADC, DAC or FMC settings were changed for this simulation.</p>
<h2>Model and evidence</h2><p>TI INA851 preliminary PSpice macro-model in ngspice 46, +12/−3 V supplies,
1.5 V output common mode, 0/3.3 V clamp rails, 150 Ω input/output series resistors. Ideal static ADS5282 transfer;
no transistor-level ADC, sampling kickback, real DAC current-limit or system noise simulation. DC only; 10 MSPS does
not establish flat response to 5 MHz current signals.</p>
<p><a href="https://www.ti.com/lit/ds/symlink/ina851.pdf">INA851 datasheet</a> ·
<a href="https://www.ti.com/product/ADS5282">ADS5282 specifications</a> ·
<a href="summary.json">Summary and assumptions</a> · <a href="nominal_gain7.cir">ngspice netlist</a> ·
<a href="nominal_gain7.csv">Sweep data</a></p></html>'''
(out/'report.html').write_text(html,encoding='utf-8')
print(json.dumps({'results':rows,'noise':summary['existing_capture_noise'],'report':str(out/'report.html')},indent=2))
