"""Plot the latest ZCU106 1Kbit LRS/HRS states and programming voltages."""

from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
OUT = ROOT / "output" / "plots"
SET_JOB = "3049643729fb4425a6a6433f69dabacb"
RESET_JOBS = [
    "08cbce7693ea4d17b447c0746e55e802",
    "2a74d697bfe4400a81a6332ef9b54152",
    "80881d174711464388e6fb957ac02bc5",
]
FINAL_RESET_JOB = RESET_JOBS[-1]
READ_VOLTAGE_V = 0.5
BIN_WIDTH_US = 4.0
PULSE_RE = re.compile(r"__p(\d+)$")
SET_GRID = [(2.30, 0.44), (2.30, 1.09), (2.30, 1.75)]
RESET_VCC_MV = (2300, 2700, 3000)
RESET_WL_MV = (
    940, 1010, 1070, 1130, 1190, 1260, 1320, 1380,
    1440, 1510, 1570, 1630, 1690, 1760, 1820, 1880,
    1940, 2010, 2070, 2130, 2190, 2260, 2320, 2380,
    2440, 2500, 2570, 2630, 2690, 2750, 2820, 2880,
)
RESET_GRID = [(v / 1000.0, wl / 1000.0) for v in RESET_VCC_MV for wl in RESET_WL_MV]
RESET_HOLD_MS = (1.2, 2.4, 6.0)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "seguisb.ttf" if bold else "segoeui.ttf"
    return ImageFont.truetype(str(Path("C:/Windows/Fonts") / name), size)


def load_job(job_id: str) -> dict:
    return json.loads((RUNS / f"{job_id}.json").read_text(encoding="utf-8"))


def pulse_count(record: dict) -> int:
    match = PULSE_RE.search(record.get("operation", ""))
    if not match:
        raise RuntimeError(f"Missing pulse count in {record.get('operation')!r}")
    return int(match.group(1))


def current_ua(record: dict) -> float:
    channel = record["channels"][2]
    if record.get("clipped") or channel.get("clipped"):
        raise RuntimeError(f"Clipped result at r{record['row']}/c{record['col']}")
    return float(channel["delta_current_ua"])


def array_records(job: dict) -> dict[tuple[int, int], dict]:
    rows = {
        (int(result["row"]), int(result["col"])): result
        for result in job["results"]
        if result.get("kind") == "scan" and result.get("fpga_array_scheduler")
    }
    if len(rows) != 1024:
        raise RuntimeError(f"{job['id']}: expected 1024 unique FPGA-array results, got {len(rows)}")
    return rows


def smooth_counts(counts: np.ndarray, sigma_bins: float = 1.2) -> np.ndarray:
    radius = int(np.ceil(4 * sigma_bins))
    x = np.arange(-radius, radius + 1, dtype=float)
    kernel = np.exp(-0.5 * (x / sigma_bins) ** 2)
    kernel /= kernel.sum()
    return np.convolve(counts.astype(float), kernel, mode="same")


def best_threshold(hrs: np.ndarray, lrs: np.ndarray) -> tuple[float, int, int]:
    ordered = np.unique(np.concatenate([hrs, lrs]))
    candidates = (ordered[:-1] + ordered[1:]) / 2
    errors = np.asarray([(hrs >= value).sum() + (lrs < value).sum() for value in candidates])
    index = int(np.argmin(errors))
    return float(candidates[index]), int((hrs >= candidates[index]).sum()), int((lrs < candidates[index]).sum())


def nice_ceiling(value: float) -> int:
    magnitude = 10 ** max(0, math.floor(math.log10(value)) - 1)
    return int(math.ceil(value / magnitude) * magnitude)


def stats(values: list[float] | np.ndarray) -> dict:
    data = np.asarray(values, dtype=float)
    return {
        "n": int(data.size), "min": float(data.min()),
        "q1": float(np.percentile(data, 25)), "median": float(np.median(data)),
        "mean": float(data.mean()), "q3": float(np.percentile(data, 75)),
        "max": float(data.max()),
    }


def plot_distribution(lrs: np.ndarray, hrs: np.ndarray) -> tuple[Path, dict]:
    lower = math.floor(min(lrs.min(), hrs.min()) / BIN_WIDTH_US) * BIN_WIDTH_US
    upper = math.ceil(max(lrs.max(), hrs.max()) / BIN_WIDTH_US) * BIN_WIDTH_US
    edges = np.arange(lower, upper + BIN_WIDTH_US, BIN_WIDTH_US)
    centers = (edges[:-1] + edges[1:]) / 2
    hrs_counts, _ = np.histogram(hrs, bins=edges)
    lrs_counts, _ = np.histogram(lrs, bins=edges)
    threshold, hrs_errors, lrs_errors = best_threshold(hrs, lrs)
    accuracy = 1 - (hrs_errors + lrs_errors) / (len(hrs) + len(lrs))

    width, height = 2400, 1400
    pl, pr, pt, pb = 225, width - 90, 185, height - 230
    pw, ph = pr - pl, pb - pt
    y_limit = nice_ceiling(max(hrs_counts.max(), lrs_counts.max()) * 1.22)
    image = Image.new("RGB", (width, height), "#f8fafc")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((55, 55, width - 55, height - 55), radius=28,
                           fill="white", outline="#e2e8f0", width=2)
    draw.text((width / 2, 86), "Latest ZCU106 1Kbit LRS/HRS Distribution",
              font=font(52, True), fill="#0f172a", anchor="ma")
    draw.text((width / 2, 143), "Hollow bubbles are measured cell counts; curves are guides",
              font=font(27), fill="#64748b", anchor="ma")

    x_px = lambda value: pl + (value - edges[0]) / (edges[-1] - edges[0]) * pw
    y_px = lambda value: pb - value / y_limit * ph
    y_step = max(10, int(math.ceil((y_limit / 5) / 10) * 10))
    for value in range(0, y_limit + 1, y_step):
        y = y_px(value)
        draw.line((pl, y, pr, y), fill="#dbe3ed", width=2)
        draw.text((pl - 24, y), str(value), font=font(27), fill="#475569", anchor="rm")
    x_step = 20 if edges[-1] <= 240 else 40
    for value in range(int(math.ceil(edges[0] / x_step) * x_step), int(edges[-1]) + 1, x_step):
        x = x_px(value)
        draw.line((x, pb, x, pb + 12), fill="#64748b", width=3)
        draw.text((x, pb + 22), str(value), font=font(27), fill="#475569", anchor="ma")
    draw.line((pl, pt, pl, pb), fill="#334155", width=4)
    draw.line((pl, pb, pr, pb), fill="#334155", width=4)

    series = [
        (hrs_counts, "#2563eb", f"HRS · final RESET {FINAL_RESET_JOB[:8]}", hrs),
        (lrs_counts, "#e4572e", f"LRS · SET {SET_JOB[:8]}", lrs),
    ]
    for counts, color, _label, _values in series:
        points = [(x_px(float(x)), y_px(float(y))) for x, y in zip(centers, smooth_counts(counts))]
        draw.line(points, fill=color, width=7, joint="curve")
        for x, y in zip(centers, counts):
            if y == 0:
                continue
            px, py, radius = x_px(float(x)), y_px(float(y)), 10
            draw.ellipse((px - radius, py - radius, px + radius, py + radius),
                         fill="white", outline=color, width=5)

    tx = x_px(threshold)
    for y in range(int(pt), int(pb), 36):
        draw.line((tx, y, tx, min(y + 18, pb)), fill="#475569", width=4)
    annotation_x = min(tx + 35, pr - 520)
    draw.multiline_text((annotation_x, pt + 110),
                        f"Best separator: {threshold:.1f} µS\nAccuracy: {accuracy * 100:.2f}%",
                        font=font(27), fill="#334155", spacing=8)

    lx, ly = pr - 725, pt + 25
    for index, (_counts, color, label, values) in enumerate(series):
        y = ly + index * 66
        draw.line((lx, y, lx + 70, y), fill=color, width=7)
        draw.ellipse((lx + 25, y - 10, lx + 45, y + 10), fill="white", outline=color, width=5)
        draw.text((lx + 92, y), f"{label} · median {np.median(values):.1f} µS",
                  font=font(26), fill="#1e293b", anchor="lm")

    draw.text(((pl + pr) / 2, height - 145), "Nominal conductance (µS)",
              font=font(34), fill="#0f172a", anchor="ma")
    y_label = Image.new("RGBA", (650, 70), (255, 255, 255, 0))
    yd = ImageDraw.Draw(y_label)
    yd.text((325, 35), f"Number of cells per {BIN_WIDTH_US:g} µS bin",
            font=font(34), fill="#0f172a", anchor="mm")
    y_label = y_label.rotate(90, expand=True, resample=Image.Resampling.BICUBIC)
    image.paste(y_label, (55, int((height - y_label.height) / 2)), y_label)
    draw.text((pl, height - 84),
              "Conductance = ADC3/R10 nominal current ÷ 0.5 V; nominal gain 7 and 56 Ω shunt, not calibrated cell-only conductance.",
              font=font(23), fill="#64748b")

    png = OUT / "latest_lrs_hrs_conductance_distribution.png"
    image.save(png, dpi=(240, 240), optimize=True)
    with (OUT / "latest_lrs_hrs_conductance_bins.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["bin_center_uS", "hrs_cells", "lrs_cells"])
        writer.writerows(zip(centers, hrs_counts, lrs_counts))
    summary = {
        "source_jobs": {"lrs_set": SET_JOB, "hrs_final_reset": FINAL_RESET_JOB},
        "read_voltage_v": READ_VOLTAGE_V, "bin_width_uS": BIN_WIDTH_US,
        "lrs_conductance_uS": stats(lrs), "hrs_conductance_uS": stats(hrs),
        "best_separator_uS": threshold, "hrs_above_separator": hrs_errors,
        "lrs_below_separator": lrs_errors, "separation_accuracy_pct": accuracy * 100,
        "note": "Nominal, uncalibrated ADC3/R10 conductance from FPGA array-scheduler results.",
    }
    (OUT / "latest_lrs_hrs_conductance_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    return png, summary


def reset_event(pulses: int) -> tuple[float, float, float]:
    if not 1 <= pulses <= 288:
        raise RuntimeError(f"RESET pulse count {pulses} is outside the three-sweep range")
    index = (pulses - 1) % 96
    sweep = (pulses - 1) // 96
    vcc, wl = RESET_GRID[index]
    return vcc, wl, RESET_HOLD_MS[sweep]


def voltage_records(set_records: dict, reset_passes: list[dict]) -> list[dict]:
    rows = []
    for (row, col), record in sorted(set_records.items()):
        pulses = pulse_count(record)
        if pulses == 0:
            classification, vcc, wl, hold = "already_lrs", None, None, None
        elif record.get("target_met"):
            classification = "targeted_transition"
            vcc, wl = SET_GRID[pulses - 1]
            hold = 1.2
        else:
            classification, (vcc, wl), hold = "failed_limit", SET_GRID[-1], 1.2
        rows.append(dict(operation="SET", row=row, col=col, classification=classification,
                         pass_number=1, pulses=pulses, vcc_v=vcc, wl_v=wl, hold_ms=hold,
                         final_current_ua=current_ua(record)))

    unresolved = set(reset_passes[0])
    for pass_number, records in enumerate(reset_passes, 1):
        for key in sorted(unresolved):
            record = records[key]
            if not record.get("target_met"):
                continue
            pulses = pulse_count(record)
            if pulses:
                classification = "targeted_transition"
                vcc, wl, hold = reset_event(pulses)
            elif pass_number == 1:
                classification, vcc, wl, hold = "already_hrs", None, None, None
            else:
                classification, vcc, wl, hold = "indirect_before_retry", None, None, None
            rows.append(dict(operation="RESET", row=key[0], col=key[1], classification=classification,
                             pass_number=pass_number, pulses=pulses, vcc_v=vcc, wl_v=wl,
                             hold_ms=hold, final_current_ua=current_ua(record)))
            unresolved.remove(key)
    final_records = reset_passes[-1]
    for row, col in sorted(unresolved):
        record = final_records[(row, col)]
        rows.append(dict(operation="RESET", row=row, col=col, classification="failed_limit",
                         pass_number=len(reset_passes), pulses=pulse_count(record),
                         vcc_v=3.0, wl_v=2.88, hold_ms=6.0,
                         final_current_ua=current_ua(record)))
    return rows


def draw_box(draw, overlay, cx: float, values: list[float], color: str,
             y_min: float, y_max: float, top: float, bottom: float, seed: int) -> None:
    scale = lambda value: bottom - (value - y_min) / (y_max - y_min) * (bottom - top)
    q1, median, q3 = np.percentile(values, [25, 50, 75])
    low, high = min(values), max(values)
    draw.line((cx, scale(low), cx, scale(high)), fill=color, width=4)
    draw.line((cx - 34, scale(low), cx + 34, scale(low)), fill=color, width=4)
    draw.line((cx - 34, scale(high), cx + 34, scale(high)), fill=color, width=4)
    draw.rectangle((cx - 62, scale(q3), cx + 62, scale(q1)), outline=color, width=5)
    draw.line((cx - 62, scale(median), cx + 62, scale(median)), fill=color, width=6)
    rng = np.random.default_rng(seed)
    od = ImageDraw.Draw(overlay)
    rgb = tuple(int(color[index:index + 2], 16) for index in (1, 3, 5))
    for value, jitter in zip(values, rng.uniform(-92, 92, len(values))):
        x, y = cx + jitter, scale(value)
        od.ellipse((x - 6, y - 6, x + 6, y + 6), fill=(255, 255, 255, 150),
                   outline=(*rgb, 205), width=3)


def voltage_panel(image: Image.Image, bounds: tuple, title: str, ylabel: str,
                  groups: list[tuple[str, list[float], str]], y_min: float, y_max: float) -> None:
    draw = ImageDraw.Draw(image)
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    left, top, right, bottom = bounds
    pl, pt, pr, pb = left + 115, top + 90, right - 30, bottom - 145
    for tick in np.linspace(y_min, y_max, 6):
        y = pb - (tick - y_min) / (y_max - y_min) * (pb - pt)
        draw.line((pl, y, pr, y), fill="#dfe5ec", width=2)
        draw.text((pl - 18, y), f"{tick:.1f}", font=font(25), fill="#475569", anchor="rm")
    draw.line((pl, pt, pl, pb), fill="#334155", width=3)
    draw.line((pl, pb, pr, pb), fill="#334155", width=3)
    draw.text(((left + right) / 2, top + 30), title, font=font(35, True),
              fill="#1e293b", anchor="mm")
    centers = np.linspace(pl + 125, pr - 125, len(groups))
    for index, ((label, values, color), cx) in enumerate(zip(groups, centers)):
        draw_box(draw, overlay, cx, values, color, y_min, y_max, pt, pb, 100 + index)
        draw.text((cx, pb + 40), label, font=font(25, True), fill=color, anchor="mm")
        draw.text((cx, pb + 77), f"n={len(values)} · median {np.median(values):.2f}",
                  font=font(21), fill="#64748b", anchor="mm")
    image.alpha_composite(overlay)
    y_img = Image.new("RGBA", (470, 55), (255, 255, 255, 0))
    yd = ImageDraw.Draw(y_img)
    yd.text((235, 27), ylabel, font=font(28), fill="#0f172a", anchor="mm")
    y_img = y_img.rotate(90, expand=True, resample=Image.Resampling.BICUBIC)
    image.alpha_composite(y_img, (left + 6, int((pt + pb - y_img.height) / 2)))


def plot_voltage(rows: list[dict]) -> tuple[Path, dict]:
    set_cross = [row for row in rows if row["operation"] == "SET" and row["classification"] == "targeted_transition"]
    reset_cross = [row for row in rows if row["operation"] == "RESET" and row["classification"] == "targeted_transition"]
    reset_fail = [row for row in rows if row["operation"] == "RESET" and row["classification"] == "failed_limit"]
    set_already = [row for row in rows if row["operation"] == "SET" and row["classification"] == "already_lrs"]
    reset_already = [row for row in rows if row["operation"] == "RESET" and row["classification"] == "already_hrs"]
    reset_indirect = [row for row in rows if row["operation"] == "RESET" and row["classification"] == "indirect_before_retry"]

    orange, blue, red = "#dc6826", "#2a70b9", "#b4232f"
    canvas = Image.new("RGBA", (2400, 1450), "#f8fafc")
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((45, 45, 2355, 1405), radius=28,
                           fill="white", outline="#e2e8f0", width=2)
    draw.text((1200, 82), "Latest 1Kbit Programming Voltage Distribution",
              font=font(50, True), fill="#0f172a", anchor="mm")
    draw.text((1200, 133), "Hollow bubbles are individual targeted cells; boxes show quartiles and median",
              font=font(27), fill="#64748b", anchor="mm")
    vcc_groups = [("SET crossing", [r["vcc_v"] for r in set_cross], orange),
                  ("RESET crossing", [r["vcc_v"] for r in reset_cross], blue),
                  ("RESET failed cap", [r["vcc_v"] for r in reset_fail], red)]
    wl_groups = [("SET crossing", [r["wl_v"] for r in set_cross], orange),
                 ("RESET crossing", [r["wl_v"] for r in reset_cross], blue),
                 ("RESET failed cap", [r["wl_v"] for r in reset_fail], red)]
    voltage_panel(canvas, (60, 165, 1180, 1050), "VCC at terminal event", "Commanded VCC (V)",
                  vcc_groups, 2.15, 3.05)
    voltage_panel(canvas, (1220, 165, 2340, 1050), "Word-line at terminal event", "Commanded WL (V)",
                  wl_groups, 0.30, 3.00)

    draw.rounded_rectangle((90, 1085, 2310, 1370), radius=24,
                           fill="#f8fafc", outline="#d5dde7", width=3)
    draw.text((130, 1125),
              f"SET: {len(set_already)} cells were already LRS; {len(set_cross)} required a targeted pulse and crossed the 35 µA target.",
              font=font(26), fill="#334155")
    draw.text((130, 1180),
              f"RESET: {len(reset_already)} were already HRS, {len(reset_cross)} crossed during a targeted ramp, and {len(reset_indirect)} crossed before their next retry.",
              font=font(26), fill="#334155")
    draw.text((130, 1235),
              f"Seven cells remained above 34.256 µA after the 3.00 V / 2.88 V cap; their red markers are censored limits, not transitions.",
              font=font(26, True), fill="#991b1b")
    hold_counts = {hold: sum(row["hold_ms"] == hold for row in reset_cross) for hold in RESET_HOLD_MS}
    draw.text((130, 1295),
              f"Targeted RESET crossings by pulse width: 1.2 ms={hold_counts[1.2]}, 2.4 ms={hold_counts[2.4]}, 6.0 ms={hold_counts[6.0]}. Commanded DAC values; rails not independently probed.",
              font=font(23), fill="#64748b")

    png = OUT / "latest_set_reset_programming_voltage.png"
    canvas.convert("RGB").save(png, dpi=(240, 240), optimize=True)
    fields = ["operation", "row", "col", "classification", "pass_number", "pulses",
              "vcc_v", "wl_v", "hold_ms", "final_current_ua"]
    with (OUT / "latest_set_reset_programming_voltage_cells.csv").open(
            "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "source_jobs": {"set": SET_JOB, "reset_passes": RESET_JOBS},
        "method": {
            "transition": "Terminal commanded rail for a cell that crossed target during its own targeted FPGA ramp.",
            "excluded": "Cells already in-state or changing before their next targeted retry have no assignable transition voltage.",
            "failed_cap": "Censored limit at 3.00 V VCC, 2.88 V WL and 6.0 ms; not a transition.",
            "voltage_basis": "Commanded DAC values, not independently probed analog rails.",
        },
        "set": {
            "already_lrs": len(set_already), "targeted_transitions": len(set_cross),
            "transition_vcc_v": stats([r["vcc_v"] for r in set_cross]),
            "transition_wl_v": stats([r["wl_v"] for r in set_cross]),
        },
        "reset": {
            "already_hrs_first_pass": len(reset_already),
            "targeted_transitions": len(reset_cross),
            "indirect_before_retry": len(reset_indirect), "failed_at_cap": len(reset_fail),
            "targeted_transition_vcc_v": stats([r["vcc_v"] for r in reset_cross]),
            "targeted_transition_wl_v": stats([r["wl_v"] for r in reset_cross]),
            "targeted_transition_hold_ms_counts": {str(k): v for k, v in hold_counts.items()},
        },
    }
    (OUT / "latest_set_reset_programming_voltage_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    return png, summary


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    set_records = array_records(load_job(SET_JOB))
    reset_passes = [array_records(load_job(job_id)) for job_id in RESET_JOBS]
    final_reset = reset_passes[-1]
    lrs = np.asarray([current_ua(set_records[key]) / READ_VOLTAGE_V for key in sorted(set_records)])
    hrs = np.asarray([current_ua(final_reset[key]) / READ_VOLTAGE_V for key in sorted(final_reset)])
    distribution_png, distribution_summary = plot_distribution(lrs, hrs)
    rows = voltage_records(set_records, reset_passes)
    voltage_png, voltage_summary = plot_voltage(rows)
    print(json.dumps({
        "distribution_png": str(distribution_png),
        "voltage_png": str(voltage_png),
        "distribution": distribution_summary,
        "voltage": voltage_summary,
    }, indent=2))


if __name__ == "__main__":
    main()
