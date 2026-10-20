"""ngspice transmission-line sensitivity study of the actual ADC/FMC routing.

Run with system Python (numpy/matplotlib) and KiCad 10 ngspice.dll.
Behavioral driver, NOT a validated ADS5282 transistor/IBIS simulation.
Only this output directory is written; no HDL, XDC, PCB or hardware changes.
"""
from pathlib import Path
import csv, ctypes as ct, hashlib, itertools, json, os
from datetime import datetime, timezone
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
for folder in ('netlists', 'logs', 'waveforms'):
    (OUT/folder).mkdir(exist_ok=True)
os.chdir(OUT)
ROUTES = {
 'OUT1': [53.784,51.547,125.813,125.751],
 'OUT2': [40.553,38.722,124.503,124.542],
 'OUT3': [29.685,27.854,124.574,124.540],
 'OUT4': [58.356,60.184,126.550,126.560],
 'OUT5': [86.265,89.403,125.149,125.168],
 'LCLK': [55.011,56.502,125.188,125.144],
 'ADCLK': [49.977,51.468,138.662,138.702],
}
TOPOLOGIES = ['none', 'receiver100', 'connector100', 'source94']
LABELS = {'none':'No termination', 'receiver100':'100 ohm at receiver',
          'connector100':'100 ohm at FMC connector', 'source94':'94 ohm at ADC source'}
UI = 1/120e6
START = 80e-9
NBITS = 63
NOMINAL = dict(zd=100., zc=100., psmm_d=6.3, psmm_c=7.0, extra=0.10e-9,
               crx=5e-12, edge=.7e-9, compliance=.9, cm=1.2, current=3.5e-3,
               term_rx=100., term_source=94., loss=.8, pkg_rx=1e-9)

class VecInfo(ct.Structure):
    _fields_ = [('name',ct.c_char_p),('type',ct.c_int),('flags',ct.c_short),
                ('real',ct.POINTER(ct.c_double)),('complex',ct.c_void_p),('length',ct.c_int)]

class Spice:
    def __init__(self):
        path=Path('C:/Program Files/KiCad/10.0/bin')
        self.dllpath=os.add_dll_directory(str(path))
        self.lib=ct.CDLL(str(path/'ngspice.dll')); self.logs=[]
        cb=ct.CFUNCTYPE(ct.c_int,ct.c_char_p,ct.c_int,ct.c_void_p)
        ex=ct.CFUNCTYPE(ct.c_int,ct.c_int,ct.c_bool,ct.c_bool,ct.c_int,ct.c_void_p)
        self.cb=cb(lambda s,i,u:self.message(s)); self.st=cb(lambda s,i,u:0)
        self.ex=ex(lambda a,b,c,d,e:0)
        self.lib.ngSpice_Init.argtypes=[ct.c_void_p]*7
        self.lib.ngSpice_Init(self.cb,self.st,self.ex,None,None,None,None)
        self.lib.ngSpice_Command.argtypes=[ct.c_char_p]
        self.lib.ngSpice_Circ.argtypes=[ct.POINTER(ct.c_char_p)]
        self.lib.ngGet_Vec_Info.argtypes=[ct.c_char_p]
        self.lib.ngGet_Vec_Info.restype=ct.POINTER(VecInfo)
        self.cmd('version'); self.version='\n'.join(self.logs)
    def message(self,s): self.logs.append(s.decode(errors='replace')); return 0
    def cmd(self,s):
        if self.lib.ngSpice_Command(s.encode()): raise RuntimeError(s)
    def run(self,name,netlist,save=False):
        self.cmd('destroy all'); start=len(self.logs)
        (OUT/'netlists'/f'{name}.cir').write_text(netlist,encoding='ascii')
        lines=netlist.strip().splitlines()
        arr=(ct.c_char_p*(len(lines)+1))(*[s.encode() for s in lines],None)
        if self.lib.ngSpice_Circ(arr): raise RuntimeError('load '+name)
        self.cmd('run'); d={}
        for label,vector in {'t':'time','p':'v(rp)','n':'v(rn)',
             'sp':'v(sp)','sn':'v(sn)','jp':'v(jp)','jn':'v(jn)','q':'v(q)'}.items():
            ptr=self.lib.ngGet_Vec_Info(vector.encode())
            if not ptr or not ptr.contents.real: raise RuntimeError((name,vector,self.logs[start:]))
            d[label]=np.ctypeslib.as_array(ptr.contents.real,(ptr.contents.length,)).copy()
        log='\n'.join(self.logs[start:]); (OUT/'logs'/f'{name}.log').write_text(log)
        if 'error:' in log.lower() or 'timestep too small' in log.lower(): raise RuntimeError(log)
        if not all(np.isfinite(a).all() for a in d.values()): raise RuntimeError(name)
        d['diff']=d['p']-d['n']; d['cm']=(d['p']+d['n'])/2
        if save:
            with (OUT/'waveforms'/f'{name}.csv').open('w',newline='') as f:
                w=csv.writer(f);w.writerow(d);w.writerows(zip(*d.values()))
        return d

def sequence(pair):
    if pair=='LCLK': return np.array([(-1 if i%2==0 else 1) for i in range(NBITS)])
    if pair=='ADCLK': return np.array([(-1 if (i//6)%2==0 else 1) for i in range(NBITS)])
    state=0x5d; seq=[]
    for i in range(NBITS):
        seq.append(1 if state&1 else -1)
        state=(state>>1)|((((state>>0)^(state>>1))&1)<<6)
    return np.array(seq)

def circuit(pair, topology, p, static=False):
    bits=sequence(pair); wave=[(0.,float(bits[0]))]
    if not static:
        wave.append((START,float(bits[0])))
        for i in range(1,len(bits)):
            if bits[i]!=bits[i-1]:
                wave.extend([(START+i*UI-p['edge']/2,float(bits[i-1])),
                             (START+i*UI+p['edge']/2,float(bits[i]))])
    stop=START+NBITS*UI if not static else 180e-9
    wave.append((stop,float(bits[-1] if not static else bits[0])))
    lines=[f'ADC LVDS {pair} {topology}: finite-compliance behavioral model',
      '* Driver compliance is ASSUMED; no prediction of silicon damage.',
      '.options reltol=0.002 abstol=1e-9 vntol=1e-6',
      f'Vcm cm 0 {p["cm"]}', 'Vq q 0 PWL(']
    lines += [f'+ {t:.12g} {v:g}' for t,v in wave]; lines+=['+ )']
    # Current-mode source; high differential impedance below an assumed
    # compliance knee. The nonlinear differential shunt stops unphysical
    # ideal-source runaway without pretending to be a vendor clamp model.
    lines += [f'Bdrive sn sp I={p["current"]}*v(q)',
      'Rout sp sn 1meg',
      f'Bcompliance sp sn I=(max(v(sp,sn)-{p["compliance"]},0)-max(-v(sp,sn)-{p["compliance"]},0))/20',
      '* Assumed ideal fast common-mode regulation, same current in both legs.',
      'Bcmp sp cm I=0.05*(v(sp)+v(sn)-2*v(cm))',
      'Bcmn sn cm I=0.05*(v(sp)+v(sn)-2*v(cm))',
      'Cdp sp 0 2p','Cdn sn 0 2p',
      '* QFN package: TI SBOC249 0.5ohm/2nH/0.3pF per pin.',
      'Rpkp sp spp .5','Lpkp spp dp 2n','Cpkp dp 0 .3p',
      'Rpkn sn snn .5','Lpkn snn dn 2n','Cpkn dn 0 .3p']
    if topology=='source94': lines += [f'Rsrc sp sn {p["term_source"]}']
    for j,leg in enumerate(('p','n')):
        td1=ROUTES[pair][j]*p['psmm_d']*1e-12+p['extra']/2
        td2=ROUTES[pair][j+2]*p['psmm_c']*1e-12+p['extra']/2
        lines += [f'Td{leg} d{leg} 0 x{leg} 0 Z0={p["zd"]/2} TD={td1:.12g}',
                  f'Rld{leg} x{leg} j{leg} {p["loss"]/2}',
                  f'Tc{leg} j{leg} 0 y{leg} 0 Z0={p["zc"]/2} TD={td2:.12g}',
                  f'Rlc{leg} y{leg} z{leg} {p["loss"]/2}',
                  f'Lrx{leg} z{leg} r{leg} {p["pkg_rx"]}',
                  f'Crx{leg} r{leg} 0 {p["crx"]}',f'Rleak{leg} r{leg} 0 100meg']
    # Receiver resistor lies at package board entry, immediately before Lrx.
    if topology=='receiver100': lines += [f'Rrx zp zn {p["term_rx"]}']
    if topology=='connector100': lines += [f'Rconn jp jn {p["term_rx"]}']
    lines += [f'.tran 25p {stop:.12g} 0 25p',
              '.save v(rp) v(rn) v(sp) v(sn) v(jp) v(jn) v(q)', '.end']
    return '\n'.join(lines)+'\n'

def metrics(d,pair,p,static=False):
    delay=np.mean(ROUTES[pair][:2])*p['psmm_d']*1e-12+np.mean(ROUTES[pair][2:])*p['psmm_c']*1e-12+p['extra']
    valid=d['t']>START
    m=dict(pin_min_V=float(min(d['p'][valid].min(),d['n'][valid].min())),
      pin_max_V=float(max(d['p'][valid].max(),d['n'][valid].max())),
      diff_abs_peak_V=float(np.abs(d['diff'][valid]).max()),
      cm_min_V=float(d['cm'][valid].min()),cm_max_V=float(d['cm'][valid].max()),
      delay_ns=float(delay*1e9),
      time_above_2V_ns=float(np.trapezoid((((d['p']>2)|(d['n']>2))&valid).astype(float),d['t'])*1e9),
      steady_diff_V=float(np.mean(d['diff'][-100:])))
    if static: return m
    bits=sequence(pair); idx=np.arange(8,len(bits)-3)
    # Use the returned LCLK geometric flight time as the data sampling
    # reference; this includes the measured lane-to-clock route skew.
    clockdelay=np.mean(ROUTES['LCLK'][:2])*p['psmm_d']*1e-12+np.mean(ROUTES['LCLK'][2:])*p['psmm_c']*1e-12+p['extra']
    reference=clockdelay if pair.startswith('OUT') else delay
    m['lane_minus_clock_delay_ns']=float((delay-clockdelay)*1e9)
    center=START+(idx+.5)*UI+reference
    sample=np.interp(center,d['t'],d['diff'])*bits[idx]
    m['center_min_signed_V']=float(sample.min())
    m['center_wrong_bits']=int((sample<=0).sum())
    m['center_below_100mV']=int((sample<.1).sum())
    # Scan central UI positions. Largest contiguous window meeting 100mV
    # for every simulated symbol, referenced to geometric propagation delay.
    phases=np.linspace(0,1,101)
    worst=np.array([(np.interp(START+(idx+ph)*UI+reference,d['t'],d['diff'])*bits[idx]).min() for ph in phases])
    good=worst>=.1; best=run=0
    for b in good:
        run=run+1 if b else 0;best=max(best,run)
    m['estimated_valid_window_ns']=max(0,(best-1)*.01*UI*1e9)
    m['all_ui_min_signed_V']=float(worst.min())
    return m

def main():
    spice=Spice(); records=[]; selected={}
    # Includes actual links at nominal values plus deliberately broad
    # engineering sensitivities, not characterized manufacturing corners.
    jobs=[]
    for pair,topology in itertools.product(ROUTES,TOPOLOGIES):
        jobs.append((pair,topology,'nominal',NOMINAL.copy(),False))
    for pair,topology,bits in itertools.product(('OUT5','LCLK'),TOPOLOGIES,itertools.product((0,1),repeat=3)):
        a,b,c=bits;p=NOMINAL.copy()
        p.update(zd=(70.,130.)[a],zc=(90.,110.)[b],crx=(3e-12,10e-12)[c],
          edge=(.315e-9,1.4e-9)[c],compliance=(.55,1.2)[a],
          cm=(1.1,1.3)[b],current=(2.8e-3,4.2e-3)[c],
          term_source=(75.2,112.8)[b],term_rx=(99.,101.)[b],
          psmm_d=(5.8,7.2)[a],psmm_c=(6.7,7.3)[b])
        jobs.append((pair,topology,f'sensitivity{a}{b}{c}',p,False))
    for topology,knee in itertools.product(TOPOLOGIES,(.55,.9,1.2)):
        p=NOMINAL.copy();p['compliance']=knee
        jobs.append(('OUT5',topology,f'static_knee{knee}',p,True))
    for k,(pair,topology,corner,p,static) in enumerate(jobs):
        name=f'{pair}_{topology}_{corner}'.replace('.','p')
        save=corner=='nominal' and pair in ('OUT5','LCLK','ADCLK')
        d=spice.run(name,circuit(pair,topology,p,static),save)
        m=metrics(d,pair,p,static)
        records.append(dict(name=name,pair=pair,topology=topology,corner=corner,static=static,**p,**m))
        if save:selected[(pair,topology)]=d
        if k%8==0:print(f'Completed {k+1}/{len(jobs)}: {name}',flush=True)
    keys=list(dict.fromkeys(k for r in records for k in r))
    with (OUT/'case_summary.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(records)
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
       [ROOT/'output/kc705_adc_test/kc705_adc_test.xdc',ROOT/'output/kc705_adc_test/kc705_adc_test.v',
        ROOT/'output/kc705_adc_test/build/kc705_adc_test.bit',
        ROOT/'CaravelReRAM-SenseEval_v1.2F/CaravelReRAM-SenseEval.kicad_pcb']}
    summary=dict(run_utc=datetime.now(timezone.utc).isoformat(),engine=spice.version,
       routes_mm=ROUTES,nominal=NOMINAL,ui_ns=UI*1e9,source_hashes=hashes,
       assumptions=['Finite-compliance current source and fast common-mode regulator are behavioral assumptions.',
       'Compliance knees 0.55/0.9/1.2V are NOT vendor limits or measured ADC behavior.',
       'No FPGA clamp, ESD, latchup, power-sequencing, analog ADC or thermal model.',
       'Transmission lines represent odd-mode equivalents; no extracted coupling, discontinuities or connector S-parameters.',
       'Carrier geometries are from rev1.0 etch report; exact physical carrier revision unconfirmed.',
       'Daughtercard impedance and dielectric assumptions are swept, not field-solved or TDR measured.',
       'RX package1nH is assumed. RX3/5/10pF includes an engineering capacitance sweep.',
       'Finite pattern central-UI metrics are illustrative; not BER testing or actual IDDR timing signoff.',
       'TI SBOC249 IBIS models were examined but NOT directly simulated: characterized50/75/100ohm loads do not validate open-load common-mode behavior.'],cases=records)
    (OUT/'simulation_summary.json').write_text(json.dumps(summary,indent=2))
    plt.rcParams.update({'font.size':10})
    fig,axs=plt.subplots(2,2,figsize=(13,8),constrained_layout=True)
    for ax,topology in zip(axs.flat,TOPOLOGIES):
        d=selected[('OUT5',topology)]; t=(d['t']-START)*1e9
        ax.plot(t,d['diff'],lw=1,label='FPGA P - N')
        ax.axhline(.1,color='#666',ls=':',lw=.8);ax.axhline(-.1,color='#666',ls=':',lw=.8)
        ax.set(xlim=(60,180),ylim=(-1.5,1.5),title=LABELS[topology],xlabel='Time since data start (ns)',ylabel='Differential input (V)')
        ax.grid(alpha=.2)
    fig.suptitle('10 MSPS / 120 Mb/s: actual OUT5 routing, nominal behavioral model\nUnterminated amplitude depends on assumed driver compliance')
    fig.savefig(OUT/'termination_comparison.png',dpi=170);plt.close(fig)
    fig,axs=plt.subplots(2,2,figsize=(13,8),constrained_layout=True)
    for ax,topology in zip(axs.flat,TOPOLOGIES):
        d=selected[('OUT5',topology)];p=NOMINAL
        delay=np.mean(ROUTES['OUT5'][:2])*p['psmm_d']*1e-12+np.mean(ROUTES['OUT5'][2:])*p['psmm_c']*1e-12+p['extra']
        for i in range(8,NBITS-3):
            x=np.linspace(-.5,1.5,301); tt=START+(i+x)*UI+delay
            ax.plot(x*UI*1e9,np.interp(tt,d['t'],d['diff']),color='#186b99',lw=.5,alpha=.23)
        ax.axhline(.1,color='#d64933',ls=':');ax.axhline(-.1,color='#d64933',ls=':')
        ax.set(title=LABELS[topology],xlabel='Time within symbol (ns)',ylabel='Differential input (V)',ylim=(-1.5,1.5))
        ax.grid(alpha=.15)
    fig.suptitle('Illustrative OUT5 eye overlay: 63-bit pattern, not a measured eye or BER test')
    fig.savefig(OUT/'eye_comparison.png',dpi=170);plt.close(fig)
    print('All simulations finished:',len(records),flush=True)
    for r in records:
        if r['pair']=='OUT5' and r['corner']=='nominal':
            print(json.dumps({k:r[k] for k in ['topology','pin_min_V','pin_max_V','diff_abs_peak_V','center_min_signed_V','center_wrong_bits','estimated_valid_window_ns']}))

if __name__=='__main__':main()
