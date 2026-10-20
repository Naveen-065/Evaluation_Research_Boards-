"""Passive voltage/digital diagnostic of J8 OUT6P/N. Not an ADC word decoder.

Logic Pro 16 inputs are single-ended. The 1.8 V option is a nominal 0.9 V
comparator threshold, below the normal LVDS low level. Analog channels have
insufficient bandwidth to validate 120-Mbit/s waveform integrity.
"""
import argparse
import csv
import json
import statistics
from pathlib import Path
from saleae import automation

parser = argparse.ArgumentParser()
parser.add_argument('--digital-rate', type=int, default=500000000)
parser.add_argument('--analog-rate', type=int, default=3125000)
parser.add_argument('--output', default='saleae_out6')
args = parser.parse_args()
out = Path('/home/ubuntu-24-04/kc705_adc_10m') / args.output
out.mkdir(parents=True, exist_ok=True)
with automation.Manager.connect(port=10430, connect_timeout_seconds=5) as manager:
    devices = manager.get_devices(include_simulation_devices=False)
    selected = [d for d in devices if d.device_id == 'A25E1BAA6577FA4D']
    if len(selected) != 1:
        raise RuntimeError('Expected physical Logic Pro 16 not found')
    config = automation.LogicDeviceConfiguration(
        enabled_analog_channels=[0, 1], enabled_digital_channels=[0, 1],
        analog_sample_rate=args.analog_rate, digital_sample_rate=args.digital_rate,
        digital_threshold_volts=1.8)
    with manager.start_capture(
        device_id=selected[0].device_id, device_configuration=config,
        capture_configuration=automation.CaptureConfiguration(
            capture_mode=automation.TimedCaptureMode(duration_seconds=0.01))) as capture:
        capture.wait()
        capture.save_capture(str(out / 'out6.sal'))
        capture.export_raw_data_csv(directory=str(out), analog_channels=[0,1], digital_channels=[0,1])

with (out/'analog.csv').open() as f:
    analog = list(csv.DictReader(f))
with (out/'digital.csv').open() as f:
    digital = list(csv.DictReader(f))
summary = {'device_id': selected[0].device_id, 'digital_sample_rate': args.digital_rate,
           'analog_sample_rate': args.analog_rate, 'duration_s': .01,
           'threshold_setting_V': 1.8, 'nominal_comparator_threshold_V': .9,
           'adc_word_decoded': False, 'analog': {}, 'digital': {}}
for ch in [0,1]:
    label=f'Channel {ch}'
    values=[float(r[label]) for r in analog]
    summary['analog'][str(ch)]={'mean_V': statistics.fmean(values),
                             'min_V': min(values), 'max_V': max(values),
                             'std_V': statistics.pstdev(values)}
    states=[int(r[label]) for r in digital]
    summary['digital'][str(ch)]={'states': sorted(set(states)),
        'transitions': sum(a != b for a,b in zip(states,states[1:]))}
summary['limitation']='Direct single-ended LVDS observation only; no bit/frame clocks; analog bandwidth cannot validate 120-Mbit/s edges.'
(out/'summary.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2))
