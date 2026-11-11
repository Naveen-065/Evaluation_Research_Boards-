"""Summarize the measured three-point 1Kbit SET/RESET hardware experiment."""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


PROGRAM_RE = re.compile(
    r"MAC_PROGRAM_RESULT (\d+) (\d+) (set|reset) ([01]) ([-+\d.]+)"
)
POINT_RE = re.compile(
    r"RAMP_POINT (\d+) (\d+) (set|reset) (\d+) (\d+) (\d+) ([-+\d.]+)"
)


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def describe(values: list[float]) -> dict[str, float]:
    return {
        "min": min(values),
        "p05": percentile(values, 0.05),
        "median": statistics.median(values),
        "mean": statistics.fmean(values),
        "p95": percentile(values, 0.95),
        "max": max(values),
    }


def portable_path(root: Path) -> Path:
    return root.parent / "results" / "fast3_ramp_1kbit" / "portable_jobs.json"


def load_job(root: Path, ident: str) -> dict:
    source = root / "runs" / f"{ident}.json"
    if source.exists():
        return json.loads(source.read_text(encoding="utf-8"))
    portable = json.loads(portable_path(root).read_text(encoding="utf-8"))
    return portable["jobs"][ident]


def load_run(root: Path, ident: str) -> tuple[dict, dict]:
    job = load_job(root, ident)
    log_path = root / "runs" / f"{ident}.log"
    if not log_path.exists():
        portable = json.loads(portable_path(root).read_text(encoding="utf-8"))
        log_path = portable_path(root).parent / portable["logs"][ident]
    points: dict[tuple[int, int], list[dict]] = defaultdict(list)
    programs: dict[tuple[int, int], dict] = {}
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if match := POINT_RE.fullmatch(line):
            row, col, operation, step, vcc_mv, wl_mv, current = match.groups()
            points[(int(row), int(col))].append(
                {
                    "operation": operation,
                    "step": int(step),
                    "vcc_mv": int(vcc_mv),
                    "wl_mv": int(wl_mv),
                    "current_ua": float(current),
                }
            )
        elif match := PROGRAM_RE.fullmatch(line):
            row, col, operation, met, current = match.groups()
            programs[(int(row), int(col))] = {
                "operation": operation,
                "target_met": bool(int(met)),
                "final_current_ua": float(current),
            }
    if len(programs) != 1024:
        raise RuntimeError(f"{ident}: expected 1024 programming results, found {len(programs)}")
    return job, {"points": points, "programs": programs}


def duration_seconds(job: dict) -> float:
    return (datetime.fromisoformat(job["finished"]) - datetime.fromisoformat(job["started"])).total_seconds()


def mac_outputs(job: dict) -> list[float]:
    return [
        result["nominal_current_dot_ua"]
        for result in job["results"]
        if result.get("kind") == "mac"
    ]


def summarize(job: dict, parsed: dict) -> dict:
    programs = parsed["programs"]
    points = parsed["points"]
    currents = [item["final_current_ua"] for item in programs.values()]
    pulse_counts = Counter(len(points[coord]) for coord in programs)
    voltage_counts = Counter(
        (point["vcc_mv"], point["wl_mv"])
        for cell_points in points.values()
        for point in cell_points
    )
    elapsed = duration_seconds(job)
    return {
        "job_id": job["id"],
        "duration_seconds": elapsed,
        "duration_minutes": elapsed / 60,
        "end_to_end_cells_per_second": 1024 / elapsed,
        "target_successes": sum(item["target_met"] for item in programs.values()),
        "target_failures": sum(not item["target_met"] for item in programs.values()),
        "target_success_percent": 100 * sum(item["target_met"] for item in programs.values()) / 1024,
        "total_pulses": sum(pulse_counts[pulses] * pulses for pulses in pulse_counts),
        "pulse_count_distribution": {str(k): pulse_counts[k] for k in sorted(pulse_counts)},
        "voltage_pair_counts": {
            f"vcc_{vcc_mv}_wl_{wl_mv}_mv": count
            for (vcc_mv, wl_mv), count in sorted(voltage_counts.items())
        },
        "final_current_ua": describe(currents),
        "mac_output_ua_input": describe(mac_outputs(job)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set-job", default="82f9e6aae8bf433695ba00f20ff4f6b7")
    parser.add_argument("--reset-job", default="c4756ed4f9044d8f9f0649b0d206d2cb")
    parser.add_argument("--old-set-job", default="d42d176742d74a90bd4fef034aec5178")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    output = args.output or root / "output" / "data" / "fast3_ramp_1kbit"
    output.mkdir(parents=True, exist_ok=True)
    set_job, set_data = load_run(root, args.set_job)
    reset_job, reset_data = load_run(root, args.reset_job)

    rows = []
    deltas = []
    for row in range(32):
        for col in range(32):
            coordinate = (row, col)
            set_result = set_data["programs"][coordinate]
            reset_result = reset_data["programs"][coordinate]
            delta = reset_result["final_current_ua"] - set_result["final_current_ua"]
            deltas.append(delta)
            rows.append(
                {
                    "row": row,
                    "col": col,
                    "set_target_met": int(set_result["target_met"]),
                    "set_pulses": len(set_data["points"][coordinate]),
                    "set_final_current_ua": set_result["final_current_ua"],
                    "reset_target_met": int(reset_result["target_met"]),
                    "reset_pulses": len(reset_data["points"][coordinate]),
                    "reset_final_current_ua": reset_result["final_current_ua"],
                    "reset_minus_set_current_ua": delta,
                }
            )

    old_set = load_job(root, args.old_set_job)
    summary = {
        "method": {
            "set_points_v": [[2.30, 0.44], [2.30, 1.09], [2.30, 1.75]],
            "reset_points_v": [[2.30, 0.94], [2.80, 1.83], [3.00, 2.88]],
            "set_target": ">=35 uA nominal SET/R10 delta current",
            "reset_target": "<=5 uA nominal SET/R10 delta current",
            "read_bias_v": 0.5,
            "note": "Commanded DAC values; rails were not independently measured during this run.",
        },
        "set": summarize(set_job, set_data),
        "reset": summarize(reset_job, reset_data),
        "reset_effect_relative_to_set": {
            "current_change_ua": describe(deltas),
            "cells_reduced_by_at_least_2ua": sum(delta <= -2 for delta in deltas),
            "cells_increased_by_at_least_2ua": sum(delta >= 2 for delta in deltas),
            "cells_within_2ua": sum(abs(delta) < 2 for delta in deltas),
        },
        "speed_comparison": {
            "old_96_step_set_job": args.old_set_job,
            "old_96_step_set_seconds": duration_seconds(old_set),
            "fast3_set_speedup": duration_seconds(old_set) / duration_seconds(set_job),
            "interpretation": "End-to-end GUI/API job time, including Vivado startup, JTAG/VIO, MAC readback and cleanup.",
        },
        "conclusion": (
            "The three-point FPGA ramp makes full-array programming interactive-minute scale, "
            "but not real-time. SET is effective; RESET is ineffective at the tested capped rail pairs."
        ),
    }

    with (output / "per_cell.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    portable = {
        "format": "SenseEval compact fast3 analysis source",
        "jobs": {
            job["id"]: {
                key: job[key] for key in ("id", "state", "started", "finished", "mac")
            }
            | {"results": [result for result in job["results"] if result.get("kind") == "mac"]}
            for job in (set_job, reset_job)
        }
        | {
            old_set["id"]: {
                key: old_set[key] for key in ("id", "state", "started", "finished")
            }
        },
        "logs": {
            set_job["id"]: f"set_job_{set_job['id']}.txt",
            reset_job["id"]: f"reset_job_{reset_job['id']}.txt",
        },
    }
    (output / "portable_jobs.json").write_text(json.dumps(portable, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
