"""50 MHz clock topology sensitivity study; not a transistor/IBIS board sign-off.

Run with Python + numpy + matplotlib and KiCad 10 ngspice.dll.
No original design files are changed. Initial capacitor charges represent either
periodic steady state or a long idle; this avoids falsely claiming a short run
has settled the 0.5 ms bias time constant.
"""
from pathlib import Path
import ctypes as ct
import csv
import json
import os
import itertools
import hashlib
from datetime import datetime, timezone
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
DLL_DIR = Path('C:/Program Files/KiCad/10.0/bin')
os.chdir(OUT)

class VecInfo(ct.Structure):
    _fields_ = [('name',ct.c_char_p),('type',ct.c_int),('flags',ct.c_short),
                ('real',ct.POINTER(ct.c_double)),('complex',ct.c_void_p),('length',ct.c_int)]

class Spice:
    def __init__(self):
        self.path = os.add_dll_directory(str(DLL_DIR))
        self.lib = ct.CDLL(str(DLL_DIR/'ngspice.dll'))
        self.logs=[]
        C=ct.CFUNCTYPE(ct.c_int,ct.c_char_p,ct.c_int,ct.c_void_p)
        E=ct.CFUNCTYPE(ct.c_int,ct.c_int,ct.c_bool,ct.c_bool,ct.c_int,ct.c_void_p)
        self.cb=C(lambda s,i,u:self.log(s)); self.st=C(lambda s,i,u:0)
        self.ex=E(lambda a,b,c,d,e:0)
        self.lib.ngSpice_Init.argtypes=[ct.c_void_p]*7
        self.lib.ngSpice_Init(self.cb,self.st,self.ex,None,None,None,None)
        self.lib.ngSpice_Command.argtypes=[ct.c_char_p]
        self.lib.ngSpice_Circ.argtypes=[ct.POINTER(ct.c_char_p)]
        self.lib.ngGet_Vec_Info.argtypes=[ct.c_char_p]
        self.lib.ngGet_Vec_Info.restype=ct.POINTER(VecInfo)
        self.cmd('version')
    def log(self,s):
        self.logs.append(s.decode(errors='replace')); return 0
    def cmd(self,s):
        if self.lib.ngSpice_Command(s.encode()): raise RuntimeError(s)
    def run(self,name,netlist,keep=False):
        self.cmd('destroy all'); start=len(self.logs)
        (OUT/'netlists'/f'{name}.cir').write_text(netlist,encoding='ascii')
        lines=netlist.strip().splitlines()
        arr=(ct.c_char_p*(len(lines)+1))(*[s.encode() for s in lines],None)
        if self.lib.ngSpice_Circ(arr): raise RuntimeError(name)
        self.cmd('run')
        data={}
        for label,vector in {'t':'time','p':'v(p)','n':'v(n)','adc_p':'v(ap)',
                             'adc_n':'v(an)','ip':'vp#branch','in':'vn#branch'}.items():
            ptr=self.lib.ngGet_Vec_Info(vector.encode())
            if not ptr or not ptr.contents.real: raise RuntimeError((name,vector))
            data[label]=np.ctypeslib.as_array(ptr.contents.real,(ptr.contents.length,)).copy()
        data['diff']=data['adc_p']-data['adc_n']
        logs=self.logs[start:]
        (OUT/'logs'/f'{name}.log').write_text('\n'.join(logs))
        if any('error:' in s.lower() or 'timestep too small' in s.lower() for s in logs):
            raise RuntimeError((name,logs))
        if not all(np.isfinite(v).all() for v in data.values()): raise RuntimeError(name)
        if keep:
            with (OUT/f'{name}.csv').open('w',newline='') as f:
                w=csv.writer(f); w.writerow(data); w.writerows(zip(*data.values()))
        return data

def circuit(mode='existing_low',state='steady',v=1.8,rp=25,rn=25,
            vc=1.5,edge=1e-9,td=0,cp=5e-12,cn=5e-12,rb=100):
    floating=mode=='existing_float'
    bridge=mode!='remove_r165'
    if bridge and not floating:
        ph=v*(rn+rb)/(rp+rn+rb); nh=v*rn/(rp+rn+rb)
    elif floating:
        ph=v; nh=v
    else:
        ph=v; nh=0
    # Initial ADC pin voltages just before the low-to-high clock waveform.
    ap0=vc-(.5*ph if state=='steady' else 0)
    an0=vc-(.5*nh if state=='steady' else 0)
    falling=state=='idle_high'
    if falling:
        # Source starts HIGH after a long pause, so AC-coupled inputs rebias to vc.
        ap0=vc; an0=vc
    lo,hi=(v,0) if falling else (0,v)
    nsrc='0'
    rdrive_n='1e12' if floating else str(rn)
    # Eight-section 50-ohm LC pi ladders, 2 ohms total series loss per trace.
    # This is an assumed line, NOT geometry/material extraction. The finite LC
    # model avoids a ngspice lossless-T/UIC convergence problem on idle restarts.
    if td:
        parts=[]; sections=8
        for leg,first,last in [('p','dp','p'),('n','dn','n')]:
            l=50*td/sections; c=td/(50*sections)
            parts.append(f'Ct{leg}start {first} 0 {c/2}')
            prev=first
            for i in range(sections):
                node=last if i==sections-1 else f'{leg}line{i}'
                mid=f'{leg}res{i}'
                parts.extend([f'Rt{leg}{i} {prev} {mid} 0.25',
                              f'Lt{leg}{i} {mid} {node} {l}',
                              f'Ct{leg}{i} {node} 0 {c/2 if i==sections-1 else c}'])
                prev=node
        lines='\n'.join(parts)
    else:
        lines='Rwirep dp p 0.001\nRwiren dn n 0.001'
    p0=ph if falling else 0
    n0=nh if falling else 0
    return f'''ADS5282 50MHz {mode} {state}: illustrative driver, not vendor IBIS
* C60/C61=100n assumed from schematic; fitted values must be verified.
* ADS clock-input bias is 5k per leg to 1.5V typical, DIFF_CLK=1.
* Input capacitance {cp}/{cn} F, driver resistance and line are ASSUMPTIONS.
* Steady-state capacitor precharge is analytic; idle cases start fully rebias-settled.
Vp sp 0 PULSE({lo} {hi} 100n {edge} {edge} {10e-9-edge} 20n)
Vn sn 0 {nsrc}
Rp sp dp {rp}
Rn sn dn {rdrive_n}
{lines}
{('R165 p n '+str(rb)) if bridge else '* R165 removed'}
C61 p ap 100n
C60 n an 100n
Vbias bias 0 {vc}
Rbp ap bias 5k
Rbn an bias 5k
Cap ap 0 {cp}
Can an 0 {cn}
Cfpgafloat dn 0 3p
.ic v(ap)={ap0} v(an)={an0} v(p)={p0} v(n)={n0} v(dp)={p0} v(dn)={n0}
.options reltol=1e-5 abstol=1e-12
.tran 0.05n 420n uic
.save v(p) v(n) v(ap) v(an) i(Vp) i(Vn)
.end
'''

def metrics(d,td=0,state='steady'):
    m=d['t']>300e-9
    stress=d['t']>90e-9
    phase=np.mod(d['t']-100e-9-td,20e-9)
    high=m&(phase>5e-9)&(phase<9e-9)
    low=m&(phase>15e-9)&(phase<19e-9)
    if state=='idle_high': high,low=low,high
    return {'diff_pp_last_V':float(np.ptp(d['diff'][m])),
            'diff_min_last_V':float(np.min(d['diff'][m])),
            'diff_max_last_V':float(np.max(d['diff'][m])),
            'diff_high_plateau_median_V':float(np.median(d['diff'][high])),
            'diff_low_plateau_median_V':float(np.median(d['diff'][low])),
            'diff_high_plateau_min_V':float(np.min(d['diff'][high])),
            'diff_low_plateau_max_V':float(np.max(d['diff'][low])),
            'adc_p_min_V':float(np.min(d['adc_p'][stress])),
            'adc_p_max_V':float(np.max(d['adc_p'][stress])),
            'adc_n_min_V':float(np.min(d['adc_n'][stress])),
            'adc_n_max_V':float(np.max(d['adc_n'][stress])),
            'p_driver_peak_mA':float(np.max(np.abs(d['ip'][stress]))*1000),
            'n_driver_peak_mA':float(np.max(np.abs(d['in'][stress]))*1000),
            'adc_common_mode_pp_last_V':float(np.ptp((d['adc_p'][m]+d['adc_n'][m])/2))}

for sub in ['netlists','logs']: (OUT/sub).mkdir(exist_ok=True)
sp=Spice(); summary={'run_utc':datetime.now(timezone.utc).isoformat(),
 'engine':'KiCad 10 ngspice 46 shared library','hardware_verified':False,
 'vendor_fpga_ibis_used':False,'adc_transistor_model_used':False,
 'assumptions':['Clock sources are ideal 0-VCCO square waves with 1ns edges unless stated.',
 'FPGA pull-up and pull-down represented by fixed resistances; not mapped to DRIVE settings.',
 'ADC differential clock mode modeled as 5k bias per leg; capacitance assumed 5pF.',
 'C60/C61 assumed 100nF; R165 assumed 100ohm, per schematic intent.',
 'No ADC threshold/comparator/PLL model, noise, jitter, clamp, thermal or package model.',
 'Some tests add assumed uncoupled 50ohm LC line ladders with 2ohm total trace loss, not extracted routing.',
 'Initial capacitor charges describe periodic steady state or long settled idle.',
 'No valid conversion, firmware capture or fabricated-board safety guarantee follows.'],
 'sources':{'adc':'https://www.ti.com/lit/ds/symlink/ads5282.pdf',
 'fpga':'https://docs.amd.com/v/u/en-US/ds182_Kintex_7_Data_Sheet'},'cases':{}}
waves={}
for mode in ['existing_low','existing_float','remove_r165']:
    for state in ['steady','idle_low','idle_high']:
        name=f'{mode}_{state}'
        d=sp.run(name,circuit(mode,state),keep=True)
        summary['cases'][name]={'mode':mode,'state':state,'kind':'nominal_lumped',**metrics(d,state=state)}
        waves[name]=d

# Correlated parameter sets are explicit sensitivity cases, not vendor PVT corners.
for mode,state,rp,rn,v,vc in itertools.product(
        ['existing_low','remove_r165'],['steady','idle_low','idle_high'],
        [10,25,60],[10,60],[1.71,1.89],[1.425,1.575]):
    name=f'sweep_{mode}_{state}_rp{rp}_rn{rn}_v{v}_b{vc}'.replace('.','p')
    d=sp.run(name,circuit(mode,state,v=v,rp=rp,rn=rn,vc=vc))
    summary['cases'][name]={'mode':mode,'state':state,'kind':'lumped_sensitivity',
          'rp':rp,'rn':rn,'vcco':v,'bias':vc,**metrics(d,state=state)}

for mode,state,r,td,edge in itertools.product(
        ['existing_low','remove_r165'],['steady','idle_low','idle_high'],
        [10,25,60],[.5e-9,1.5e-9],[.5e-9,2e-9]):
    name=f'line_{mode}_{state}_r{r}_td{td*1e9}_edge{edge*1e9}'.replace('.','p')
    keep=(r==25 and td==.5e-9 and edge==.5e-9 and state=='steady')
    d=sp.run(name,circuit(mode,state,rp=r,rn=r,td=td,edge=edge),keep=keep)
    summary['cases'][name]={'mode':mode,'state':state,'kind':'assumed_line_sensitivity',
                          'r':r,'td_ns':td*1e9,'edge_ns':edge*1e9,**metrics(d,td,state)}
    if keep: waves[name]=d

# Analytical cross-check of the two nominal steady configurations.
check={}
for name,target in [('existing_low_steady',1.2),('remove_r165_steady',1.8)]:
    actual=summary['cases'][name]['diff_pp_last_V']
    check[name]={'expected_lumped_pp':target,'simulated_pp':actual,
                 'within_2_percent':abs(actual-target)<.02*target}
summary['checks']=check
summary['case_count']=len(summary['cases'])
summary['all_numerical_checks_passed']=all(x['within_2_percent'] for x in check.values())
summary['pcb_sha256']=hashlib.sha256((ROOT/'CaravelReRAM-SenseEval_v1.2F/CaravelReRAM-SenseEval.kicad_pcb').read_bytes()).hexdigest()
(OUT/'simulation_summary.json').write_text(json.dumps(summary,indent=2))
fields=['case','kind','mode','state','diff_pp_last_V','adc_p_min_V','adc_p_max_V','adc_n_min_V','adc_n_max_V','p_driver_peak_mA','n_driver_peak_mA']
with (OUT/'case_summary.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader()
    for name,row in summary['cases'].items(): w.writerow({'case':name,**row})

fig,axes=plt.subplots(3,2,figsize=(12,9),sharex=True)
for row,mode in enumerate(['existing_low','existing_float','remove_r165']):
    d=waves[mode+'_steady'];m=(d['t']>=220e-9)&(d['t']<=300e-9)
    t=(d['t'][m]-220e-9)*1e9
    axes[row,0].plot(t,d['adc_p'][m],label='ADC CLKP')
    axes[row,0].plot(t,d['adc_n'][m],label='ADC CLKN')
    axes[row,1].plot(t,d['diff'][m],color='#8c3a9a',label='CLKP - CLKN')
    axes[row,0].set_ylabel(mode.replace('_',' ')+'\nVoltage (V)')
    for ax in axes[row]: ax.grid(alpha=.25);ax.legend(fontsize=8)
for ax in axes[-1]: ax.set_xlabel('Time (ns), 50 MHz = 20 ns period')
fig.suptitle('Clock topology comparison: illustrative 25 ohm drivers, no line model\nDIFF_CLK=1; 100 nF coupling; 5 kohm bias to 1.5 V; not hardware verification',fontsize=12)
fig.tight_layout(rect=[0,0,1,.94]);fig.savefig(OUT/'clock_comparison.png',dpi=170);plt.close(fig)
print(json.dumps({'cases':summary['case_count'],'checks':check,
 'nominal':{k:v for k,v in summary['cases'].items() if v['kind']=='nominal_lumped'}},indent=2))
