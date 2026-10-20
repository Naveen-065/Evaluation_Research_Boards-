"""Compare the user's 3.3 kohm load before and after R9 at measured 0.539 V."""
from pathlib import Path
import json
import simulate_ain1 as base

root=Path(__file__).resolve().parent/'load_3k3'
root.mkdir(exist_ok=True)
base.ROOT=root
engine=base.Spice()
results=[]
for position, node, gains in [
    ('AQ1_C00_before_R9','dac0',[1000]),
    ('VCC_READ_after_R9','vcc_read',[470,1000,2000,6040,10000,1e12]),
]:
    for rg in gains:
        name=position+'_rg_'+('open' if rg==1e12 else str(rg))
        d=engine.run(name,base.netlist(rg,analysis='.op',
                          load=f'RTEST {node} 0 3300',dac=0.539))
        vp=float(d['v(dac0)'][0])
        vn=float(d['v(vcc_read)'][0])
        op=float(d['v(amp1_p)'][0]);on=float(d['v(amp1_n)'][0])
        ideal_drop=0 if node=='dac0' else .539*470/(3300+470)
        results.append({
            'test_resistor_position':position,'test_resistor_ohms':3300,
            'rg_ohms':None if rg==1e12 else rg,'nominal_gain':1+6000/rg,
            'AIN1_P_V':vp,'AIN1_N_V':vn,
            'shunt_drop_V':vp-vn,'shunt_current_A':(vp-vn)/470,
            'test_resistor_current_A':(vp if node=='dac0' else vn)/3300,
            'AMP1_P_V':op,'AMP1_N_V':on,'adc_differential_V':op-on,
            'model_plus_ideal_adc_code':2048+2048*(op-on),
            'ideal_offset_free_adc_code':2048+2048*(1+6000/rg)*ideal_drop,
            'expected_offset_free_code_increase':2048*(1+6000/rg)*ideal_drop,
        })
out={
    'user_measurement':{'R9_pad2_to_GND_V':.539,'R9_pad3_to_GND_V':.539,
                        'direct_differential_mV':None,
                        'load':'3.3 kohm from AQ1_C00 to ground',
                        'caravel_connected_through_NT1':True},
    'assumptions':['DAC0 remains at measured 0.539 V under both load arrangements.',
                   'Unknown Caravel current is omitted; predictions are for the test resistor alone.',
                   'R9 fitted value is 470 ohms; R31 fitted value remains unconfirmed.',
                   'Equal ground-referenced readings to three decimal places do not establish zero shunt drop.'],
    'simulations':results,
    'status':'Awaiting corrected load placement and meter/FPGA comparison',
}
(root/'simulation_3k3.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out,indent=2))
