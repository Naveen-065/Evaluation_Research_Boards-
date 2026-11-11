"""Run TI INA851 macro-model in ngspice for the PCB R9/U10/ADC1 path.

The ADC is an ideal 12-bit, 2 Vpp differential transfer function, not a
transistor-level ADS5282 model. DAC0 is a stiff DC source at its nominal code.
Board resistor values are design values; fitted values require measurement.
"""
from pathlib import Path
import ctypes as ct
import os, json, csv, hashlib
import numpy as np

ROOT=Path(__file__).resolve().parent
DLLDIR=Path('C:/Program Files/KiCad/10.0/bin')
MODEL=ROOT/'vendor/SBOMC50/INA851.LIB'

class VecInfo(ct.Structure):
    _fields_=[('name',ct.c_char_p),('type',ct.c_int),('flags',ct.c_short),
              ('real',ct.POINTER(ct.c_double)),('complex',ct.c_void_p),('length',ct.c_int)]

class Spice:
    def __init__(self):
        self.dllpath=os.add_dll_directory(str(DLLDIR))
        self.lib=ct.CDLL(str(DLLDIR/'ngspice.dll'))
        self.messages=[]
        cb=ct.CFUNCTYPE(ct.c_int,ct.c_char_p,ct.c_int,ct.c_void_p)
        ex=ct.CFUNCTYPE(ct.c_int,ct.c_int,ct.c_bool,ct.c_bool,ct.c_int,ct.c_void_p)
        self.send=cb(lambda s,i,u:self.messages.append(s.decode(errors='replace')) or 0)
        self.status=cb(lambda s,i,u:0)
        self.exit=ex(lambda a,b,c,d,e:0)
        self.lib.ngSpice_Init.argtypes=[ct.c_void_p]*7
        self.lib.ngSpice_Init(self.send,self.status,self.exit,None,None,None,None)
        self.lib.ngSpice_Command.argtypes=[ct.c_char_p]
        self.lib.ngSpice_Circ.argtypes=[ct.POINTER(ct.c_char_p)]
        self.lib.ngGet_Vec_Info.argtypes=[ct.c_char_p]
        self.lib.ngGet_Vec_Info.restype=ct.POINTER(VecInfo)
        # ngspice's codemodel loader keeps quote characters in its filename.
        # Windows short paths avoid spaces without changing the vendor files.
        for model in sorted((DLLDIR.parent/'lib/ngspice').glob('*.cm')):
            short=ct.create_unicode_buffer(32768)
            if not ct.windll.kernel32.GetShortPathNameW(str(model),short,len(short)):
                raise OSError('No short path for '+str(model))
            self.cmd('codemodel '+short.value.replace('\\','/'))
        self.cmd('set ngbehavior=ps')
        self.cmd('version')
        (ROOT/'ngspice_version.log').write_text('\n'.join(self.messages))
    def cmd(self,s):
        rc=self.lib.ngSpice_Command(s.encode())
        if rc: raise RuntimeError((s,rc,self.messages[-20:]))
    def run(self,name,netlist):
        self.cmd('destroy all')
        (ROOT/f'{name}.cir').write_text(netlist)
        start=len(self.messages)
        lines=netlist.strip().splitlines()
        arr=(ct.c_char_p*(len(lines)+1))(*[s.encode() for s in lines],None)
        rc=self.lib.ngSpice_Circ(arr)
        if rc:
            (ROOT/f'{name}.log').write_text('\n'.join(self.messages[start:]))
            raise RuntimeError(('load',rc,self.messages[start:]))
        self.cmd('run')
        log='\n'.join(self.messages[start:])
        (ROOT/f'{name}.log').write_text(log)
        if 'Error:' in log or 'Timestep too small' in log: raise RuntimeError(log)
        data={}
        for key in ['v(dac0)','v(vcc_read)','v(inp)','v(inn)','v(amp1_p)','v(amp1_n)']:
            p=self.lib.ngGet_Vec_Info(key.encode())
            if not p or p.contents.length<1: raise RuntimeError((key,log))
            data[key]=np.ctypeslib.as_array(p.contents.real,(p.contents.length,)).copy()
        return data

def netlist(rg,analysis='.dc ILOAD 0 1m 1u',load='ILOAD vcc_read 0 DC 0',dac=0.500030517578125):
    return f'''PCB DAC0 -> R9 Kelvin shunt -> U10 INA851 -> ADS5282 channel 1
.include "{MODEL.as_posix()}"
.options reltol=1e-5 abstol=1e-12 vntol=1e-7 rshunt=1e12 itl1=500 itl2=200
VDAC dac0 0 {dac}
R9 dac0 vcc_read 470
{load}
R33 dac0 inp 150
R34 vcc_read inn 150
R31 rgp rgn {rg}
VPLUS vplus 0 12
VMINUS vminus 0 -3
VCLAMP vclamp 0 3.3
VCM vcm 0 1.5
XU10 inp inn rgp rgn vplus vminus outp outn vcm fdap fdan g02p g02n vclamp 0 INA851
R37 outp amp1_p 150
R38 outn amp1_n 150
* DC input leakage and input capacitance placeholders, not an ADC macro-model.
RADC_P amp1_p vcm 1e12
RADC_N amp1_n vcm 1e12
CADC_P amp1_p vcm 5p
CADC_N amp1_n vcm 5p
{analysis}
.end
'''

def main():
    spice=Spice()
    summary=[]
    for rg in [100,150,470,1000,2000,6000,6040,10000,1e12]:
        name='rg_'+('open' if rg==1e12 else str(rg))
        nominal_gain=1+6000/rg
        imax=min(1e-3,1.1/(470*nominal_gain))
        istep=imax/1000
        d=spice.run(name,netlist(rg,analysis=f'.dc ILOAD 0 {imax} {istep}'))
        drop=d['v(dac0)']-d['v(vcc_read)']
        diff=d['v(amp1_p)']-d['v(amp1_n)']
        code=2048+2048*diff
        # Avoid the macro-model's zero-differential internal switch transition
        # when estimating its slope. Fit only the linear 10%-80% portion.
        gain=float(np.polyfit(drop[100:800],diff[100:800],1)[0])
        good=np.flatnonzero((diff>=-1)&(diff<1))
        with (ROOT/f'{name}.csv').open('w',newline='') as f:
            w=csv.writer(f)
            w.writerow(['load_current_A','shunt_drop_V','vcc_read_V','amp1_p_V','amp1_n_V','adc_differential_V','ideal_adc_code_unclipped','ideal_adc_code_clipped'])
            for i in range(len(drop)):
                w.writerow([i*istep,drop[i],d['v(vcc_read)'][i],d['v(amp1_p)'][i],d['v(amp1_n)'][i],diff[i],code[i],min(4095,max(0,round(code[i])))])
        summary.append({'rg_ohms':None if rg==1e12 else rg,'nominal_gain':1+6000/rg,
                        'ngspice_linear_fitted_gain':gain,'zero_load_adc_diff_V':float(diff[0]),
                        'zero_load_ideal_code':float(code[0]),
                        'at_20uA':{'drop_V':float(np.interp(20e-6,np.arange(len(drop))*istep,drop)),
                                    'adc_diff_V':float(np.interp(20e-6,np.arange(len(drop))*istep,diff)),
                                    'ideal_code_unclipped':float(np.interp(20e-6,np.arange(len(drop))*istep,code))},
                        'positive_adc_full_scale_current_uA_ideal':1e6/((1+6000/rg)*470),
                        'last_unclipped_simulated_current_uA':float(good[-1]*istep*1e6) if len(good) else None})
        print(name,'gain',gain,'zero code',float(code[0]),flush=True)
    known_load=[]
    for rg in [100,150,470,1000,2000,6040,10000,1e12]:
        name='load47k_rg_'+('open' if rg==1e12 else str(rg))
        d=spice.run(name,netlist(rg,analysis='.op',load='RLOAD vcc_read 0 47000'))
        drop=float(d['v(dac0)'][0]-d['v(vcc_read)'][0])
        diff=float(d['v(amp1_p)'][0]-d['v(amp1_n)'][0])
        known_load.append({'rg_ohms':None if rg==1e12 else rg,
                           'shunt_drop_V':drop,'load_current_A':drop/470,
                           'vcc_read_V':float(d['v(vcc_read)'][0]),
                           'amp1_p_V':float(d['v(amp1_p)'][0]),
                           'amp1_n_V':float(d['v(amp1_n)'][0]),
                           'adc_differential_V':diff,
                           'ideal_adc_code':2048+2048*diff,
                           'ideal_nominal_increment_from_no_load':2048*(1+6000/rg)*drop})
    result={'model_url':'https://www.ti.com/lit/zip/SBOMC50',
            'model_sha256':hashlib.sha256(MODEL.read_bytes()).hexdigest(),
            'dac0_nominal_V':0.500030517578125,'r9_ohms':470,'rg_sweep':summary,
            '47k_load_simulations_assuming_no_other_load':known_load,
            'ngspice_convergence_options':{'rshunt_ohms':1e12,'reltol':1e-5,'itl1':500,'itl2':200},
            'limitations':['TI preliminary macro-model does not include all gain errors or actual component tolerances.',
                           'Output-clamping behavior is not used to certify safe hardware limits.',
                           'ADC uses ideal static 2 Vpp differential / 12-bit mapping; no ADC offset/noise or sampling kickback model.',
                           'Unknown physical load and fitted R31 cannot be inferred uniquely from a near-zero ADC reading.']}
    (ROOT/'simulation_summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__': main()
