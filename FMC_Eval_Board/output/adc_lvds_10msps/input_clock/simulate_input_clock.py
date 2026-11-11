"""Focused 10 MHz input-clock topology sensitivity, not hardware sign-off.

This standalone ngspice experiment writes only beside itself. It does not load
Vivado or change any HDL, XDC, hardware configuration, or schematic.
"""
from pathlib import Path
import ctypes as ct
import csv
import json
import os
from datetime import datetime, timezone
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parent
DLL_DIR = Path('C:/Program Files/KiCad/10.0/bin')

class VecInfo(ct.Structure):
    _fields_ = [('name', ct.c_char_p), ('type', ct.c_int), ('flags', ct.c_short),
                ('real', ct.POINTER(ct.c_double)), ('complex', ct.c_void_p),
                ('length', ct.c_int)]

class Spice:
    def __init__(self):
        self.dll_path = os.add_dll_directory(str(DLL_DIR))
        self.lib = ct.CDLL(str(DLL_DIR / 'ngspice.dll'))
        self.logs = []
        CB = ct.CFUNCTYPE(ct.c_int, ct.c_char_p, ct.c_int, ct.c_void_p)
        EX = ct.CFUNCTYPE(ct.c_int, ct.c_int, ct.c_bool, ct.c_bool, ct.c_int, ct.c_void_p)
        self.log_cb = CB(lambda s, i, u: self.log(s))
        self.status_cb = CB(lambda s, i, u: 0)
        self.exit_cb = EX(lambda a, b, c, d, e: 0)
        self.lib.ngSpice_Init.argtypes = [ct.c_void_p] * 7
        self.lib.ngSpice_Init(self.log_cb, self.status_cb, self.exit_cb, None, None, None, None)
        self.lib.ngSpice_Command.argtypes = [ct.c_char_p]
        self.lib.ngSpice_Circ.argtypes = [ct.POINTER(ct.c_char_p)]
        self.lib.ngGet_Vec_Info.argtypes = [ct.c_char_p]
        self.lib.ngGet_Vec_Info.restype = ct.POINTER(VecInfo)
        self.cmd('version')

    def log(self, msg):
        self.logs.append(msg.decode(errors='replace'))
        return 0

    def cmd(self, command):
        if self.lib.ngSpice_Command(command.encode()):
            raise RuntimeError(command)

    def run(self, name, netlist):
        self.cmd('destroy all')
        offset = len(self.logs)
        (OUT / 'netlists' / (name + '.cir')).write_text(netlist, encoding='ascii')
        lines = netlist.strip().splitlines()
        arr = (ct.c_char_p * (len(lines) + 1))(*[s.encode() for s in lines], None)
        if self.lib.ngSpice_Circ(arr):
            raise RuntimeError('Cannot parse ' + name)
        self.cmd('run')
        result = {}
        for key, vec in {'time': 'time', 'connector_p': 'v(jp)', 'connector_n': 'v(jn)',
                         'clk_p': 'v(ap)', 'clk_n': 'v(an)', 'source_p_current': 'vp#branch',
                         'source_n_current': 'vn#branch'}.items():
            ptr = self.lib.ngGet_Vec_Info(vec.encode())
            if not ptr or not ptr.contents.real:
                raise RuntimeError((name, vec))
            result[key] = np.ctypeslib.as_array(ptr.contents.real, (ptr.contents.length,)).copy()
        result['differential'] = result['clk_p'] - result['clk_n']
        result['common_mode'] = (result['clk_p'] + result['clk_n']) / 2
        logs = self.logs[offset:]
        (OUT / 'logs' / (name + '.log')).write_text('\n'.join(logs))
        if any('error:' in s.lower() or 'timestep too small' in s.lower() for s in logs):
            raise RuntimeError((name, logs))
        if not all(np.isfinite(a).all() for a in result.values()):
            raise RuntimeError('Non-finite result: ' + name)
        return result

# Actual horizontal etch lengths. Velocity and impedance remain assumptions.
CARRIER_MM = {'p': 124.74815538, 'n': 124.82368228}
CARD_MM = {'p': 76.04033676 + 1.76386708, 'n': 76.13790786 + 1.98404039}
CARRIER_PS_PER_MM = 6.7
CARD_PS_PER_MM = 6.2

def ladder(tag, first, last, delay, resistance, sections=12, z0=50):
    # Uncoupled single-ended pi sections. Differential Z=100 ohm nominal.
    l = z0 * delay / sections
    c = delay / (z0 * sections)
    lines = [f'C{tag}_first {first} 0 {c / 2:.12g}']
    prev = first
    for i in range(sections):
        node = last if i == sections - 1 else f'{tag}_v{i}'
        mid = f'{tag}_r{i}'
        lines += [f'R{tag}_{i} {prev} {mid} {resistance / sections:.12g}',
                  f'L{tag}_{i} {mid} {node} {l:.12g}',
                  f'C{tag}_{i} {node} 0 {c / 2 if i == sections - 1 else c:.12g}']
        prev = node
    return lines

def circuit(resistance, edge_ns, fitted=True):
    # Finite fixed resistance is a sensitivity variable, not DRIVE24 calibration.
    # Initialize coupling caps for a 50%-duty periodic clock, all line nodes low.
    rc = resistance + 1.6
    ph = 1.8 * (100 + rc) / (100 + 2 * rc) if fitted else 1.8
    nh = 1.8 * rc / (100 + 2 * rc) if fitted else 0.0
    lines = [f'ADS5282 sample-clock 10MHz Rdriver={resistance} edge={edge_ns}ns R165={fitted}',
             '* Behavioral sensitivity only; no vendor FPGA IBIS or ADC transistor model.',
             '* FPGA P switches 0..1.8V; FPGA N actively driven low.',
             '* R165 is at the daughtercard connector, before about78mm card routing.',
             '* UIC capacitor precharge represents periodic steady operation, not startup.',
             f'Vp sp 0 PULSE(0 1.8 25n {edge_ns}n {edge_ns}n {50-edge_ns}n 100n)',
             'Vn sn 0 0', f'Rp sp dp {resistance}', f'Rn sn dn {resistance}']
    for leg in 'pn':
        lines += ladder('carrier' + leg, 'd' + leg, 'j' + leg,
                        CARRIER_MM[leg] * CARRIER_PS_PER_MM * 1e-12, 1.6)
        lines += ladder('card' + leg, 'j' + leg, 'c' + leg,
                        CARD_MM[leg] * CARD_PS_PER_MM * 1e-12, 0.2)
    if fitted:
        lines += ['R165 jp jn 100']
    lines += ['C61 cp ap 100n', 'C60 cn an 100n', 'Vbias bias 0 1.5',
              'Rbiasp ap bias 5k', 'Rbiasn an bias 5k', 'Cadcp ap 0 5p', 'Cadcn an 0 5p',
              f'.ic v(ap)={1.5-ph/2:.12g} v(an)={1.5-nh/2:.12g}',
              '.options reltol=1e-5 abstol=1e-12',
              '.tran 0.05n 1200n uic',
              '.save v(jp) v(jn) v(ap) v(an) i(Vp) i(Vn)', '.end']
    return '\n'.join(lines) + '\n'

def metrics(d):
    t = d['time']
    steady = t >= 800e-9
    phase = np.mod(t - 25e-9, 100e-9)
    high = steady & (phase > 25e-9) & (phase < 45e-9)
    low = steady & (phase > 75e-9) & (phase < 95e-9)
    hi = float(np.median(d['differential'][high]))
    lo = float(np.median(d['differential'][low]))
    # Count settled-period zero crossings; verify approximate 10MHz numerically.
    ix = np.flatnonzero((d['differential'][:-1] <= 0) & (d['differential'][1:] > 0)
                       & (t[:-1] > 700e-9))
    crossing = t[ix]
    return {'plateau_high_V': hi, 'plateau_low_V': lo, 'plateau_pp_V': hi-lo,
            'diff_min_V': float(np.min(d['differential'][steady])),
            'diff_max_V': float(np.max(d['differential'][steady])),
            'clk_p_min_V': float(np.min(d['clk_p'][steady])),
            'clk_p_max_V': float(np.max(d['clk_p'][steady])),
            'clk_n_min_V': float(np.min(d['clk_n'][steady])),
            'clk_n_max_V': float(np.max(d['clk_n'][steady])),
            'common_mode_min_V': float(np.min(d['common_mode'][steady])),
            'common_mode_max_V': float(np.max(d['common_mode'][steady])),
            'p_driver_peak_abs_mA': float(np.max(np.abs(d['source_p_current'][steady]))*1e3),
            'n_driver_peak_abs_mA': float(np.max(np.abs(d['source_n_current'][steady]))*1e3),
            'rising_crossing_count_after_700ns': len(crossing),
            'median_rising_period_ns': float(np.median(np.diff(crossing)) * 1e9)}

def main():
    for sub in ['netlists', 'logs']:
        (OUT / sub).mkdir(parents=True, exist_ok=True)
    sp = Spice()
    cases = []
    waves = {}
    conditions = [(r, edge, True) for r in [10,25,60] for edge in [.5,1,2]]
    conditions += [(r,1,False) for r in [10,25,60]]
    for r, edge, fitted in conditions:
        name = f'R{r}_edge{edge:g}ns_R165_{"100ohm" if fitted else "removed"}'.replace('.', 'p')
        wave = sp.run(name, circuit(r, edge, fitted))
        row = {'case':name, 'driver_R_ohm':r, 'edge_ns':edge, 'R165_fitted':fitted, **metrics(wave)}
        cases.append(row)
        if (r == 25 and edge == 1) or (r == 10 and edge == .5):
            waves[name] = wave
            with (OUT / (name + '_waveform.csv')).open('w', newline='') as f:
                w = csv.writer(f); w.writerow(wave); w.writerows(zip(*wave.values()))
    checks = []
    for row in cases:
        r = row['driver_R_ohm']
        rload = 100 * 10000.4 / 10100.4 if row['R165_fitted'] else 10000.4
        expected = 1.8 * rload / (2 * (r + 1.6) + rload) * (10000 / 10000.4)
        error = abs(row['plateau_pp_V'] / expected - 1)
        checks.append({'case': row['case'], 'analytic_plateau_pp_V': expected,
                       'relative_error': error, 'within_1_percent': bool(error < .01),
                       'period_within_0p1percent': bool(abs(row['median_rising_period_ns']-100) < .1)})
    assert all(c['within_1_percent'] and c['period_within_0p1percent'] for c in checks)
    summary = {'run_utc':datetime.now(timezone.utc).isoformat(),
               'engine':'KiCad ngspice.dll; version in logs/version.log',
               'case_count':len(cases), 'sample_clock_MHz':10,
               'real_board_waveform_verified':False,
               'carrier_horizontal_length_mm':CARRIER_MM, 'card_horizontal_length_mm':CARD_MM,
               'carrier_delay_ps_per_mm_assumed':CARRIER_PS_PER_MM,
               'card_delay_ps_per_mm_assumed':CARD_PS_PER_MM,
               'limitations':[
                   'Fixed 10/25/60 ohm driver resistances are sensitivity assumptions, not known DRIVE24 impedances.',
                   '0.5/1/2 ns edge times are assumed. No vendor FPGA IBIS or ADC transistor model.',
                   'Uncoupled 50 ohm per-leg line model, 1.6 ohm carrier and0.2 ohm card conductor loss assumed.',
                   'Actual geometry lengths used; propagation, impedance and parasitics not field-solved.',
                   'No connector/package discontinuities, input clamps, jitter or noise model.',
                   'ADC DIFF_CLK=1 equivalent uses documented5kohm bias to1.5V;5pF input capacitance assumed.',
                   'Periodic capacitor initial charge avoids0.5ms settling; this does not model startup.',
                   'R165=100ohm,C60/C61=100nF are intended schematic values; fitted values unverified.',
                   'The final~2mm after coupling capacitor is lumped into the card line before it.',
                   'This source-clock study is independent of ADC-return LVDS termination.',
                   'No conclusion certifies conversion accuracy, FPGA capture, or fabricated-board safety.'
               ], 'cases':cases, 'analytical_checks': checks}
    (OUT / 'results.json').write_text(json.dumps(summary, indent=2))
    (OUT / 'logs/version.log').write_text('\n'.join(sp.logs[:12]))
    with (OUT / 'results.csv').open('w', newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(cases[0]));w.writeheader();w.writerows(cases)
    fig, axes = plt.subplots(2,2,figsize=(12,7))
    for fitted, col in [(True,0),(False,1)]:
        name=f'R25_edge1ns_R165_{"100ohm" if fitted else "removed"}'
        d=waves[name]; mask=(d['time']>=825e-9)&(d['time']<=1025e-9)
        x=(d['time'][mask]-825e-9)*1e9
        axes[0,col].plot(x,d['clk_p'][mask],label='U14 CLKP')
        axes[0,col].plot(x,d['clk_n'][mask],label='U14 CLKN')
        axes[1,col].plot(x,d['differential'][mask],label='CLKP minus CLKN',color='#7047a6')
        axes[0,col].set_title('R165=100 ohm at connector' if fitted else 'R165 removed: comparison only')
        for ax in axes[:,col]:
            ax.grid(alpha=.25);ax.legend();ax.set_ylabel('Voltage(V)')
        axes[1,col].set_xlabel('Time(ns);10MHz period=100ns')
    fig.suptitle('FPGA to ADS5282 sampling clock:10MHz,1.8V P source,N actively low\n25ohm illustrative drivers,1ns edges;behavioral simulation,not measured waveforms')
    fig.tight_layout(rect=[0,0,1,.93]);fig.savefig(OUT/'input_clock_comparison.png',dpi=160);plt.close(fig)
    fitted=[r for r in cases if r['R165_fitted']]
    text = f'''10 MHz FPGA-to-ADC input-clock simulation

Run {summary['run_utc']}; {len(cases)} ngspice cases.
All cases retain P driven0..1.8V and N actively drivenlow; no FPGA settings changed.
R165 fitted cases: differential plateau peak-to-peak spans {min(r['plateau_pp_V'] for r in fitted):.3f} to {max(r['plateau_pp_V'] for r in fitted):.3f}V.
Nominal25ohm/1ns case and removed-R165 comparison are plotted in input_clock_comparison.png.
Driver resistance and slew are sensitivity assumptions, not calibrated DRIVE24 behavior.
The ADC sample-clock arrives through D8/D9,C61/C60,U14pins58/59.
R165 only loads this incoming clock; it does not terminate returned LCLK,ADCLK or OUT1..5.
This model cannot establish the measured waveform, converter operation, data capture, or hardware safety.
See results.json for all assumptions and limitations and results.csv for metrics.
'''
    (OUT/'report.txt').write_text(text)
    print(json.dumps({'cases':len(cases),'results':cases},indent=2))

if __name__ == '__main__':
    main()
