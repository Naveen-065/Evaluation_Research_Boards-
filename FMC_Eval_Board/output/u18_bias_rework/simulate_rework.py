"""PCA9306 bias rework: ngspice equivalent-circuit experiments.

NOT TI's encrypted HSPICE model; NOT an AMS1117 vendor model.
Level-1 MOS parameters are assumptions, not fitted to the measured 2.1 V.
Only output/u18_bias_rework is written. Board sources are unchanged.
Run: python simulate_rework.py
"""
from pathlib import Path
import ctypes as ct
import os, csv, json, hashlib
from datetime import datetime, timezone
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parent
os.chdir(OUT)
DLLDIR = Path('C:/Program Files/KiCad/10.0/bin')

class VecInfo(ct.Structure):
    _fields_ = [('name',ct.c_char_p),('type',ct.c_int),('flags',ct.c_short),
                ('real',ct.POINTER(ct.c_double)),('complex',ct.c_void_p),('length',ct.c_int)]

class Spice:
    def __init__(self):
        self.path = os.add_dll_directory(str(DLLDIR))
        self.lib = ct.CDLL(str(DLLDIR/'ngspice.dll'))
        self.logs=[]
        cb=ct.CFUNCTYPE(ct.c_int,ct.c_char_p,ct.c_int,ct.c_void_p)
        ex=ct.CFUNCTYPE(ct.c_int,ct.c_int,ct.c_bool,ct.c_bool,ct.c_int,ct.c_void_p)
        self.cb=cb(lambda s,i,u:self.message(s))
        self.status=cb(lambda s,i,u:0)
        self.exit=ex(lambda a,b,c,d,e:0)
        self.lib.ngSpice_Init.argtypes=[ct.c_void_p]*7
        self.lib.ngSpice_Init(self.cb,self.status,self.exit,None,None,None,None)
        self.lib.ngSpice_Command.argtypes=[ct.c_char_p]
        self.lib.ngSpice_Circ.argtypes=[ct.POINTER(ct.c_char_p)]
        self.lib.ngGet_Vec_Info.argtypes=[ct.c_char_p]
        self.lib.ngGet_Vec_Info.restype=ct.POINTER(VecInfo)
        self.command('version')
        self.version='\n'.join(self.logs)
    def message(self,s):
        self.logs.append(s.decode(errors='replace'));return 0
    def command(self,s):
        rc=self.lib.ngSpice_Command(s.encode())
        if rc: raise RuntimeError((s,rc))
    def run(self,name,netlist,vectors):
        self.command('destroy all')
        start=len(self.logs)
        (OUT/(name+'.cir')).write_text(netlist,encoding='ascii')
        lines=netlist.strip().splitlines()
        arr=(ct.c_char_p*(len(lines)+1))(*[s.encode() for s in lines],None)
        if self.lib.ngSpice_Circ(arr):raise RuntimeError('load '+name)
        self.command('run')
        data={}
        for k,v in vectors.items():
            ptr=self.lib.ngGet_Vec_Info(v.encode())
            if not ptr or ptr.contents.length<1:raise RuntimeError((name,v,self.logs[start:]))
            data[k]=np.ctypeslib.as_array(ptr.contents.real,(ptr.contents.length,)).copy()
        log='\n'.join(self.logs[start:])
        (OUT/(name+'.log')).write_text(log,encoding='utf8')
        if 'Error:' in log or 'Timestep too small' in log:raise RuntimeError(log)
        with (OUT/(name+'.csv')).open('w',newline='') as f:
            w=csv.writer(f);w.writerow(data);w.writerows(zip(*data.values()))
        return data

def circuit(mode='corrected',cap='100n',analysis='dc',kp=.02,vth=.6,bleed=None):
    corrected=mode=='corrected'
    ramp=analysis=='startup'
    high='PWL(0 0 100u 3.3)' if ramp else '3.3'
    target='PWL(0 0 100u 1.8)' if ramp else '1.8'
    bias='R56 high bias 200k\nVlink bias ref2 0' if corrected else (
        'R56 high bias 200k\nVlink high ref2 0' if mode=='resistor_only' else
        'R56 high bias 10k\nVlink high ref2 0')
    load='Vload loadctl 0 0.001'
    drvl='VdriveL ctlL 0 0';drvh='VdriveH ctlH 0 0'
    analysisline='.dc Vload 0 0.02 0.0001'
    if analysis=='startup':analysisline='.tran 2u 60m 0 5u uic'
    elif analysis=='i2c':
        drvl='VdriveL ctlL 0 PWL(0 0 5u 0 5.01u 1 10u 1 10.01u 0)'
        drvh='VdriveH ctlH 0 PWL(0 0 20u 0 20.01u 1 25u 1 25.01u 0)'
        analysisline='.tran 5n 40u 0 20n'
    return f'''PCA9306 {mode} equivalent model, {analysis}, C58={cap}
* Not a vendor PCA9306 or AMS1117 transistor model.
* Reference MOS KP={kp}, VTO={vth}; bus MOS uses same parameters.
* LDO sources only: 20 A/V feedback gain, 0.8 A ceiling; no sink capability.
* Does not model AMS1117 loop stability, heating, minimum load or reverse failure.
* Fixed load controlled by Vload, plus 10 Megohm leakage and 10k I2C pullups.
.options reltol=1e-5 abstol=1e-11 vntol=1e-7 itl1=500
Vhigh high 0 {high}
Vtarget target 0 {target}
Bldo 0 rail I=max(0,min(0.8,20*(v(target)-v(rail))))
{load}
Bload rail 0 I=v(loadctl)
Rleak rail 0 10Meg
{('Rbleed rail 0 '+str(bleed)) if bleed else '* No additional rail bleed resistor'}
Crail rail 0 10u
{bias}
C58 ref2 0 {cap}
Mref ref2 bias rail 0 PASS W=1u L=1u
Mscl sclh bias scll 0 PASS W=1u L=1u
Msda sdah bias sdal 0 PASS W=1u L=1u
.model PASS NMOS (LEVEL=1 VTO={vth} KP={kp} LAMBDA=0 GAMMA=0)
R54 rail scll 10k
R57 high sclh 10k
R53 rail sdal 10k
R58 high sdah 10k
Csl scll 0 50p
Csh sclh 0 50p
Cdl sdal 0 50p
Cdh sdah 0 50p
{drvl}
{drvh}
SdrvL scll 0 ctlL 0 OD
SdrvH sclh 0 ctlH 0 OD
.model OD SW(RON=10 ROFF=1e12 VT=0.5 VH=0.1)
{analysisline}
.save v(loadctl) v(rail) v(bias) v(ref2) v(scll) v(sclh) i(Vlink)
.end
'''

sp=Spice()
vectors={'load_A':'v(loadctl)','rail_V':'v(rail)','bias_V':'v(bias)',
         'ref2_V':'v(ref2)','scl_low_V':'v(scll)','scl_high_V':'v(sclh)','injection_A':'i(Vlink)'}
dc={}
for mode in ['original','resistor_only','corrected']:
    dc[mode]=sp.run('dc_'+mode,circuit(mode),vectors)

starts={}
tv={k:v for k,v in vectors.items() if k!='load_A'};tv={'time_s':'time',**tv}
for cap in ['100n','100p']:
    starts[cap]=sp.run('startup_'+cap,circuit(cap=cap,analysis='startup'),tv)
bus=sp.run('i2c_bidirectional',circuit(cap='100p',analysis='i2c'),tv)

rows=[]
for mode in dc:
    for load in [0,.0001,.001,.01]:
        rows.append({'case':mode,'assumed_load_A':load,**{
            k:float(np.interp(load,dc[mode]['load_A'],dc[mode][k])) for k in vectors if k!='load_A'}})
with (OUT/'dc_selected_results.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)

sweep=[]
for vth in [.4,.6,.8]:
    for kp in [.002,.02,.2]:
        for mode in ['original','corrected']:
            name=f'sensitivity_{mode}_vth{vth}_kp{kp}'.replace('.','p')
            d=sp.run(name,circuit(mode,kp=kp,vth=vth),vectors)
            sweep.append({'case':mode,'assumed_vth_V':vth,'assumed_kp_A_V2':kp,
                          'rail_at_1mA_V':float(np.interp(.001,d['load_A'],d['rail_V']))})

bleed=sp.run('dc_corrected_100k_bleed',circuit(bleed='100k'),vectors)
metrics={}
for cap,d in starts.items():
    target=d['bias_V'][-1];ids=np.flatnonzero(d['bias_V']>=.99*target)
    metrics[cap]={'final_bias_V':float(target),'time_to_99pct_from_ramp_start_s':float(d['time_s'][ids[0]]),
                 'final_rail_V':float(d['rail_V'][-1])}
for t,label in [(8e-6,'low_side_pulls_low'),(23e-6,'high_side_pulls_low'),(38e-6,'released')]:
    metrics[label]={k:float(np.interp(t,bus['time_s'],bus[k])) for k in ['scl_low_V','scl_high_V']}

plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
fig,axes=plt.subplots(2,2,figsize=(12,8.5))
colors={'original':'#b45309','resistor_only':'#d4a017','corrected':'#007f83'}
for mode,d in dc.items():
    axes[0,0].plot(d['load_A']*1000,d['rail_V'],label=mode.replace('_',' '),color=colors[mode],
                   linestyle='--' if mode=='resistor_only' else '-')
axes[0,0].axhline(1.8,color='#555',linestyle=':',linewidth=1)
axes[0,0].set(xlabel='Assumed rail load (mA)',ylabel='+1V8 rail (V)',title='DC: changing R56 alone leaves the fault')
axes[0,0].legend(fontsize=8)
for cap,d in starts.items():
    axes[0,1].plot(d['time_s']*1000,d['bias_V'],label='C58 = '+('100 nF (existing)' if cap=='100n' else '100 pF'),linewidth=2)
axes[0,1].set(xlabel='Time from supply ramp start (ms)',ylabel='Joined pins 7/8 (V)',title='Corrected circuit: bias startup')
axes[0,1].legend(fontsize=8)
axes[1,0].plot(bus['time_s']*1e6,bus['scl_low_V'],label='1.8 V side',color='#007f83')
axes[1,0].plot(bus['time_s']*1e6,bus['scl_high_V'],label='3.3 V side',color='#b45309')
axes[1,0].set(xlabel='Time (us)',ylabel='SCL voltage (V)',title='After startup: low passes in both directions')
axes[1,0].legend(fontsize=8)
for mode in ['original','corrected']:
    values=[r['rail_at_1mA_V'] for r in sweep if r['case']==mode]
    axes[1,1].scatter([mode]*len(values),values,color=colors[mode],s=36,alpha=.7)
axes[1,1].axhline(1.8,color='#555',linestyle=':',linewidth=1)
axes[1,1].set(ylabel='+1V8 rail at assumed 1 mA load (V)',title='Sensitivity to assumed MOS parameters')
for ax in axes.flat:ax.grid(alpha=.18)
fig.suptitle('U18 bias rework - ngspice equivalent-circuit results',fontsize=17,fontweight='bold')
fig.text(.5,.018,'Illustrative model, not TI silicon validation. Original fault voltage depends on unknown device parameters and rail load.',ha='center',fontsize=9)
fig.tight_layout(rect=(0,.035,1,.95))
fig.savefig(OUT/'simulation_results.png',dpi=170)

summary={'run_utc':datetime.now(timezone.utc).isoformat(),'engine':sp.version,
         'model':'Generic level-1 MOS functional equivalent; non-sinking idealized 1.8 V regulator',
         'vendor_model_status':'Existing TI SCEJ212A model is .prot FREELIB encrypted HSPICE; not executed.',
         'assumptions':['No model parameters fitted to measured 2.1 V','Nominal VTO=0.6 V; KP=0.02 A/V^2; swept 0.4-0.8 V and 0.002-0.2 A/V^2',
                        'Default active load=1 mA; DC sweep 0-20 mA; actual board load unknown',
                        '3.3 V and 1.8 V target ramp together over 100 us for startup',
                        '10 uF rail capacitance; each I2C node 50 pF; actual PCB pullups 10k',
                        'No regulator loop stability, damage, thermal, ESD, silicon corners or full FPGA interface certification'],
         'selected_dc':rows,'metrics':metrics,'sensitivity':sweep,
         'no_load_with_100k_bleed_V':float(bleed['rail_V'][0])}
(OUT/'results.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
print(json.dumps({'metrics':metrics,'selected_dc':rows,'bleed_no_load':summary['no_load_with_100k_bleed_V']},indent=2))
