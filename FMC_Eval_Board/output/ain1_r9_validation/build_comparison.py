from pathlib import Path
from collections import Counter
import json,csv,html,statistics
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

root=Path(__file__).resolve().parent
sim=json.loads((root/'simulation_summary.json').read_text())
capture_path=root/'ads5282_analog_20261019_200552.summary.json'
capture=json.loads(capture_path.read_text())
with (root/'ads5282_analog_20261019_200552_packets.csv').open() as f:
    packets=list(csv.DictReader(f))
codes=np.array([int(row['ch1_candidate_code']) for row in packets])
mean=float(codes.mean())
apparent_vadc=(mean-2048)/2048
nominal_gain=7
comparison={
    'capture_file':capture_path.name,
    'packets':len(codes),'sample_rate_hz':10000000,
    'decoded_ch1_mean':mean,'decoded_ch1_min':int(codes.min()),'decoded_ch1_max':int(codes.max()),
    'decoded_ch1_stdev':float(codes.std()),
    'nominal_adc_equivalent_differential_V_before_offset_correction':apparent_vadc,
    'assumed_R31_ohms':1000,'assumed_gain':nominal_gain,'assumed_R9_ohms':470,
    'apparent_shunt_drop_V_if_zero_offset':apparent_vadc/nominal_gain,
    'apparent_current_A_if_zero_offset':apparent_vadc/nominal_gain/470,
    'current_A_per_adc_code_at_gain7':1/2048/7/470,
    'measured_shunt_voltage_V':None,'actual_fitted_R31_ohms':None,
    'independent_end_to_end_gain_validation':'pending meter readings and known load stimulus',
    'known_adc_pattern_hardware_validation':False,
    'important':'Apparent current is not a calibrated measured current; ADC and amplifier offsets can explain a near-midscale reading.',
}
(root/'fpga_comparison.json').write_text(json.dumps(comparison,indent=2)+'\n')
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10})
fig,(ax,hist)=plt.subplots(1,2,figsize=(12,4.5),gridspec_kw={'width_ratios':[1.5,1]})
for rg in [100,150,470,1000,6040,10000]:
    a=np.genfromtxt(root/f'rg_{rg}.csv',delimiter=',',names=True)
    good=(a['ideal_adc_code_unclipped']<=4095)
    label=f'R31 = {rg/1000:g} kΩ' if rg>=1000 else f'R31 = {rg} Ω'
    ax.plot(a['load_current_A'][good]*1e6,a['ideal_adc_code_unclipped'][good],label=label,lw=2 if rg==1000 else 1.2)
ax.set(xlim=(0,400),ylim=(2000,4150),xlabel='Assumed load current through R9 (µA)',ylabel='Predicted ADC code',title='ngspice: TI INA851 model + ideal ADC')
ax.axhline(4095,color='#7c8796',ls='--',lw=.8)
ax.grid(alpha=.2);ax.legend(loc='lower right',fontsize=8)
freq=Counter(codes)
hist.bar(list(freq),list(freq.values()),color='#2660a4')
hist.axvline(mean,color='#b85924',label=f'Mean {mean:.2f}',lw=1.5)
hist.set(xlabel='Channel 1 decoded code (LSB-first)',ylabel='Samples',title=f'FPGA baseline: {len(codes)} packets at 10 MSPS')
hist.legend();hist.grid(axis='y',alpha=.2)
fig.text(.5,.015,'Simulation sweeps an assumed load. Hardware shunt drop and fitted R31 are not yet measured; this is not a gain calibration.',ha='center',fontsize=9)
fig.tight_layout(rect=(0,.05,1,1))
fig.savefig(root/'gain_and_capture.png',dpi=170)
plt.close(fig)

table=''.join(f"<tr><td>{'Open' if x['rg_ohms'] is None else str(x['rg_ohms'])+' Ω'}</td><td>{x['nominal_gain']:.4g}</td><td>{x['ngspice_linear_fitted_gain']:.5g}</td><td>{x['positive_adc_full_scale_current_uA_ideal']:.2f}</td></tr>" for x in sim['rg_sweep'])
load=next(x for x in sim['47k_load_simulations_assuming_no_other_load'] if x['rg_ohms']==1000)
report=f'''<!doctype html><html lang="en"><meta charset="utf-8"><title>R9 / U10 / ADC1 validation</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;color:#193046;max-width:1000px;margin:40px auto;padding:0 24px}}h1{{font-size:28px}}h2{{font-size:20px;margin-top:30px}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;padding:8px;border-bottom:1px solid #cdd6df}}.status{{background:#fff1d5;padding:15px}}code{{font-size:14px}}img{{max-width:100%}}</style>
<h1>R9 → U10 → ADS5282 channel 1 → KC705</h1>
<p class="status"><b>Simulation completed; independent gain validation pending.</b> The FPGA captured {len(codes)} complete packets at 10 MSPS. No FPGA bitstream or FMC electrical setting was changed during this comparison. The actual R9 voltage drop and fitted R31 remain unknown.</p>
<h2>Traced circuit</h2>
<p>DAC81416 OUT0 / AQ1_C00 → R9 current pad 1 → 470 Ω shunt → R9 current pad 4 / VCC_READ → NT1 → Caravel mprj_io[33]. The four-terminal resistor is assumed to connect sense pad 2 to the source side and sense pad 3 to the load side internally.</p>
<p>R9.2 / AIN1_P → R33 (150 Ω) → U10.4 (IN+). R9.3 / AIN1_N → R34 (150 Ω) → U10.1 (IN−). U10.11/10 → R37/R38 (150 Ω) → AMP1_P/N → U14.1/2. OUT1_P/N route through FMC to the FPGA. All these routed connections passed the PCB design connectivity audit; this does not test solder joints.</p>
<p>U10 is INA851, powered from +12 V and −3VA, VOCM = ADCVCM ≈ 1.5 V, clamps 0/3.3 V. G02 pins are open: output-stage gain = 1. Only <b>R31</b>, between U10 pins 3 and 2, sets its input-stage gain.</p>
<h2>Gain and conversion</h2>
<p><code>G = 1 + 6000 / R31<br>Vshunt = V(AIN1_P) − V(AIN1_N) = I × 470<br>VADC,diff ≈ G × Vshunt<br>ADC code ≈ clip(2048 + 2048 × VADC,diff, 0, 4095)</code></p>
<p>At R31 = 1 kΩ, G = 7. One ADC count represents about 69.75 µV across R9, or 0.1484 µA, before offsets and gain errors. Changing the DAC voltage without a load need not produce a measurable shunt drop.</p>
<table><tr><th>R31</th><th>Nominal gain</th><th>ngspice fitted gain</th><th>Ideal positive ADC full-scale current (µA)</th></tr>{table}</table>
<p>Full-scale limits are ±1 V differential at the ADC. Values above 1064 µA also exceed the current available from an ideal 0.5 V source through 470 Ω into a passive grounded load. Open R31 gives gain ≈ 1; shorting it is not a valid gain selection.</p>
<img src="gain_and_capture.png" alt="Simulated gain curves and measured FPGA code distribution">
<h2>Fresh FPGA baseline</h2>
<p>Mean {mean:.4f}; range {codes.min()}–{codes.max()}; standard deviation {codes.std():.3f} counts. Every packet interval was 20 cycles of the 200 MHz capture clock, giving 10 MSPS. Return-clock flags and frame-lock stayed high.</p>
<p>Using the configured LSB-first interpretation, the mean is equivalent to {apparent_vadc*1000:.4f} mV at the ADC. If gain were exactly 7 and total offset zero, that would imply {comparison['apparent_shunt_drop_V_if_zero_offset']*1000:.4f} mV across R9 and {comparison['apparent_current_A_if_zero_offset']*1e6:.4f} µA. <b>Those are conditional equivalents, not validated current measurements.</b> ADS5282 offset specification is ±0.2% FS typical and ±1.25% FS maximum; a four-count departure from midscale cannot identify a bad gain resistor.</p>
<h2>Concrete known-load check</h2>
<p>A 47 kΩ resistor from VCC_READ (R9.4) to PCB GND, with a nominal 0.50003 V DAC and no other load, produces {load['load_current_A']*1e6:.4f} µA and {load['shunt_drop_V']*1000:.4f} mV across R9. With R31 = 1 kΩ, the TI model predicts AMP1_P = {load['amp1_p_V']:.6f} V, AMP1_N = {load['amp1_n_V']:.6f} V, differential {load['adc_differential_V']*1000:.4f} mV, ideal ADC code ≈ {load['ideal_adc_code']:.2f}. Model offsets are not the real board's offsets.</p>
<p>The useful check is the <b>change</b> from unloaded to loaded reading: approximately +{load['ideal_nominal_increment_from_no_load']:.2f} counts at gain 7. Use the measured change in R9 drop if Caravel is also connected. Calculate <code>Gmeas = (code_loaded − code_baseline) / (2048 × (Vshunt_loaded − Vshunt_baseline))</code>, then <code>R31 ≈ 6000 / (Gmeas − 1)</code>. A nonzero known-input test also checks the serial interpretation and polarity.</p>
<p>Requested measurements: R9.2 and R9.3 to ground, direct R9.2 (+) to R9.3 (−) in mV, actual load connection, and R31 fitted marking/value. Do not use resistance mode on a powered board.</p>
<h2>Model scope and source consistency</h2>
<p>ngspice 46 used TI's unmodified preliminary INA851 macro-model, PSpice compatibility, and 1 TΩ numerical shunts for convergence. The DAC is an ideal voltage source; ADS5282 is an ideal static conversion equation. ADC offsets/noise, sample-and-hold kickback and real resistor tolerances are not simulated. TI documents limitations in this model's clamp/range behavior, so those limits were checked from the data sheets rather than inferred from saturation plots.</p>
<p>The exported schematic has local <code>/DAC/AIN1_P,N</code> labels distinct from global <code>AIN1_P,N</code>. The current PCB connects the R9 sense pads to R33/R34; the simulation follows that routed PCB. The schematic's label inconsistency should be corrected before a future PCB update.</p>
<p>Sources: <a href="https://www.ti.com/lit/ds/symlink/ina851.pdf">INA851 data sheet</a>; <a href="https://www.ti.com/lit/zip/SBOMC50">TI INA851 model</a>; <a href="https://www.ti.com/lit/ds/symlink/ads5282.pdf">ADS5282 data sheet</a>; <a href="https://e2e.ti.com/support/amplifiers-group/amplifiers/f/amplifiers-forum/1220673/ina851-ltspice-model-issue">TI model limitations</a>.</p>
</html>'''
(root/'comparison.html').write_text(report,encoding='utf8')
print(json.dumps(comparison,indent=2))
