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


