"""Passive clock capture after the user confirms the selected CH0 probe point.

--point fpga: C61 pad 2, 1.8 V CMOS, before the coupling capacitor.
--point adc: C61 pad 1, AC-coupled clock biased around 1.5 V.
The threshold setting changes only the Saleae receiver, never the PCB/FPGA.
This is not suitable for measuring the ADC LVDS return clock directly.
"""
import argparse
import csv
import json
from pathlib import Path
from saleae import automation

parser = argparse.ArgumentParser()
parser.add_argument('--point', choices=['fpga', 'adc'], default='fpga')
args = parser.parse_args()
probe_location = ('C61 pad 2, FPGA_MCLKIN_P, CH0' if args.point == 'fpga'
                  else 'C61 pad 1, FPGA_MCLKIN_C_P, CH0')
threshold_setting = 1.8 if args.point == 'fpga' else 3.3
directory = 'saleae_sample_clock_mixed' if args.point == 'fpga' else 'saleae_adc_side_clock'
out = Path('/home/ubuntu-24-04/kc705_adc_10m') / directory
out.mkdir(parents=True, exist_ok=True)
with automation.Manager.connect(port=10430, connect_timeout_seconds=5) as manager:
    devices = manager.get_devices(include_simulation_devices=False)
    selected = [d for d in devices if d.device_id == 'A25E1BAA6577FA4D']
    if len(selected) != 1:
        raise RuntimeError('Physical Logic Pro 16 not found')
    config = automation.LogicDeviceConfiguration(
        enabled_digital_channels=[0], digital_sample_rate=250000000,
        enabled_analog_channels=[0], analog_sample_rate=31250,
        digital_threshold_volts=threshold_setting)
    with manager.start_capture(
        device_id=selected[0].device_id, device_configuration=config,
        capture_configuration=automation.CaptureConfiguration(
            capture_mode=automation.TimedCaptureMode(duration_seconds=0.01))) as capture:
        capture.wait()
        capture.save_capture(str(out / 'sample_clock.sal'))
        capture.export_raw_data_csv(directory=str(out), digital_channels=[0], analog_channels=[0])

with (out/'digital.csv').open() as f:
    rows = list(csv.DictReader(f))
edges = []
previous = int(rows[0]['Channel 0'])
for row in rows[1:]:
    state = int(row['Channel 0'])
    if state != previous:
        edges.append((float(row['Time [s]']), state))
        previous = state
rising = [t for t, state in edges if state == 1]
periods = [b-a for a, b in zip(rising, rising[1:])]
summary = {
    'probe_location': probe_location,
    'saleae_threshold_setting_V': threshold_setting,
    'digital_sample_rate_hz': 250000000,
    'exported_duration_s': float(rows[-1]['Time [s]'])-float(rows[0]['Time [s]']),
    'transitions': len(edges),
    'rising_edges': len(rising),
    'frequency_hz': (len(rising)-1)/(rising[-1]-rising[0]) if len(rising)>1 else None,
    'period_min_s': min(periods) if periods else None,
    'period_max_s': max(periods) if periods else None,
    'limitation': 'Digital threshold crossing measurement; does not verify analog amplitude or clock waveform quality at the ADC package.'
}
summary['nominal_10mhz_observed'] = bool(summary['frequency_hz'] and abs(summary['frequency_hz']/1e7-1)<.01)
(out/'summary.json').write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))
