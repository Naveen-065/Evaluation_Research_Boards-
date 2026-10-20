"""U18-specific fault experiments, ngspice-46, assumed MOS equivalent.

These are mechanism tests, not a fitted PCA9306 silicon model or a diagnosis
from a single voltage. All PCB resistors/pin assignments follow the inspected
v1.2F board. Rail load, MOS parameters and fault impedances are assumptions.
Run with Python, numpy, matplotlib and the KiCad ngspice DLL (see runner).
"""
from spice_runner import Spice, OUT
import numpy as np
import matplotlib.pyplot as plt
import csv, json

def circuit(case, load=1e-3, sweep=True, leakage=1e12, bleed=1e12):
    bias = {
        'original': 'R56 high en 10k\nVref high ref2 0',
        'r56_only': 'R56 high en 200k\nVref high ref2 0',
        'temporary_disable': 'R56 high en 10k\nVref high ref2 0\nRtest en 0 470',
        'bridge_no_cut': 'R56 high en 200k\nVref high ref2 0\nRbridge en ref2 1m',
        'cut_no_bridge': 'R56 high en 200k\nRfloat ref2 0 1T',
        'corrected_10k': 'R56 high en 10k\nVref en ref2 0',
        'corrected': 'R56 high en 200k\nVref en ref2 0',
        'incomplete_cut': f'R56 high en 200k\nVref en ref2 0\nRcut high ref2 {leakage}',
        'faulted_u18_disabled': 'R56 high en 10k\nVref high ref2 0\nRtest en 0 470\nRdamage ref2 rail 1k',
    }[case]
    analysis = '.dc Vload 0 0.01 0.00001' if sweep else '.op'
    return f'''U18 fault scenario: {case}
* Illustrative 3-NMOS PCA9306 equivalent; not a vendor silicon model.
* Load is assumed; no parameter fitted to 2.1 V. Damage/leak resistances hypothetical.
* Idealized source-only LDO; does not simulate regulator stability or reverse damage.
.options reltol=1e-7 abstol=1e-12 vntol=1e-9 itl1=500
.nodeset v(rail)=1.8 v(en)=2.4 v(ref2)=2.4 v(scll)=1.8 v(sclh)=3.3 v(sdal)=1.8 v(sdah)=3.3
Vhigh high 0 3.3
Vtarget target 0 1.8
Vload loadctl 0 {load}
Bldo 0 rail I=max(0,min(0.8,20*(v(target)-v(rail))))
Bload rail 0 I=v(loadctl)
Rrail rail 0 10Meg
Rbleed rail 0 {bleed}
Crail rail 0 10u
{bias}
C58 ref2 0 100n
Cen en 0 11p
Mref ref2 en rail 0 PASS W=1u L=1u
Mscl sclh en scll 0 PASS W=1u L=1u
Msda sdah en sdal 0 PASS W=1u L=1u
.model PASS NMOS(LEVEL=1 VTO=0.6 KP=0.02 LAMBDA=0 GAMMA=0)
R53 rail sdal 10k
R54 rail scll 10k
R57 high sclh 10k
R58 high sdah 10k
Cscll scll 0 50p
Csclh sclh 0 50p
Csdal sdal 0 50p
Csdah sdah 0 50p
{analysis}
.save v(loadctl) v(rail) v(en) v(ref2) v(scll) v(sclh) @mref[id]
.end
'''

sp=Spice()
vectors={'load_A':'v(loadctl)','rail_V':'v(rail)','en_V':'v(en)',
         'ref2_V':'v(ref2)','scl_low_V':'v(scll)','scl_high_V':'v(sclh)',
         'reference_MOS_current_A':'@mref[id]'}

def checked_run(name, netlist, case, bleed=1e12):
    d=sp.run(name,netlist,vectors)
    # DC KCL sanity check rejects false operating points after solver recovery.
    # SDA is identical to idle SCL in these symmetric circuits.
    rail=d['rail_V']
    ldo=np.maximum(0,np.minimum(.8,20*(1.8-rail)))
    damage=(d['ref2_V']-rail)/1e3 if case=='faulted_u18_disabled' else 0
    residual=ldo+d['reference_MOS_current_A']+damage+2*(d['scl_low_V']-rail)/1e4-d['load_A']-rail/1e7-rail/bleed
    if not np.all(np.isfinite(residual)) or np.max(np.abs(residual))>2e-8:
        raise RuntimeError(f'{name}: DC current balance failed, {np.max(np.abs(residual))} A')
    return d
cases=['original','r56_only','temporary_disable','bridge_no_cut','cut_no_bridge',
       'corrected_10k','corrected','faulted_u18_disabled']
curves={}
for case in cases:
    curves[case]=checked_run(case,circuit(case),case)

selected=[]
for case,d in curves.items():
    for load in [0,10e-6,50e-6,1e-3,10e-3]:
        selected.append({'case':case,'assumed_load_A':load,**{
            k:float(np.interp(load,d['load_A'],d[k])) for k in vectors if k!='load_A'}})

# Weak residual copper/contamination paths bypassing the intended resistor.
# Their values are test assumptions, not measured board faults.
residual=[]
for resistance in np.geomspace(10,1e6,41):
    d=checked_run(f'cut_leak_{resistance:.6g}'.replace('.','p'),
             circuit('incomplete_cut',sweep=False,leakage=resistance),'incomplete_cut')
    residual.append({'residual_ohm':float(resistance),**{k:float(v[0]) for k,v in d.items()}})

# Correct bias may still lift an otherwise unloaded source-only rail.
bleed=[]
for case in ['corrected','corrected_10k']:
    for active in [0,1e-6,10e-6,50e-6,100e-6,1e-3]:
        for res in [1e12,100e3,1e3]:
            name=f'lightload_{case}_{active:.0e}_{res:.0e}'
            d=checked_run(name,circuit(case,load=active,sweep=False,bleed=res),case,bleed=res)
            bleed.append({'case':case,'bleed_ohm':res,'active_load_A':active,
                          **{k:float(v[0]) for k,v in d.items()}})

for filename,rows in [('selected_results',selected),('residual_cut_results',residual),('light_load_results',bleed)]:
    with (OUT/(filename+'.csv')).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)

plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
fig,axs=plt.subplots(2,2,figsize=(12,8.5))
for c,label,color,ls in [('original','Original','#b45309','-'),
                         ('r56_only','200k only (overlaps original)','#c8a200','--'),
                         ('temporary_disable','EN pulled down through 470 ohms','#0066aa','--'),
                         ('corrected','Cut + bridge + 200k','#00866b','-')]:
    d=curves[c];axs[0,0].plot(1e3*d['load_A'],d['rail_V'],label=label,color=color,ls=ls)
axs[0,0].set(xlabel='Assumed rail load (mA)',ylabel='+1V8 rail (V)',title='Temporary EN test isolates healthy U18 in model')
axs[0,0].legend(fontsize=8)

cs=['original','cut_no_bridge','bridge_no_cut','corrected']
labels=['Original','Cut only','Bridge only','Complete repair']
x=np.arange(len(cs));width=.35
for j,(key,label,color) in enumerate([('rail_V','Supply rail','#00866b'),('scl_low_V','Low-side SCL idle','#b45309')]):
    vals=[float(np.interp(.001,curves[c]['load_A'],curves[c][key])) for c in cs]
    axs[0,1].bar(x+(j-.5)*width,vals,width,label=label,color=color)
axs[0,1].set(xticks=x,xticklabels=labels,ylabel='Voltage (V)',title='A correct rail alone does not prove correct I2C levels')
axs[0,1].legend(fontsize=8)

axs[1,0].semilogx([r['residual_ohm'] for r in residual],[r['rail_V'] for r in residual],label='+1V8 rail',color='#00866b')
axs[1,0].semilogx([r['residual_ohm'] for r in residual],[r['en_V'] for r in residual],label='Joined EN/VREF2',color='#b45309')
axs[1,0].set(xlabel='Assumed residual path to 3.3 V (ohms)',ylabel='Voltage (V)',title='Incomplete cut, 1 mA assumed rail load')
axs[1,0].legend(fontsize=8)

for c,label,color in [('corrected','R56 = 200k','#00866b'),('corrected_10k','R56 left at 10k','#b45309')]:
    d=curves[c];mask=d['load_A']<=200e-6
    axs[1,1].plot(d['load_A'][mask]*1e6,d['rail_V'][mask],label=label,color=color)
axs[1,1].set(xlabel='Assumed rail load (uA)',ylabel='+1V8 rail (V)',title='Light load: available sink current matters')
axs[1,1].legend(fontsize=8)
for ax in axs.flat:
    ax.axhline(1.8,color='#666',ls=':',lw=1);ax.grid(alpha=.2)
fig.suptitle('U18-specific fault tests in ngspice',fontsize=17,fontweight='bold')
fig.text(.5,.015,'Generic MOS equivalent; actual load and silicon parameters unknown. These tests distinguish mechanisms, not a unique diagnosis.',ha='center',fontsize=9)
fig.tight_layout(rect=(0,.035,1,.95))
fig.savefig(OUT/'u18_fault_results.png',dpi=170)

summary={'engine':sp.version,'model':'Generic 3-NMOS PCA9306 equivalent with source-only idealized 1.8 V rail',
         'scope':'U18 only. User confirmed no rework yet; 2.1 V measured on original assembly.',
         'limitations':['No TI encrypted HSPICE model executed','MOS VTO=0.6 V and KP=0.02 are assumed',
                        'No parameters fitted to 2.1 V','Board rail load unknown',
                        'Fault resistances are illustrative; damaged silicon not characterized',
                        'LDO stability, exact part behavior, FPGA compatibility not simulated'],
         'selected':selected,'residual_cut':residual,'light_load':bleed}
(OUT/'results.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
print(json.dumps({'at_1mA':[r for r in selected if r['assumed_load_A']==.001],
                  'at_50uA':[r for r in selected if r['assumed_load_A']==50e-6],
                  'corrected_zero_load':[r for r in bleed if r['case']=='corrected' and r['active_load_A']==0]},indent=2))
