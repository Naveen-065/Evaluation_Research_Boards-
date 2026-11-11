"""Electrical risk mechanisms at a measured +1V8 rail of 2.1 V.

Not a damage/lifetime model. U18 is a generic MOS equivalent. Carrier I2C
pullups are actual values from KC705 schematic; no mux transfer model.
FPGA-clamp example is explicitly generic, not AMD IBIS or silicon.
"""
from spice_runner import Spice, OUT
import numpy as np
import matplotlib.pyplot as plt
import json

def u18_net(corrected=False,carrier=False,vth=.6,kp=.02):
    bias='R56 high en 200k\nVlink en ref2 0' if corrected else 'R56 high en 10k\nVlink high ref2 0'
    pulls='RcS high scll 4.7k\nRcD high sdal 4.7k' if carrier else '* FMC disconnected'
    return f'''U18 held-rail stress check: corrected={corrected}, carrierpullups={carrier}
* Holding rail with a voltage source is a boundary condition, NOT LDO behavior.
* Positive I(Vrail) is current which the real rail load/regulator must absorb.
* Generic MOS equivalent, no manufacturer fitted parameters, no damage model.
.options reltol=1e-7 abstol=1e-12 vntol=1e-9
Vrail rail 0 2.1
Vhigh high 0 3.3
{bias}
Mref ref2 en rail 0 PASS W=1u L=1u
Mscl sclh en scll 0 PASS W=1u L=1u
Msda sdah en sdal 0 PASS W=1u L=1u
.model PASS NMOS(LEVEL=1 VTO={vth} KP={kp} GAMMA=0 LAMBDA=0)
R53 rail sdal 10k
R54 rail scll 10k
R57 high sclh 10k
R58 high sdah 10k
{pulls}
.dc Vrail 1.7 2.7 .01
.save v(rail) v(en) v(scll) v(sclh) i(Vrail) @mref[id]
.end
'''

def clamp_net(vcco=1.8):
    return f'''Illustrative generic input clamp: bank VCCO={vcco}
* NOT an AMD/Kintex model. No breakdown, latchup, lifetime or thermal behavior.
* 4k represents a TXS high-state weak pullup; edge accelerators not simulated.
.options reltol=1e-7 abstol=1e-12 vntol=1e-9
Vsource source 0 2.1
Vbank bank 0 {vcco}
Rpull source pin 4k
Dclamp pin bank GENERIC
.model GENERIC D(IS=1e-12 N=1 RS=5)
Rleak pin 0 10Meg
Cpin pin 0 8p
.dc Vsource 1.8 2.7 .01
.save v(source) v(pin) i(Vbank) i(Vsource)
.end
'''

sp=Spice()
vec={'rail_V':'v(rail)','bias_V':'v(en)','i2c_card_V':'v(scll)',
     'i2c_clock_V':'v(sclh)','rail_injection_A':'i(Vrail)','ref_current_A':'@mref[id]'}
curves={};selected=[]
for corrected in [False,True]:
    for carrier in [False,True]:
        name=('corrected' if corrected else 'original')+('_carrier_pullups' if carrier else '_standalone')
        d=sp.run(name,u18_net(corrected,carrier),vec)
        # Idle SDA and SCL are symmetric. Check rail current accounting.
        residual=d['rail_injection_A']-d['ref_current_A']-2*(d['i2c_card_V']-d['rail_V'])/1e4
        assert np.max(abs(residual))<2e-8, (name,float(np.max(abs(residual))))
        curves[name]=d
        for v in [1.8,2.1]:
            selected.append({'case':name,'held_rail_V':v,**{k:float(np.interp(v,d['rail_V'],d[k])) for k in vec if k!='rail_V'}})

# Illustrate uncertainty in current: vary assumed MOS parameters, not hardware.
sensitivity=[]
for vt in [.4,.6,.8]:
    for kp in [.002,.02,.2]:
        d=sp.run(f'original_vth{vt}_kp{kp}'.replace('.','p'),u18_net(vth=vt,kp=kp),vec)
        sensitivity.append({'assumed_vth_V':vt,'assumed_kp_A_V2':kp,
                            'rail_injection_at_2p1_A':float(np.interp(2.1,d['rail_V'],d['rail_injection_A']))})

cv={'source_V':'v(source)','pin_V':'v(pin)','bank_injection_A':'i(Vbank)','source_current_A':'i(Vsource)'}
clamps={};clamp_selected=[]
for vcco in [0,1.8,2.5]:
    name=f'generic_clamp_vcco{vcco}'.replace('.','p')
    d=sp.run(name,clamp_net(vcco),cv);clamps[vcco]=d
    assert np.max(abs(-d['source_current_A']-d['bank_injection_A']-d['pin_V']/1e7))<1e-9
    clamp_selected.append({'VCCO_V':vcco,**{k:float(np.interp(2.1,d['source_V'],d[k])) for k in cv}})

plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
fig,ax=plt.subplots(2,2,figsize=(12,8.5))
styles=[('original_standalone','Original, FMC disconnected','#b45309','-'),
        ('corrected_standalone','Corrected, FMC disconnected','#00866b','-'),
        ('original_carrier_pullups','Original + KC705 pullups','#b45309','--'),
        ('corrected_carrier_pullups','Corrected + KC705 pullups','#00866b',':')]
for key,label,col,ls in styles:
    d=curves[key];ax[0,0].plot(d['rail_V'],d['i2c_card_V'],label=label,color=col,ls=ls)
ax[0,0].set(xlabel='Held card rail (V)',ylabel='FMC C30/C31 idle voltage (V)',title='U18 is on the management I2C bus')
ax[0,0].legend(fontsize=7.5)
for key,label,col,ls in styles:
    d=curves[key];ax[0,1].semilogy(d['rail_V'],1e6*d['rail_injection_A'],label=label,color=col,ls=ls)
ax[0,1].set(xlabel='Held card rail (V)',ylabel='Current into card rail (uA)',title='Bias repair still leaves carrier-pullup backfeed')
ax[0,1].legend(fontsize=7.5)

for vcco,col in [(1.8,'#b45309'),(2.5,'#00866b')]:
    ax[1,0].hlines(vcco+.2,1.8,2.7,label=f'VCCO={vcco}: recommended max',color=col)
    ax[1,0].hlines(vcco+.55,1.8,2.7,label=f'VCCO={vcco}: HR absolute max',color=col,linestyle='--')
ax[1,0].plot([1.8,2.7],[1.8,2.7],color='#444',label='Signal = card rail')
ax[1,0].axvline(2.1,color='#888',ls=':')
ax[1,0].set(xlabel='Signal voltage (V)',ylabel='Signal / limit (V)',title='Direct U17-to-Kintex pins: datasheet limits')
ax[1,0].legend(fontsize=7)
for vcco,d in clamps.items():
    ax[1,1].plot(d['source_V'],1e3*d['bank_injection_A'],label=f'VCCO={vcco} V')
ax[1,1].set(xlabel='Weak-pullup source (V)',ylabel='Generic clamp injection (mA / pin)',title='Illustrative only: an unpowered bank can be fed')
ax[1,1].legend(fontsize=8)
for a in ax.flat:a.grid(alpha=.2)
fig.suptitle('Keeping the card rail at 2.1 V: electrical risks',fontsize=17,fontweight='bold')
fig.text(.5,.014,'ngspice mechanism tests + AMD limits. Generic MOS/clamp models cannot predict device destruction, lifetime or exact hardware currents.',ha='center',fontsize=8.8)
fig.tight_layout(rect=(0,.035,1,.95))
fig.savefig(OUT/'risk_results.png',dpi=170)
result={'engine':sp.version,'u18':selected,'generic_clamp_at_source_2p1':clamp_selected,
        'mos_sensitivity':sensitivity,
        'limits':{'Kintex_HR_recommended':'VIN <= VCCO+0.2 V','Kintex_HR_absolute':'VIN <= VCCO+0.55 V',
                  'source':'https://docs.amd.com/api/khub/documents/BhulK6GRrzUpQYw0lzrnMA/content'},
        'limitations':['No IC destruction or lifetime model','No vendor PCA9306 or Kintex simulation model executed',
                       'Held rail is boundary condition, not a regulator model','Generic clamp current is illustrative',
                       'KC705 I2C mux transfer, startup, powered-off mux and PCB ringing not modeled',
                       'External M.2 module unknown; +1V8A distinct rail not modeled']}
(OUT/'results.json').write_text(json.dumps(result,indent=2),encoding='utf8')
print(json.dumps({'u18':selected,'generic_clamp':clamp_selected,'mos_current_range_A':[min(r['rail_injection_at_2p1_A'] for r in sensitivity),max(r['rail_injection_at_2p1_A'] for r in sensitivity)]},indent=2))
