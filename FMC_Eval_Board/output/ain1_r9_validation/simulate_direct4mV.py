"""Amplifier-only response to the user's direct 4 mV R9 reading.

The reported 0.529/0.520 V absolute readings imply 9 mV, so they cannot
both be imposed along with 4 mV. Here ideal sources impose 0.529/0.525 V
solely to test U10's gain. This is not a validation of the 3.3k load path.
"""
from pathlib import Path
import json
import simulate_ain1 as base

root=Path(__file__).resolve().parent/'r9_56ohm'
out=root/'direct4mV'
out.mkdir(exist_ok=True)
base.ROOT=out
engine=base.Spice()
rows=[]
for rg in [470,1000,1300]:
    runs={}
    for state,drop in [('zero',0),('measured_drop',.004)]:
        net=base.netlist(rg,analysis='.op',load=f'VSENSE_N vcc_read 0 {.529-drop}',dac=.529)
        net=net.replace('R9 dac0 vcc_read 470\n','R9 dac0 vcc_read 56\n')
        d=engine.run(f'rg_{rg}_{state}',net)
        p=float(d['v(amp1_p)'][0]);n=float(d['v(amp1_n)'][0])
        runs[state]={'AMP1_P_V':p,'AMP1_N_V':n,'ADC_diff_V':p-n}
    rows.append({'R31_ohms':rg,'gain':1+6000/rg,
                 'ideal_output_signal_mV':4*(1+6000/rg),
                 'ngspice_output_change_mV':1000*(runs['measured_drop']['ADC_diff_V']-runs['zero']['ADC_diff_V']),
                 'runs':runs})
data={'user_reported_direct_R9_V':.004,'separate_ground_reading_difference_V':.009,
      'readings_consistent':False,'R9_ohms':56,'current_from_direct_reading_uA':.004/56*1e6,
      'load_current_from_prior_0p520_V_and_3k3_uA':.520/3300*1e6,
      'simulation_scope':'U10 gain response to forced 4 mV input; not the physical 3.3k load circuit',
      'assumed_common_mode_source_V':.529,'forced_load_side_V':.525,
      'U10_output_meter_reading_pending':True,'results':rows}
(out/'simulation.json').write_text(json.dumps(data,indent=2)+'\n')
mp=root/'meter_measurements.json'
m=json.loads(mp.read_text())
m['R9_direct_differential_mV']=4.0
m['note']='User reported direct R9 voltage 0.004 V after reporting 0.529/0.520 V to ground. Readings are inconsistent; do not infer fitted R31 until verified.'
m['U10_direct_output_differential_mV']=None
mp.write_text(json.dumps(m,indent=2)+'\n')
report=root.parent/'comparison.html'
s=report.read_text(encoding='utf-8')
notice='<p class="status"><b>Latest measurement conflict:</b> User reports 4 mV directly across R9, whereas the earlier ground-referenced readings differ by 9 mV. These cannot describe the same steady voltages. The gain estimates below are conditional and not validated. Direct U10 output measurement is pending. <a href="r9_56ohm/direct4mV/simulation.json">4 mV amplifier simulation</a>.</p>'
if 'Latest measurement conflict:' not in s:
    s=s.replace('<h1>',notice+'<h1>',1)
    report.write_text(s,encoding='utf-8')
print(json.dumps(data,indent=2))
