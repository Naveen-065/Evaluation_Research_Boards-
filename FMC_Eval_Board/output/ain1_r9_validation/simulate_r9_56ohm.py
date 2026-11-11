"""User replaced R9 with 56 ohms; predict ADC1 for retained 3.3k load."""
from pathlib import Path
import argparse, json
import simulate_ain1 as base

parser = argparse.ArgumentParser()
parser.add_argument('--source-voltage', type=float, default=.539)
args = parser.parse_args()
source_v = args.source_voltage
root = Path(__file__).resolve().parent / 'r9_56ohm'
root.mkdir(exist_ok=True)
base.ROOT = root
engine = base.Spice()
results = []
for rg in [100, 150, 470, 1000, 1200, 1300, 1500, 2000, 6040, 10000, 1e12]:
    runs = {}
    for state, rload in [('unloaded', 1e12), ('loaded', 3300)]:
        name = f'rg_{rg:g}_{state}'
        net = base.netlist(rg, analysis='.op', load=f'RLOAD vcc_read 0 {rload}', dac=source_v)
        net = net.replace('R9 dac0 vcc_read 470\n', 'R9 dac0 vcc_read 56\n')
        d = engine.run(name, net)
        vals = {k:float(v[0]) for k,v in d.items()}
        vals['shunt_drop_V'] = vals['v(dac0)'] - vals['v(vcc_read)']
        vals['adc_diff_V'] = vals['v(amp1_p)'] - vals['v(amp1_n)']
        vals['ideal_ADC_code_from_model'] = 2048 + 2048*vals['adc_diff_V']
        runs[state] = vals
    gain = 1 + 6000/rg
    drop = source_v*56/(3300+56)
    results.append({'R31_ohms': None if rg==1e12 else rg, 'gain':gain,
                    'ideal_current_A':source_v/(3300+56), 'ideal_shunt_drop_V':drop,
                    'ideal_ADC_signal_V': gain*drop,
                    'ideal_ADC_code':2048+2048*gain*drop,
                    'ideal_ADC_increment':2048*gain*drop,
                    'ngspice_ADC_increment':runs['loaded']['ideal_ADC_code_from_model']-runs['unloaded']['ideal_ADC_code_from_model'],
                    'runs':runs})
out = {'user_confirmed_R9_ohms':56, 'R31_fitted_value_confirmed':False,
       'assumed_load_ohms':3300, 'assumed_Caravel_removed':True,
       'source_voltage_V':source_v, 'source_voltage_basis':'Source voltage provided by command-line argument; see meter_measurements.json for latest hardware readings',
       'results':results,
       'limitations':['ADC conversion is ideal static 12-bit / 2 Vpp; actual ADC offset and noise not modeled.',
                      'TI INA851 preliminary macro-model; simulation does not establish fitted gain or ADC bit alignment.']}
(root/'simulation.json').write_text(json.dumps(out,indent=2)+'\n')
for r in results:
    print(f"R31={r['R31_ohms']} gain={r['gain']:.6g} "
          f"shunt_mV={r['ideal_shunt_drop_V']*1e3:.6f} "
          f"ADC_mV={r['ideal_ADC_signal_V']*1e3:.6f} "
          f"ideal_code={r['ideal_ADC_code']:.4f} "
          f"ngspice_delta={r['ngspice_ADC_increment']:.4f}")
