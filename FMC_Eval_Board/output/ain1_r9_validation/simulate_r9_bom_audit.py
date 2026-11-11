"""Compare the schematic's 470 ohms with BOM C7420029's 0.47 ohms.

The user has confirmed R9 is 0.470 ohms; R10/R11 and fitted R31 remain unconfirmed.
The physical load is user-confirmed as VCC_READ -> 3.3k -> GND, Caravel removed.
"""
from pathlib import Path
import json
import simulate_ain1 as base

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'r9_bom_audit'
OUT.mkdir(exist_ok=True)
base.ROOT = OUT
spice = base.Spice()
results = []
for r9, gains in [(470, [470, 1000, 2000, 6040, 10000, 1e12]),
                  (0.47, [100, 150, 470, 1000, 2000, 6040, 10000, 1e12])]:
    for rg in gains:
        runs = {}
        for state, load in [('unloaded', 1e12), ('loaded_3k3', 3300)]:
            name = f'r9_{r9:g}_rg_{rg:g}_{state}'.replace('.', 'p')
            circuit = base.netlist(rg, analysis='.op',
                                   load=f'RLOAD vcc_read 0 {load}', dac=0.539)
            circuit = circuit.replace('R9 dac0 vcc_read 470\n', f'R9 dac0 vcc_read {r9}\n')
            d = spice.run(name, circuit)
            source, sense = float(d['v(dac0)'][0]), float(d['v(vcc_read)'][0])
            p, n = float(d['v(amp1_p)'][0]), float(d['v(amp1_n)'][0])
            runs[state] = {
                'source_V': source, 'load_V': sense, 'shunt_drop_V': source-sense,
                'resistor_current_A': sense/load, 'AMP1_P_V': p, 'AMP1_N_V': n,
                'ADC_differential_V': p-n, 'model_plus_ideal_ADC_code': 2048+2048*(p-n)
            }
        nominal_gain = 1+6000/rg
        ideal_drop = 0.539*r9/(r9+3300)
        results.append({
            'R9_ohms': r9, 'R31_ohms': None if rg==1e12 else rg,
            'nominal_gain': nominal_gain, 'runs': runs,
            'ideal_load_current_A': 0.539/(r9+3300),
            'ideal_shunt_drop_V': ideal_drop,
            'ideal_ADC_signal_V': nominal_gain*ideal_drop,
            'ideal_ADC_increment_counts': 2048*nominal_gain*ideal_drop,
            'ngspice_ADC_increment_counts': runs['loaded_3k3']['model_plus_ideal_ADC_code']-runs['unloaded']['model_plus_ideal_ADC_code'],
        })

captures = []
for stem, description in [
    ('ads5282_analog_20261019_201747', 'Earlier source-side load arrangement; Caravel installed'),
    ('ads5282_analog_20261019_202241', 'During confirmation of series load connection; Caravel state not yet confirmed'),
    ('ads5282_analog_20261019_202359', 'After user confirmed series connection and Caravel removed'),
]:
    data = json.loads((ROOT/'load_3k3'/f'{stem}.summary.json').read_text())
    captures.append({'file': f'../load_3k3/{stem}.summary.json', 'description': description,
                     'samples': data['coherent_packets'], 'sample_rate_hz': data['mean_packet_rate_hz'],
                     'capture_checks_pass': data['all_capture_checks_pass'],
                     'ch1': data['channels']['1'],
                     'serial_bit_order_independently_validated': data['serial_bit_order_validated_by_known_input_or_test_pattern']})

audit = {
    'user_confirmed_connection': 'AQ1_C00 -> R9 -> VCC_READ -> 3.3 kohm -> GND',
    'caravel_installed': False, 'measured_source_V_prior_to_rewire': 0.539,
    'loaded_source_voltage_remeasurement_pending': True,
    'bom': {
        'path': 'CaravelReRAM-SenseEval_v1.2F/jlcpcb/production_files/BOM-CaravelReRAM-SenseEval.csv',
        'line': 19, 'designators': ['R9','R10','R11'], 'comment': '470R', 'part': 'C7420029',
        'manufacturer_part': 'FOJAN FRM252WJR470TK', 'selected_part_ohms': 0.47,
        'selected_part_tolerance_percent': 5,
        'source': 'https://www.lcsc.com/product-detail/C7420029.html',
        'R9_user_confirmed_ohms': 0.470,
        'R9_confirmation_source': 'User: yes its .470 ohms',
        'R10_R11_fitted_values_confirmed': False,
    },
    'R31': {'design_ohms': 1000, 'part': 'C2907232', 'selected_part_ohms': 1000,
            'source': 'https://jlcpcb.com/partdetail/FOJAN-FRC0805F1001TS/C2907232',
            'actual_fitted_value_confirmed': False},
    'simulations': results, 'captures': captures,
    'interpretation': [
        'The PCB label and selected purchase part differ by a factor of 1000 for R9, R10 and R11.',
        '0.47 ohms with gain 7 produces about one ADC count for this load; near-midscale readings cannot establish a failed signal path or a wrong gain resistor.',
        'User confirmed fitted R9 is 0.470 ohms; the 470 ohm simulations are comparison cases only and do not describe the fitted R9.',
        'This simulation does not independently validate ADC serial word alignment, analogue calibration, or physical solder connectivity.',
        'No hardware output configuration or FPGA bitstream was changed; captures only arm and read the existing ILA.',
    ],
    'model_limits': [
        'TI INA851 preliminary PSpice macro-model executed by ngspice 46 with PSpice compatibility.',
        'An ideal static 12-bit, 2 Vpp ADC transfer is applied to the amplifier output; actual ADC offset and noise are not modeled.',
        'No inference of actual R31 or R9 from the near-zero ADC data is justified.',
    ]
}
(OUT/'audit.json').write_text(json.dumps(audit, indent=2)+'\n')
for row in results:
    print(f"R9={row['R9_ohms']:g} ohm R31={row['R31_ohms']} gain={row['nominal_gain']:.5g} "
          f"drop={row['ideal_shunt_drop_V']*1e3:.8g} mV "
          f"ideal_step={row['ideal_ADC_increment_counts']:.6g} "
          f"ngspice_step={row['ngspice_ADC_increment_counts']:.6g}")

if __name__ == '__main__':
    print('Saved', OUT/'audit.json')
