"""Compare possible bench changes; does not modify PCB, DAC or FPGA hardware."""
from pathlib import Path
import json
import simulate_ain1 as base

ROOT = Path(__file__).resolve().parent
OUT = ROOT/'gain_shunt_options'
OUT.mkdir(exist_ok=True)
base.ROOT = OUT
engine = base.Spice()
results = []
options = [(0.47,1000), (0.47,100), (0.47,60.4), (0.47,6.04),
           (10,1000), (47,1000), (47,100), (470,1000)]
for r9, rg in options:
    cases = {}
    for state, rload in [('no_load',1e12), ('load_3k3',3300)]:
        circuit = base.netlist(rg, analysis='.op', load=f'RLOAD vcc_read 0 {rload}', dac=.539)
        circuit = circuit.replace('R9 dac0 vcc_read 470\n', f'R9 dac0 vcc_read {r9}\n')
        name = f'r9_{r9:g}_rg_{rg:g}_{state}'.replace('.','p')
        d = engine.run(name,circuit)
        vp = float(d['v(amp1_p)'][0]); vn = float(d['v(amp1_n)'][0])
        load_v = float(d['v(vcc_read)'][0])
        cases[state] = {'load_V':load_v, 'shunt_drop_V':.539-load_v,
                        'AMP1_P_V':vp, 'AMP1_N_V':vn, 'ADC_differential_V':vp-vn,
                        'ideal_ADC_code_of_model_output':2048+2048*(vp-vn)}
    gain = 1+6000/rg
    current = .539/(3300+r9)
    results.append({'R9_ohms':r9, 'R31_ohms':rg, 'gain':gain,
                    'load_current_uA':current*1e6, 'shunt_drop_mV':current*r9*1000,
                    'load_V':current*3300, 'fractional_source_voltage_drop':r9/(3300+r9),
                    'ADC_signal_mV_ideal':current*r9*gain*1000,
                    'ADC_increment_counts_ideal':2048*current*r9*gain,
                    'ADC_increment_counts_ngspice':cases['load_3k3']['ideal_ADC_code_of_model_output']-cases['no_load']['ideal_ADC_code_of_model_output'],
                    'current_uA_per_count_ideal':1e6/(2048*r9*gain),
                    'ideal_ADC_1V_limit_current_mA':1000/(r9*gain),
                    'model_operating_points':cases})

out = {'assumptions': {'source_V':.539, 'load_ohms':3300, 'caravel_installed':False,
                       'ADC_differential_full_scale_Vpp':2, 'ADC_bits':12,
                       'R31_actual_fitted_value_confirmed':False},
       'options':results,
       'temporary_bench_recommendation':{'R9_ohms':47, 'R31_ohms':1000,
           'reason':'Provides approximately 108 ADC counts with approximately 7.57 mV load-voltage reduction; avoids raising amplifier gain for initial path validation.'},
       'final_design_pending':['Required minimum and maximum current', 'Allowed supply drop', 'Required analog bandwidth', 'Fitted R31 value'],
       'limitations':['DC operating point only; this is not an AC bandwidth or settling simulation.',
           'INA851 bandwidth decreases with increasing gain; TI specifies typical 11 MHz at gain 10, 5 MHz at gain 100 and 0.8 MHz at gain 1000.',
           'ADC sample rate is independent of the useful analog measurement bandwidth.',
           'ADC transfer is ideal; actual offsets, noise, tolerances and physical Kelvin connections require measurement.',
           'No hardware changes have been made.'],
       'datasheet':'https://www.ti.com/lit/ds/symlink/ina851.pdf'}
(OUT/'comparison.json').write_text(json.dumps(out,indent=2)+'\n')
for r in results:
    print(f"R9={r['R9_ohms']:g} R31={r['R31_ohms']:g} gain={r['gain']:.4f} "
          f"drop_mV={r['shunt_drop_mV']:.6f} ADC_mV={r['ADC_signal_mV_ideal']:.6f} "
          f"ideal_counts={r['ADC_increment_counts_ideal']:.3f} spice_counts={r['ADC_increment_counts_ngspice']:.3f}")
