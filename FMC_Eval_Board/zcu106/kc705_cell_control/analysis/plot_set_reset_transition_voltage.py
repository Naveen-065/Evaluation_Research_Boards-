"""Plot 1Kbit SET transition and RESET response-saturation voltages.

SET transition is the programmed rail pair whose ten confirmation reads first
passed the >=35 uA nominal target.  Cells already above target before a pulse
are counted but omitted from the transition-voltage distribution.

RESET never passed its <=5 uA target in this experiment.  Its plotted voltage
is therefore a descriptive saturation proxy: the earliest ramp point reaching
90% of that cell's total observed current reduction.  It is not called a
transition voltage and must not be used as proof that a single pulse is safe.
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
OUT = ROOT / "output" / "plots"
CELL_CSV = OUT / "set_reset_transition_saturation_voltage_cells.csv"
LRS_JOB = "d42d176742d74a90bd4fef034aec5178"
HRS_JOBS = [
    "b90c22792b4742f596061e41f026654e",
    "b28de2a6b5e0454d8579c8fd6749383b",
    "cc9d179a310242f7bd5ae3da818803f6",
    "f55a38746080490595739b026b4e1a83",
    "30ab5bc5867444e39657ef724e0e33de",
]
RAIL_RE = re.compile(r"__s(\d+)_v(\d+)_wl(\d+)$")
POINT_RE = re.compile(
    r"^RAMP_POINT (\d+) (\d+) reset (\d+) (\d+) (\d+) ([-+.\deE]+)$"
)


def records(job_id: str):
    with (RUNS / f"{job_id}.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def current_ua(record: dict) -> float:
    return float(record["channels"][2]["delta_current_ua"])


def parse_rail(operation: str):
    match = RAIL_RE.search(operation)
    if not match:
        return None
    step, vcc, wl = map(int, match.groups())
    return step, vcc / 1000.0, wl / 1000.0


def load_set():
    if not (RUNS / f"{LRS_JOB}.jsonl").exists() and CELL_CSV.exists():
        with CELL_CSV.open(newline="", encoding="utf-8") as handle:
            return [dict(row=int(row["row"]), col=int(row["col"]),
                         status=row["classification"], step=int(row["step"]),
                         vcc_v=float(row["vcc_v"]), wl_v=float(row["wl_v"]))
                    for row in csv.DictReader(handle) if row["operation"] == "SET"]
    cells = defaultdict(lambda: {"after": [], "success": None, "limit": None})
    for record in records(LRS_JOB):
        if record.get("kind") != "scan":
            continue
        op = record.get("operation", "")
        if "set" not in op:
            continue
        cell = cells[(int(record["row"]), int(record["col"]))]
        rail = parse_rail(op)
        if op.startswith("after_set") and rail:
            cell["after"].append((*rail, current_ua(record)))
            if "_limit__" in op:
                cell["limit"] = rail
        elif op.startswith("confirm_set_10_met") and rail:
            cell["success"] = rail

    rows = []
    for (row, col), cell in sorted(cells.items()):
        if cell["success"] is not None:
            step, vcc, wl = cell["success"]
            pulsed = bool(cell["after"])
            status = "transition" if pulsed else "already_lrs"
        elif cell["limit"] is not None:
            step, vcc, wl = cell["limit"]
            status = "censored_limit"
        else:
            continue
        rows.append(dict(row=row, col=col, status=status, step=step, vcc_v=vcc, wl_v=wl))
    return rows


def reset_grid():
    vs = (2300, 2700, 3000)
    ws = (940, 1010, 1070, 1130, 1190, 1260, 1320, 1380, 1440, 1510,
          1570, 1630, 1690, 1760, 1820, 1880, 1940, 2010, 2070, 2130,
          2190, 2260, 2320, 2380, 2440, 2500, 2570, 2630, 2690, 2750,
          2820, 2880)
    return [(v / 1000.0, w / 1000.0) for v in vs for w in ws]


def load_reset():
    if (not all((RUNS / f"{job_id}.jsonl").exists() for job_id in HRS_JOBS)
            and CELL_CSV.exists()):
        with CELL_CSV.open(newline="", encoding="utf-8") as handle:
            output = []
            for row in csv.DictReader(handle):
                if row["operation"] != "RESET":
                    continue
                output.append(dict(
                    row=int(row["row"]), col=int(row["col"]), target_met=False,
                    detectable_response=row["classification"] == "90pct_response",
                    saturation_step=int(row["step"]), vcc_v=float(row["vcc_v"]),
                    wl_v=float(row["wl_v"]), initial_uA=float(row["initial_uA"]),
                    minimum_uA=float(row["minimum_uA"]),
                    observed_reduction_uA=float(row["observed_reduction_uA"]),
                ))
            return output
    cells = defaultdict(lambda: {"before": None, "points": {}, "target": False})
    for job_id in HRS_JOBS:
        for record in records(job_id):
            if record.get("kind") != "scan":
                continue
            op = record.get("operation", "")
            if "reset" not in op:
                continue
            key = (int(record["row"]), int(record["col"]))
            rail = parse_rail(op)
            if op.startswith("before_reset"):
                cells[key]["before"] = current_ua(record)
            elif op.startswith("after_reset") and rail:
                step, vcc, wl = rail
                cells[key]["points"][step] = (vcc, wl, current_ua(record))
                cells[key]["target"] |= "_met__" in op

        # Compound FPGA ramps preserve all intermediate read currents in log.
        log_path = RUNS / f"{job_id}.log"
        if log_path.exists():
            with log_path.open(encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    match = POINT_RE.match(line.strip())
                    if match:
                        row, col, step, vcc, wl = map(int, match.groups()[:5])
                        cells[(row, col)]["points"][step] = (
                            vcc / 1000.0, wl / 1000.0, float(match.group(6))
                        )

    grid = reset_grid()
    output = []
    for (row, col), cell in sorted(cells.items()):
        points = [cell["points"].get(i) for i in range(1, 97)]
        if cell["before"] is None or any(point is None for point in points):
            continue
        raw = np.asarray([point[2] for point in points], dtype=float)
        # A 3-point median rejects isolated ADC spikes without moving a broad knee.
        smooth = np.asarray([
            np.median(raw[max(0, i - 1):min(len(raw), i + 2)])
            for i in range(len(raw))
        ])
        initial = float(cell["before"])
        minimum = float(np.min(smooth))
        reduction = initial - minimum
        detectable = reduction >= 2.0
        if detectable:
            threshold = initial - 0.90 * reduction
            index = int(np.flatnonzero(smooth <= threshold)[0])
            vcc, wl = grid[index]
            step = index + 1
        else:
            vcc = wl = math.nan
            step = 0
        output.append(dict(
            row=row, col=col, target_met=bool(cell["target"]),
            detectable_response=detectable, saturation_step=step,
            vcc_v=vcc, wl_v=wl, initial_uA=initial, minimum_uA=minimum,
            observed_reduction_uA=reduction,
        ))
    return output


def percentile(values, q):
    return float(np.percentile(np.asarray(values, dtype=float), q))


def stats(values):
    return {
        "n": len(values), "min": min(values), "q1": percentile(values, 25),
        "median": percentile(values, 50), "q3": percentile(values, 75),
        "max": max(values), "p90": percentile(values, 90),
        "p95": percentile(values, 95),
    }


def font(size, bold=False):
    name = "seguisb.ttf" if bold else "segoeui.ttf"
    return ImageFont.truetype(str(Path("C:/Windows/Fonts") / name), size)


def draw_box(draw, overlay, bounds, values, color, y_min, y_max, seed=0):
    left, top, right, bottom = bounds
    cx = (left + right) / 2
    scale = lambda value: bottom - (value - y_min) / (y_max - y_min) * (bottom - top)
    q1, med, q3 = np.percentile(values, [25, 50, 75])
    low, high = min(values), max(values)
    box_w = 128
    draw.line((cx, scale(low), cx, scale(high)), fill=color, width=4)
    draw.line((cx - 38, scale(low), cx + 38, scale(low)), fill=color, width=4)
    draw.line((cx - 38, scale(high), cx + 38, scale(high)), fill=color, width=4)
    draw.rectangle((cx - box_w / 2, scale(q3), cx + box_w / 2, scale(q1)),
                   outline=color, width=5)
    draw.line((cx - box_w / 2, scale(med), cx + box_w / 2, scale(med)),
              fill=color, width=6)
    rng = np.random.default_rng(seed)
    od = ImageDraw.Draw(overlay)
    for value, jitter in zip(values, rng.uniform(-100, 100, len(values))):
        x, y = cx + jitter, scale(value)
        od.ellipse((x - 5, y - 5, x + 5, y + 5), outline=(*color, 115), width=2)


def panel(image, bounds, title, groups, y_min, y_max, y_label):
    draw = ImageDraw.Draw(image)
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    left, top, right, bottom = bounds
    plot = (left + 105, top + 80, right - 25, bottom - 115)
    pl, pt, pr, pb = plot
    for tick in np.linspace(y_min, y_max, 6):
        y = pb - (tick - y_min) / (y_max - y_min) * (pb - pt)
        draw.line((pl, y, pr, y), fill=(225, 229, 235), width=2)
        label = f"{tick:.1f}"
        draw.text((pl - 18, y), label, font=font(27), fill=(65, 72, 84), anchor="rm")
    draw.line((pl, pt, pl, pb), fill=(45, 51, 61), width=3)
    draw.line((pl, pb, pr, pb), fill=(45, 51, 61), width=3)
    draw.text(((left + right) / 2, top + 25), title, font=font(35, True),
              fill=(30, 35, 43), anchor="mm")
    draw.text((left + 24, (pt + pb) / 2), y_label, font=font(28),
              fill=(45, 51, 61), anchor="mm")
    centers = np.linspace(pl + 150, pr - 150, len(groups))
    for idx, ((name, values, color), cx) in enumerate(zip(groups, centers)):
        width = (pr - pl) / len(groups)
        box_bounds = (cx - width / 2, pt, cx + width / 2, pb)
        draw_box(draw, overlay, box_bounds, values, color, y_min, y_max, seed=73 + idx)
        med = np.median(values)
        draw.text((cx, pb + 35), name, font=font(28, True), fill=color, anchor="mm")
        draw.text((cx, pb + 73), f"n={len(values)}  median={med:.2f}",
                  font=font(23), fill=(65, 72, 84), anchor="mm")
    image.alpha_composite(overlay)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    set_rows = load_set()
    reset_rows = load_reset()
    set_transition = [row for row in set_rows if row["status"] == "transition"]
    set_already = [row for row in set_rows if row["status"] == "already_lrs"]
    set_failed = [row for row in set_rows if row["status"] == "censored_limit"]
    reset_response = [row for row in reset_rows if row["detectable_response"]]

    if len(set_rows) != 1024 or len(reset_rows) != 1024:
        raise RuntimeError(f"Expected 1024 SET and RESET cells; got {len(set_rows)}, {len(reset_rows)}")
    if any(row["target_met"] for row in reset_rows):
        raise RuntimeError("RESET target-met data unexpectedly present")

    set_vcc = [row["vcc_v"] for row in set_transition]
    set_wl = [row["wl_v"] for row in set_transition]
    reset_vcc = [row["vcc_v"] for row in reset_response]
    reset_wl = [row["wl_v"] for row in reset_response]

    canvas = Image.new("RGBA", (2400, 1450), (248, 249, 251, 255))
    draw = ImageDraw.Draw(canvas)
    draw.text((1200, 64), "1Kbit programming voltage: transition and saturation proxy",
              font=font(49, True), fill=(24, 29, 38), anchor="mm")
    draw.text((1200, 116), "Hollow circles are individual cells; boxes show quartiles and median",
              font=font(28), fill=(80, 87, 99), anchor="mm")
    orange, blue = (220, 104, 38), (42, 112, 185)
    panel(canvas, (40, 155, 1180, 1045), "VCC at event",
          [("SET target crossing", set_vcc, orange), ("RESET 90% response", reset_vcc, blue)],
          2.15, 3.05, "VCC (V)")
    panel(canvas, (1220, 155, 2360, 1045), "Word-line voltage at event",
          [("SET target crossing", set_wl, orange), ("RESET 90% response", reset_wl, blue)],
          0.30, 3.00, "WL (V)")

    note_y = 1080
    draw.rounded_rectangle((75, note_y, 2325, 1385), radius=28,
                           fill=(255, 255, 255), outline=(210, 216, 225), width=3)
    set_total_attempted = len(set_transition) + len(set_failed)
    line1 = (f"SET: {len(set_already)}/1024 cells were already >=35 µA before any pulse. "
             f"Of {set_total_attempted} cells requiring programming, {len(set_transition)} crossed target "
             f"and {len(set_failed)} reached the configured limit without confirmation.")
    line2 = (f"RESET: 0/1024 cells crossed the <=5 µA target. Blue points are only the earliest rail "
             f"reaching 90% of each cell's observed reduction ({len(reset_response)} cells with >=2 µA response).")
    line3 = ("All RESET attempts continued to 3.00 V VCC / 2.88 V WL and still failed target. "
             "Therefore this run does not validate replacing the ramp with one maximum-voltage pulse.")
    draw.text((115, note_y + 46), line1, font=font(26), fill=(55, 61, 72))
    draw.text((115, note_y + 112), line2, font=font(26), fill=(55, 61, 72))
    draw.text((115, note_y + 178), line3, font=font(27, True), fill=(152, 42, 42))
    draw.text((115, note_y + 246),
              "Voltages are commanded DAC values; actual rail voltages were not independently probed during this run.",
              font=font(23), fill=(90, 96, 108))

    png = OUT / "set_reset_transition_saturation_voltage_boxplots.png"
    canvas.convert("RGB").save(png, quality=95)

    csv_path = CELL_CSV
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        fields = ["operation", "row", "col", "classification", "step", "vcc_v", "wl_v",
                  "initial_uA", "minimum_uA", "observed_reduction_uA"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in set_rows:
            writer.writerow(dict(operation="SET", row=row["row"], col=row["col"],
                                 classification=row["status"], step=row["step"],
                                 vcc_v=row["vcc_v"], wl_v=row["wl_v"], initial_uA="",
                                 minimum_uA="", observed_reduction_uA=""))
        for row in reset_rows:
            writer.writerow(dict(operation="RESET", row=row["row"], col=row["col"],
                                 classification=("90pct_response" if row["detectable_response"] else "no_detectable_response"),
                                 step=row["saturation_step"], vcc_v=row["vcc_v"], wl_v=row["wl_v"],
                                 initial_uA=row["initial_uA"], minimum_uA=row["minimum_uA"],
                                 observed_reduction_uA=row["observed_reduction_uA"]))

    summary = {
        "method": {
            "set": "First rail followed by ten reads >=35 uA; pre-existing LRS cells excluded.",
            "reset": "Earliest 3-point-median ramp sample reaching 90% of the total observed current reduction; only reductions >=2 uA included.",
            "warning": "RESET target <=5 uA was never met; RESET values are a response-saturation proxy, not transition voltages.",
            "voltage_basis": "Commanded DAC values, not independently probed analog rails.",
        },
        "set": {
            "cells": len(set_rows), "already_lrs_before_pulse": len(set_already),
            "transitioned_after_pulse": len(set_transition), "failed_at_limit": len(set_failed),
            "transition_success_rate_among_attempted_pct": 100 * len(set_transition) / set_total_attempted,
            "transition_vcc_v": stats(set_vcc), "transition_wl_v": stats(set_wl),
        },
        "reset": {
            "cells": len(reset_rows), "target_met": 0,
            "detectable_response_cells": len(reset_response),
            "no_detectable_response_cells": len(reset_rows) - len(reset_response),
            "response90_vcc_v": stats(reset_vcc), "response90_wl_v": stats(reset_wl),
            "failed_limit_vcc_v": 3.0, "failed_limit_wl_v": 2.88,
        },
        "source_jobs": {"set_lrs": LRS_JOB, "reset_hrs": HRS_JOBS},
    }
    summary_path = OUT / "set_reset_transition_saturation_voltage_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"png": str(png), "csv": str(csv_path), "summary": summary}, indent=2))


if __name__ == "__main__":
    main()
