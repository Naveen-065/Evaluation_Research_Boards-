"""Sense-path DC range and 47-ohm bench load, with ideal-source limits explicit."""
from pathlib import Path
import json
import simulate_ain1 as base

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'range_1_to_300mA'
OUT.mkdir(exist_ok=True)
base.ROOT=OUT
engine=base.Spice()
cases=[]
for rg in [1000,1200]:
    for current in [0,.001,.01,.1,.3]:
        circuit=base.netlist(rg,analysis='.op',load=f'ILOAD vcc_read 0 {current}',dac=.539)
        circuit=circuit.replace('R9 dac0 vcc_read 470\n','R9 dac0 vcc_read 0.47\n')
        name=f'rg_{rg}_current_{current:g}'.replace('.','p')
        d=engine.run(name,circuit)
        diff=float(d['v(amp1_p)'][0]-d['v(amp1_n)'][0])
        gain=1+6000/rg
        cases.append({'R31_ohms':rg,'gain':gain,'current_mA':current*1000,
                      'shunt_drop_V_ideal':current*.47,
                      'ADC_signal_V_ideal':current*.47*gain,
                      'ADC_increment_counts_ideal':2048*current*.47*gain,
                      'ngspice_ADC_differential_V_including_model_offset':diff,
                      'ngspice_plus_ideal_ADC_code':2048+2048*diff,
                      'ADC_equivalent_mA_per_count':1000/(2048*.47*gain),
                      'ideal_source_only_above_DAC_capability':current>.025})

bench=[]
for rg in [1000,1200]:
    circuit=base.netlist(rg,analysis='.op',load='RLOAD vcc_read 0 47',dac=.539)
    circuit=circuit.replace('R9 dac0 vcc_read 470\n','R9 dac0 vcc_read 0.47\n')
    d=engine.run(f'47ohm_load_rg_{rg}',circuit)
    gain=1+6000/rg
    current=.539/(47+.47)
    bench.append({'R31_ohms':rg,'gain':gain,'R9_ohms':.47,'load_ohms':47,
                  'source_V_assumed':.539,'current_mA_ideal':current*1000,
                  'shunt_drop_mV_ideal':current*.47*1000,
                  'load_V_ideal':current*47,'load_power_mW_ideal':current**2*47*1000,
                  'ADC_signal_mV_ideal':current*.47*gain*1000,
                  'ADC_increment_counts_ideal':2048*current*.47*gain,
                  'ngspice_AMP1_P_V':float(d['v(amp1_p)'][0]),
                  'ngspice_AMP1_N_V':float(d['v(amp1_n)'][0]),
                  'actual_loaded_source_voltage_required':True})

out={'user_range_mA':[1,300],'R9_user_confirmed_ohms':.47,
     'R31_fitted_value_confirmed':False,'max_allowed_shunt_drop_V':None,
     'cases':cases,'bench_47ohm_load':bench,
     'range_design':{
         'R9_47ohm_drop_at_300mA_V':.3*47,
         'R9_47ohm_power_at_300mA_W':.3**2*47,
         'R9_0p47ohm_drop_at_300mA_V':.3*.47,
         'R9_0p47ohm_power_at_300mA_W':.3**2*.47,
         'ADC_ideal_positive_limit_V':1,
         'gain7_signal_at_300mA_R9_plus5percent_V':.3*.47*1.05*7,
         'gain6_signal_at_300mA_R9_plus5percent_R31_minus1percent_V':.3*.47*1.05*(1+6000/(1200*.99)),
         'provisional_final_R31_ohms_if_141mV_drop_accepted':1200,
         'provisional_final_gain':6,
     },
     'hardware_limitations':[
         'U1 DAC81416 OUT0 directly drives AQ1_C00/R9; no power buffer is in this PCB path.',
         'TI specifies output drive up to 25 mA under stated supply-headroom conditions; it cannot directly supply 300 mA.',
         'Simulated points above 25 mA use an ideal source only and do not establish that the actual DAC can deliver them.',
         'U1 VSS is GND; 0.539 V is outside the 1 V/1.5 V output-headroom accuracy specification. Measure actual voltage under the 47-ohm load.',
         'A 300 mA test requires a suitable external power stage or supply and isolation from the DAC output; do not parallel a bench supply with the active DAC.',
         'A 1 mA signal is only 5.78 counts at gain 6; offset calibration is required, and high precision across the full range may require more than one gain range.',
         'No hardware settings or components were changed.'
     ],
     'sources':['https://www.ti.com/product/DAC81416',
                'https://www.ti.com/lit/ds/symlink/dac81416.pdf',
                'https://www.ti.com/lit/ds/symlink/ina851.pdf']}
(OUT/'result.json').write_text(json.dumps(out,indent=2)+'\n')
old=ROOT/'gain_shunt_options/comparison.json'
if old.exists():
    earlier=json.loads(old.read_text())
    earlier['recommendation_status']='Superseded by user range 1-300 mA: keep 0.470-ohm R9; use 47 ohms only as a temporary load.'
    earlier['superseded_by']='../range_1_to_300mA/result.json'
    old.write_text(json.dumps(earlier,indent=2)+'\n')
print(json.dumps({'range_design':out['range_design'],'bench_47ohm_load':bench},indent=2))
