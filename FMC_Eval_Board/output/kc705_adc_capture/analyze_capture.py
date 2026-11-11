"""Check coherent packet cadence in a 200 MHz ILA capture.

Bit-reversed codes are candidates based on the configured LSB-first stream.
They are not calibrated voltages or a substitute for a known-input/pattern test.
"""
import argparse
import csv
import json
import statistics
from collections import Counter
from pathlib import Path


def reverse12(word):
    return int(f"{word:012b}"[::-1], 2)


def analyze(path):
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        radix = next(reader)
        assert radix["snapshot_words[59:0]"] == "HEX"
        rows = list(reader)
    required_high = [
        "run_enable_1", "pll_locked_1", "adc_clock_running_1",
        "adc_reset_n_1", "config_done_1", "dac_enable_1", "dac_ready_1",
        "ret_adclk_seen_1", "ret_lclk_seen_1", "ret_adclk_10m_1",
        "ret_lclk_60m_1", "ret_window_valid_1", "frame_locked_sync[1:1]",
    ]
    high_checks = {key: all(row[key] == "1" for row in rows) for key in required_high}
    packets = [row for row in rows if row["snapshot_valid"] == "1"]
    indices = [int(row["Sample in Buffer"]) for row in packets]
    intervals = [b-a for a, b in zip(indices, indices[1:])]
    assert len(rows) == 4096 and len(packets) > 190
    assert all(high_checks.values()), high_checks
    assert set(intervals).issubset({19, 20, 21}), Counter(intervals)
    changes_without_valid = [
        int(b["Sample in Buffer"])
        for a, b in zip(rows, rows[1:])
        if a["snapshot_words[59:0]"] != b["snapshot_words[59:0]"]
        and b["snapshot_valid"] != "1"
    ]
    assert not changes_without_valid, changes_without_valid
    channel_stats = {}
    decoded_rows = []
    for packet in packets:
        bundle = int(packet["snapshot_words[59:0]"], 16)
        raw = [(bundle >> (12*i)) & 0xfff for i in range(5)]
        decoded_rows.append([int(packet["Sample in Buffer"])] + raw + [reverse12(v) for v in raw])
    for ch in range(1, 6):
        raw = [row[ch] for row in decoded_rows]
        codes = [row[ch+5] for row in decoded_rows]
        channel_stats[str(ch)] = {
            "raw_unique_words": len(set(raw)),
            "candidate_lsb_first_code_min": min(codes),
            "candidate_lsb_first_code_max": max(codes),
            "candidate_lsb_first_code_mean": statistics.mean(codes),
            "candidate_lsb_first_code_stdev": statistics.pstdev(codes),
        }
    packet_csv = path.with_name(path.stem + "_packets.csv")
    with packet_csv.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ila_sample"] + [f"ch{i}_raw" for i in range(1,6)] +
                        [f"ch{i}_candidate_code" for i in range(1,6)])
        writer.writerows(decoded_rows)
    result = {
        "source_csv": path.name,
        "ila_clock_hz": 200000000,
        "ila_samples": len(rows),
        "coherent_packets": len(packets),
        "packet_interval_ila_cycles": dict(Counter(intervals)),
        "mean_packet_rate_hz": 200000000 / statistics.mean(intervals),
        "all_capture_checks_pass": True,
        "status_high_throughout_capture": high_checks,
        "packet_changes_without_valid": len(changes_without_valid),
        "channels": channel_stats,
        "serial_bit_order_validated_by_known_input_or_test_pattern": False,
        "adc_register_readback": False,
        "adc6_captured": False,
        "limitations": [
            "Only ADC outputs 1-5 are connected to FMC; OUT6 is on J8.",
            "Bit-reversed candidate codes need a known input or test-pattern validation.",
            "No voltage or R9/R10/R11 current calibration is claimed.",
            "Clock counters establish activity/rate, not LVDS eye quality.",
        ],
    }
    path.with_suffix(".summary.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("capture", type=Path)
    args = parser.parse_args()
    print(json.dumps(analyze(args.capture), indent=2))
