"""Reproduce limited FMC interface fault scenarios with the KiCad ngspice DLL.

Most are electrical equivalent circuits, NOT vendor transistor models.
The powered DAC cases explicitly marked TI IBIS use vendor input clamp tables.
They do not certify the fabricated PCB or predict precise fault current.
Run with Python, NumPy and matplotlib. No board/project files are modified.
"""
from pathlib import Path
import ctypes as ct
import csv
import hashlib
import json
import os
import platform
import re
import zipfile
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
DLL_DIR = Path(os.environ.get('NGSPICE_DLL_DIR', 'C:/Program Files/KiCad/10.0/bin'))
os.chdir(OUT)

class VecInfo(ct.Structure):
    _fields_ = [('name', ct.c_char_p), ('type', ct.c_int), ('flags', ct.c_short),
                ('real', ct.POINTER(ct.c_double)), ('complex', ct.c_void_p), ('length', ct.c_int)]

class Spice:
    def __init__(self):
        self.dll_path = os.add_dll_directory(str(DLL_DIR))
        self.lib = ct.CDLL(str(DLL_DIR / 'ngspice.dll'))
        self.logs = []
        char_cb = ct.CFUNCTYPE(ct.c_int, ct.c_char_p, ct.c_int, ct.c_void_p)
        exit_cb = ct.CFUNCTYPE(ct.c_int, ct.c_int, ct.c_bool, ct.c_bool, ct.c_int, ct.c_void_p)
        self.cb = char_cb(lambda s, i, u: self.message(s))
        self.status_cb = char_cb(lambda s, i, u: 0)
        self.exit_cb = exit_cb(lambda a, b, c, d, e: 0)
        self.lib.ngSpice_Init.argtypes = [ct.c_void_p] * 7
        self.lib.ngSpice_Init(self.cb, self.status_cb, self.exit_cb, None, None, None, None)
        self.lib.ngSpice_Command.argtypes = [ct.c_char_p]
        self.lib.ngSpice_Circ.argtypes = [ct.POINTER(ct.c_char_p)]
        self.lib.ngGet_Vec_Info.argtypes = [ct.c_char_p]
        self.lib.ngGet_Vec_Info.restype = ct.POINTER(VecInfo)
        self.command('version')

    def message(self, s):
        self.logs.append(s.decode(errors='replace'))
        return 0

    def command(self, s):
        result = self.lib.ngSpice_Command(s.encode())
        if result:
            raise RuntimeError(f'ngspice command failed ({result}): {s}')

    def run(self, name, text, vectors):
        self.command('destroy all')
        start = len(self.logs)
        (OUT / (name + '.cir')).write_text(text, encoding='ascii')
        lines = text.strip().splitlines()
        arr = (ct.c_char_p * (len(lines) + 1))(*[s.encode() for s in lines], None)
        if self.lib.ngSpice_Circ(arr):
            raise RuntimeError('Cannot load ' + name)
        self.command('run')
        result = {}
        for label, vector in vectors.items():
            p = self.lib.ngGet_Vec_Info(vector.encode())
            if not p or not p.contents.real or p.contents.length < 1:
                raise RuntimeError(f'Missing {vector} in {name}: {self.logs[start:]}')
            result[label] = np.ctypeslib.as_array(p.contents.real, (p.contents.length,)).copy()
        logs = self.logs[start:]
        (OUT / (name + '.log')).write_text('\n'.join(logs), encoding='utf-8')
        if any('error:' in s.lower() or 'timestep too small' in s.lower() for s in logs):
            raise RuntimeError('Simulation error: ' + name)
        with (OUT / (name + '.csv')).open('w', newline='') as f:
            w = csv.writer(f); w.writerow(result); w.writerows(zip(*result.values()))
        return result

def interp(d, key, x, axis='drive_V'):
    return float(np.interp(x, d[axis], d[key]))

spice = Spice()
results = {}
summary = {'engine': 'ngspice-46 shared library bundled with KiCad 10.0',
           'python': platform.python_version(),
           'scope': 'Equivalent-circuit DC/transient fault scenarios, not board sign-off',
           'limits_source': {'DAC81416': 'https://www.ti.com/lit/ds/symlink/dac81416.pdf',
                             'Kintex7': 'https://docs.amd.com/v/u/en-US/ds182_Kintex_7_Data_Sheet'},
           'assumptions': [
               'Generic diode: IS=1e-12 A, N=1, RS=5 ohm; NOT a vendor input clamp model.',
               'FPGA source resistance 25 ohm; actual pin resistance and current limits unknown.',
               'Regulator conflict uses ideal sources and assumed series resistance; real regulator reverse behavior is not represented.',
               'LVDS simplified 3.5 mA differential source and 1.2 V common mode; no package or extracted PCB transmission-line model.',
               'No solder defects, FPGA configuration, firmware, ESD, thermal model, latchup, or full power-sequencing model.'],
           'cases': {}}

# Extract the actual TI input model I/V tables. Positive current is into the
# component. Power-clamp voltage coordinate is Vref - Vpin (IBIS convention).
ibis_path = OUT / 'models/dac81416.ibs'
ibis = ibis_path.read_text()
model = re.search(r'\[Model\]\s+INPUT1_1p8\s+(.*?)(?=\[Model\])', ibis, re.S).group(1)
def table(section, col):
    body = re.search(r'\[' + re.escape(section) + r'\]\s*(.*?)(?=\[|\Z)', model, re.S | re.I).group(1)
    rows = []
    for line in body.splitlines():
        vals = line.split()
        if len(vals) == 4 and not line.lstrip().startswith('|'):
            try: rows.append((float(vals[0]), float(vals[col])))
            except ValueError: pass
    if not rows: raise ValueError(section)
    return rows

def pwl_source(name, n1, n2, argument, rows):
    # Continuations keep the generated netlist readable and below line limits.
    lines = [f'{name} {n1} {n2} I=pwl({argument},']
    for j in range(0, len(rows), 5):
        pairs = ', '.join(f'{x:.12g}, {y:.12g}' for x,y in rows[j:j+5])
        lines.append('+ ' + pairs + (',' if j+5<len(rows) else ')'))
    return '\n'.join(lines)

for corner, vio, col in [('typ',1.8,1), ('min',1.65,2), ('max',1.95,3)]:
    name = 'dac_ti_ibis_' + corner
    text = f'''DAC81416 INPUT1_1p8 TI IBIS clamp table, {corner} corner
* TI SLAM334 / dac81416.ibs, File Rev 1.0, 2018-08-23.
* Powered DC I/V conversion only, not a full FPGA or complete IBIS transient model.
* Assumed FPGA source resistance 25 ohm. Device voltage limits remain mandatory.
Vdrive source 0 0
Rdriver source package 25
Rpackage package pin 0.05
Vio vio 0 {vio}
Rpull package vio 10k
{pwl_source('Bgnd', 'pin', '0', 'v(pin)', table('GND Clamp',col))}
{pwl_source('Bpwr', 'pin', 'vio', 'v(vio,pin)', table('POWER Clamp',col))}
.dc Vdrive 0 3.3 0.01
.save v(source) v(package) v(pin) i(Vdrive)
.end
'''
    d=spice.run(name,text,{'drive_V':'v(source)','pin_V':'v(package)','die_V':'v(pin)','source_current_A':'vdrive#branch'})
    results[name]=d
    summary['cases'][name] = {str(x): {'pin_V': interp(d, 'pin_V', x),
                                      'source_mA': -1000*interp(d,'source_current_A',x),
                                      'absolute_max_V': vio+.3} for x in [1.8,2.5,3.3]}
summary['vendor_model'] = {'url':'https://www.ti.com/lit/zip/SLAM334',
                          'sha256':hashlib.sha256(ibis_path.read_bytes()).hexdigest(),
                          'model':'INPUT1_1p8; nominal and stated min/max voltage/process/temperature corners',
                          'limitation':'Powered DC clamp conversion only. No extrapolation to VIO=0.'}

name='i2c_opposed_pullups'
d=spice.run(name, '''FMC I2C opposed pullups only
* Actual nominal resistor/rail values. U18 and carrier mux pass gates omitted.
* This calculates the resistor-network consequence, not complete bus operation.
Vcarrier carrier 0 3.3
Vlocal local 0 1.8
Rcarrier carrier bus 4.7k
Rlocal bus local 10k
.op
.save v(bus) i(Vlocal)
.end
''', {'bus_V':'v(bus)','current_into_local_rail_A':'vlocal#branch'})
results[name]=d
summary['cases'][name]={'bus_V':float(d['bus_V'][0]),'into_1V8_uA_per_line':float(d['current_into_local_rail_A'][0]*1e6)}

for vio in [1.8, 0.0]:
    name = 'dac_gpio_vio_' + str(vio).replace('.', '_')
    text = f'''DAC input overvoltage scenario, VIO={vio} V
* Generic diode approximation only. Never interpret clamp action as safe operation.
Vdrive source 0 0
Rdriver source pin 25
Vio vio 0 {vio}
Rpull pin vio 10k
Dupper pin vio Dgeneric
Dlower 0 pin Dgeneric
.model Dgeneric D(IS=1e-12 N=1 RS=5)
.dc Vdrive 0 3.3 0.01
.save v(source) v(pin) i(Vdrive)
.end
'''
    d = spice.run(name, text, {'drive_V': 'v(source)', 'pin_V': 'v(pin)', 'source_current_A': 'vdrive#branch'})
    results[name] = d
    summary['cases'][name] = {str(x): {'pin_V': interp(d, 'pin_V', x),
                                      'source_mA': -1000 * interp(d, 'source_current_A', x),
                                      'absolute_max_V': vio + .3}
                                for x in [1.8, 2.5, 3.3]}

for r in [.05, .25, 1.0]:
    name = 'nt25_sources_R_' + str(r).replace('.', '_')
    d = spice.run(name, f'''NT25 supply conflict sensitivity, assumed total series R={r} ohm
* Ideal regulated sources; this is NOT a reverse-current model of AMS1117.
Vcarrier carrier 0 3.3
Vlocal local 0 3.3
Rpath local carrier {r}
.dc Vlocal 3.2 3.4 0.001
.save v(local) i(Vlocal)
.end
''', {'local_V': 'v(local)', 'local_source_A': 'vlocal#branch'})
    results[name] = d
    summary['cases'][name] = {'current_at_100mV_mismatch_A': float(abs(d['local_source_A'][-1]))}

for rload in [1000, 100000]:
    name = f'unpowered_fpga_pullup_load_{rload}'
    d = spice.run(name, f'''Mezzanine 1.8V pullups into an unpowered FPGA bank
* Eight 4k pullups represented by 500 ohm equivalent. Illustrative load only.
* Generic clamp diode; no powered-off vendor FPGA model.
Vmezz source 0 PWL(0 0 1u 0 2u 1.8 0.5 1.8)
Rpull source pin 500
Dupper pin bank Dgeneric
Cbank bank 0 100u
Rload bank 0 {rload}
.model Dgeneric D(IS=1e-12 N=1 RS=5)
.tran 0.1m 0.5 0 0.1m
.save time v(bank) v(pin) i(Vmezz)
.end
''', {'time_s': 'time', 'bank_V': 'v(bank)', 'pin_V': 'v(pin)', 'source_current_A': 'vmezz#branch'})
    results[name] = d
    summary['cases'][name] = {'bank_V_at_500ms': float(d['bank_V'][-1]),
                              'peak_total_injection_mA': float(-1000 * min(d['source_current_A']))}

for rt in [100, 50, 1000]:
    name = f'lvds_termination_{rt}'
    d = spice.run(name, f'''ADS5282 LVDS simplified differential source, load={rt} ohm
* 1.2V common-mode and 3.5mA differential current from datasheet typical values.
* 1000ohm case only illustrates loss of termination; real output compliance is NOT modeled.
Vcm cm 0 1.2
Iout p n PULSE(-3.5m 3.5m 5n 0.2n 0.2n 5n 10n)
Rterm p n {rt}
Rcmp p cm 1meg
Rcmn n cm 1meg
Cpinp p 0 3p
Cpinn n 0 3p
.tran 0.02n 40n 0 0.02n
.save time v(p) v(n)
.end
''', {'time_s': 'time', 'p_V': 'v(p)', 'n_V': 'v(n)'})
    results[name] = d
    summary['cases'][name] = {'differential_peak_mV': float(1000 * max(abs(d['p_V'] - d['n_V']))),
                              'pin_min_V': float(min(min(d['p_V']), min(d['n_V']))),
                              'pin_max_V': float(max(max(d['p_V']), max(d['n_V'])))}

for series in [0, 33]:
    name = f'gpio_line_series_{series}'
    d = spice.run(name, f'''1.8V GPIO transmission-line sensitivity, added series R={series} ohm
* Assumed 25ohm output, 50ohm line, 1ns flight time, 5pF input. Not extracted PCB.
* No clamp model so overshoot is visible as a stress flag, not a real pin prediction.
Vdrive source 0 PULSE(0 1.8 2n 0.3n 0.3n 10n 20n)
Rdriver source tx {25+series}
Tline tx 0 rx 0 Z0=50 TD=1n
Cinput rx 0 5p
Rleak rx 0 1meg
.tran 0.02n 45n 0 0.02n
.save time v(rx) v(source)
.end
''', {'time_s': 'time', 'rx_V': 'v(rx)', 'drive_V': 'v(source)'})
    results[name] = d
    summary['cases'][name] = {'rx_min_V': float(min(d['rx_V'])), 'rx_max_V': float(max(d['rx_V']))}

zip_path = ROOT / 'CaravelReRAM-SenseEval_v1.2F.zip'
with zipfile.ZipFile(zip_path) as z:
    pcb = z.read('CaravelReRAM-SenseEval.kicad_pcb')
summary['pcb_zip_member_sha256'] = hashlib.sha256(pcb).hexdigest()
local_pcb = ROOT / 'CaravelReRAM-SenseEval_v1.2F/CaravelReRAM-SenseEval.kicad_pcb'
summary['pcb_local_sha256'] = hashlib.sha256(local_pcb.read_bytes()).hexdigest()
summary['pcb_local_matches_archive'] = summary['pcb_local_sha256'] == summary['pcb_zip_member_sha256']
(OUT / 'simulation_summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
(OUT / 'ngspice_engine.log').write_text('\n'.join(spice.logs[:30]), encoding='utf-8')

plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})
fig, ax = plt.subplots(2, 2, figsize=(12, 8.5), layout='constrained')
d = results['dac_ti_ibis_typ']
ax[0, 0].plot(d['drive_V'], d['pin_V'], label='TI IBIS INPUT1_1p8, nominal', color='#147d92')
ax[0, 0].plot([0, 3.3], [0, 3.3], '--', color='gray', label='Unclamped input')
ax[0, 0].axhline(2.1, color='#c43d3d', linestyle=':', label='DAC absolute max at VIO = 1.8 V')
ax[0, 0].set(title='DAC input: 2.5 V drive exceeds its limit', xlabel='FPGA drive (V)', ylabel='DAC pin voltage (V)')
ax[0, 0].legend(fontsize=8)
for r in [.05, .25, 1.0]:
    d = results['nt25_sources_R_' + str(r).replace('.', '_')]
    ax[0, 1].plot((d['local_V']-3.3)*1000, -d['local_source_A'], label=f'Assumed R = {r} ohm')
ax[0, 1].set(title='NT25: supply mismatch drives unwanted current', xlabel='Local minus carrier supply (mV)', ylabel='Current local to carrier (A)')
ax[0, 1].legend(fontsize=8)
for r in [1000, 100000]:
    d = results[f'unpowered_fpga_pullup_load_{r}']
    ax[1, 0].plot(d['time_s']*1000, d['bank_V'], label=f'Assumed rail load {r/1000:g} kohm')
ax[1, 0].set(title='Unpowered bank: pullups can lift its supply', xlabel='Time (ms)', ylabel='Unpowered bank rail (V)')
ax[1, 0].legend(fontsize=8)
for r in [0, 33]:
    d = results[f'gpio_line_series_{r}']
    ax[1, 1].plot(d['time_s']*1e9, d['rx_V'], label=f'Added series R = {r} ohm')
ax[1, 1].axhline(2.1, color='#c43d3d', linestyle=':')
ax[1, 1].set(title='Assumed line: check overshoot with a scope', xlabel='Time (ns)', ylabel='Receiver voltage (V)', xlim=(0, 25))
ax[1, 1].legend(fontsize=8)
for a in ax.flat: a.grid(alpha=.2)
fig.suptitle('FMC interface fault scenarios | ngspice 46\nTI DAC clamp tables + equivalent circuits; not hardware certification', fontsize=14)
fig.savefig(OUT / 'simulation_results.png', dpi=180)
plt.close(fig)
print(json.dumps(summary, indent=2))
