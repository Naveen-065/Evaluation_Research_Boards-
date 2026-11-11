"""Plot measured 1Kbit LRS/HRS conductance distributions."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
OUT = ROOT / "output" / "plots"
RESULT_CSV = ROOT.parent / "results" / "final_cell_reads.csv"
LRS_JOB = "d42d176742d74a90bd4fef034aec5178"
HRS_JOB = "30ab5bc5867444e39657ef724e0e33de"
READ_VOLTAGE_V = 0.5
BIN_WIDTH_US = 4.0


def measured_conductance(job_id: str) -> np.ndarray:
    state = "LRS" if job_id == LRS_JOB else "HRS"
    values, coordinates = [], set()
    with RESULT_CSV.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["state"] != state or row["job_id"] != job_id:
                continue
            coordinate = (int(row["row"]), int(row["col"]))
            coordinates.add(coordinate)
            if row["clipped"] != "false":
                raise RuntimeError(f"{job_id}: clipped final read at r{coordinate[0]}/c{coordinate[1]}")
            values.append(float(row["conductance_uS"]))
    if len(values) != 1024 or len(coordinates) != 1024:
        raise RuntimeError(f"{job_id}: expected 1024 unique final cell reads")
    return np.asarray(values, dtype=float)


def smooth_counts(counts: np.ndarray, sigma_bins: float = 1.2) -> np.ndarray:
    radius = int(np.ceil(4 * sigma_bins))
    x = np.arange(-radius, radius + 1, dtype=float)
    kernel = np.exp(-0.5 * (x / sigma_bins) ** 2)
    kernel /= kernel.sum()
    return np.convolve(counts.astype(float), kernel, mode="same")


def best_threshold(hrs: np.ndarray, lrs: np.ndarray) -> tuple[float, int, int]:
    ordered = np.unique(np.concatenate([hrs, lrs]))
    candidates = (ordered[:-1] + ordered[1:]) / 2
    errors = np.asarray([(hrs >= threshold).sum() + (lrs < threshold).sum() for threshold in candidates])
    index = int(np.argmin(errors))
    threshold = float(candidates[index])
    return threshold, int((hrs >= threshold).sum()), int((lrs < threshold).sum())


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    filename = "seguisb.ttf" if bold else "segoeui.ttf"
    return ImageFont.truetype(str(Path("C:/Windows/Fonts") / filename), size)


def nice_ceiling(value: float) -> int:
    magnitude = 10 ** max(0, math.floor(math.log10(value)) - 1)
    return int(math.ceil(value / magnitude) * magnitude)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    lrs = measured_conductance(LRS_JOB)
    hrs = measured_conductance(HRS_JOB)

    lower = np.floor(min(hrs.min(), lrs.min()) / BIN_WIDTH_US) * BIN_WIDTH_US
    upper = np.ceil(max(hrs.max(), lrs.max()) / BIN_WIDTH_US) * BIN_WIDTH_US
    edges = np.arange(lower, upper + BIN_WIDTH_US, BIN_WIDTH_US)
    centers = (edges[:-1] + edges[1:]) / 2
    hrs_counts, _ = np.histogram(hrs, bins=edges)
    lrs_counts, _ = np.histogram(lrs, bins=edges)
    threshold, hrs_errors, lrs_errors = best_threshold(hrs, lrs)
    error_count = hrs_errors + lrs_errors
    accuracy = 1 - error_count / (len(hrs) + len(lrs))

    width, height = 2400, 1400
    left, right, top, bottom = 220, 90, 170, 225
    plot_left, plot_right = left, width - right
    plot_top, plot_bottom = top, height - bottom
    plot_width, plot_height = plot_right - plot_left, plot_bottom - plot_top
    y_limit = nice_ceiling(max(hrs_counts.max(), lrs_counts.max()) * 1.22)
    image = Image.new("RGB", (width, height), "#f8fafc")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (55, 55, width - 55, height - 55), radius=28, fill="white", outline="#e2e8f0", width=2
    )

    title_font = font(52, bold=True)
    label_font = font(34)
    tick_font = font(27)
    legend_font = font(27)
    small_font = font(24)
    draw.text((width / 2, 82), "Measured 1Kbit Array Conductance Distributions", font=title_font,
              fill="#0f172a", anchor="ma")

    def x_px(value: float) -> float:
        return plot_left + (value - edges[0]) / (edges[-1] - edges[0]) * plot_width

    def y_px(value: float) -> float:
        return plot_bottom - value / y_limit * plot_height

    y_step = max(10, int(math.ceil((y_limit / 5) / 10) * 10))
    for value in range(0, y_limit + 1, y_step):
        y = y_px(value)
        draw.line((plot_left, y, plot_right, y), fill="#dbe3ed", width=2)
        draw.text((plot_left - 25, y), str(value), font=tick_font, fill="#475569", anchor="rm")
    x_start = int(math.ceil(edges[0] / 20) * 20)
    for value in range(x_start, int(edges[-1]) + 1, 20):
        x = x_px(value)
        draw.line((x, plot_bottom, x, plot_bottom + 12), fill="#64748b", width=3)
        draw.text((x, plot_bottom + 22), str(value), font=tick_font, fill="#475569", anchor="ma")
    draw.line((plot_left, plot_top, plot_left, plot_bottom), fill="#334155", width=4)
    draw.line((plot_left, plot_bottom, plot_right, plot_bottom), fill="#334155", width=4)

    series = [
        (hrs_counts, "#2563eb", "HRS after RESET run", hrs),
        (lrs_counts, "#e4572e", "LRS after SET run", lrs),
    ]
    for counts, color, _label, _values in series:
        curve = smooth_counts(counts)
        nonzero = counts > 0
        points = [(x_px(float(x)), y_px(float(y))) for x, y in zip(centers, curve)]
        draw.line(points, fill=color, width=7, joint="curve")
        for x, y, show in zip(centers, counts, nonzero):
            if not show:
                continue
            px, py = x_px(float(x)), y_px(float(y))
            radius = 10
            draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill="white", outline=color, width=5)

    threshold_x = x_px(threshold)
    dash = 20
    y = plot_top
    while y < plot_bottom:
        draw.line((threshold_x, y, threshold_x, min(y + dash, plot_bottom)), fill="#475569", width=4)
        y += dash * 2
    annotation = (
        f"Best measured threshold: {threshold:.1f} µS\n"
        f"Separation accuracy: {accuracy * 100:.2f}%"
    )
    annotation_x, annotation_y = threshold_x + 135, plot_top + 85
    draw.multiline_text((annotation_x, annotation_y), annotation, font=legend_font, fill="#334155", spacing=8)
    arrow_end = (threshold_x + 5, plot_top + 185)
    draw.line((annotation_x - 15, annotation_y + 70, *arrow_end), fill="#475569", width=4)
    draw.polygon(
        [(arrow_end[0], arrow_end[1]), (arrow_end[0] + 16, arrow_end[1] - 5),
         (arrow_end[0] + 9, arrow_end[1] + 12)], fill="#475569"
    )

    legend_x, legend_y = plot_right - 650, plot_top + 24
    for index, (_counts, color, label, values) in enumerate(series):
        ly = legend_y + index * 64
        draw.line((legend_x, ly, legend_x + 72, ly), fill=color, width=7)
        draw.ellipse((legend_x + 26, ly - 10, legend_x + 46, ly + 10), fill="white", outline=color, width=5)
        draw.text((legend_x + 92, ly),
                  f"{label}  (n={len(values)}, median={np.median(values):.1f} µS)",
                  font=legend_font, fill="#1e293b", anchor="lm")

    draw.text(((plot_left + plot_right) / 2, height - 142), "Nominal conductance (µS)",
              font=label_font, fill="#0f172a", anchor="ma")
    y_label = Image.new("RGBA", (650, 70), (255, 255, 255, 0))
    y_draw = ImageDraw.Draw(y_label)
    y_draw.text((325, 35), f"Number of cells per {BIN_WIDTH_US:g} µS bin", font=label_font,
                fill="#0f172a", anchor="mm")
    y_label = y_label.rotate(90, expand=True, resample=Image.Resampling.BICUBIC)
    image.paste(y_label, (55, int((height - y_label.height) / 2)), y_label)

    note = (
        "Hollow circles: measured bin counts; curves: Gaussian-smoothed guides.  "
        "Conductance = SET/R10 ΔI ÷ 0.5 V. Nominal gain 7; not calibrated cell-only conductance."
    )
    draw.text((plot_left, height - 82), note, font=small_font, fill="#475569", anchor="la")

    png = OUT / "lrs_hrs_1kbit_conductance_distribution.png"
    image.save(png, dpi=(240, 240), optimize=True)

    with (OUT / "lrs_hrs_1kbit_conductance_bins.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["bin_center_uS", "hrs_cells", "lrs_cells"])
        writer.writerows(zip(centers, hrs_counts, lrs_counts))

    summary = {
        "read_voltage_v": READ_VOLTAGE_V,
        "bin_width_uS": BIN_WIDTH_US,
        "hrs": {
            "job_id": HRS_JOB,
            "cells": int(hrs.size),
            "median_uS": float(np.median(hrs)),
            "mean_uS": float(np.mean(hrs)),
            "min_uS": float(np.min(hrs)),
            "max_uS": float(np.max(hrs)),
        },
        "lrs": {
            "job_id": LRS_JOB,
            "cells": int(lrs.size),
            "median_uS": float(np.median(lrs)),
            "mean_uS": float(np.mean(lrs)),
            "min_uS": float(np.min(lrs)),
            "max_uS": float(np.max(lrs)),
        },
        "best_threshold_uS": threshold,
        "hrs_above_threshold": hrs_errors,
        "lrs_below_threshold": lrs_errors,
        "separation_accuracy": accuracy,
        "note": "Nominal, uncalibrated conductance from final full-array mac_read captures.",
    }
    (OUT / "lrs_hrs_1kbit_conductance_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    print(png)


if __name__ == "__main__":
    main()
