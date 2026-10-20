"""Bounded ngspice checks for the DAC81416 REF/REFCMP population error.

This is deliberately not a transistor-level DAC81416 model: TI's downloadable
IBIS model marks pins 33 (REF) and 34 (REFCMP) NC and contains no analog
reference-loop model.  The simulations therefore answer only two questions
that can be supported by published/known values:

1. How much does the specified 150 nF REF capacitor reduce a short load pulse
   when the published 0.1-ohm reference output impedance is used?
2. By what factor does 100 nF change a compensation-node RC response compared
   with the specified 330 pF, over a sweep of unknown internal resistance?

The second model is normalized.  It cannot establish loop stability or predict
silicon damage; it demonstrates the invariant 100 nF / 330 pF = 303.03 ratio.
"""

from pathlib import Path
import ctypes as ct
import csv
import json
import math
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


OUT = Path(__file__).resolve().parent
DLLDIR = Path(r"C:/Program Files/KiCad/10.0/bin")
os.chdir(OUT)


class VecInfo(ct.Structure):
    _fields_ = [
        ("name", ct.c_char_p),
        ("type", ct.c_int),
        ("flags", ct.c_short),
        ("real", ct.POINTER(ct.c_double)),
        ("complex", ct.c_void_p),
        ("length", ct.c_int),
    ]


class Spice:
    def __init__(self):
        self.dll_dir_handle = os.add_dll_directory(str(DLLDIR))
        self.lib = ct.CDLL(str(DLLDIR / "ngspice.dll"))
        self.logs = []
        callback = ct.CFUNCTYPE(ct.c_int, ct.c_char_p, ct.c_int, ct.c_void_p)
        exit_cb = ct.CFUNCTYPE(
            ct.c_int, ct.c_int, ct.c_bool, ct.c_bool, ct.c_int, ct.c_void_p
        )
        self.stdout_cb = callback(lambda msg, _id, _user: self._log(msg))
        self.status_cb = callback(lambda _msg, _id, _user: 0)
        self.exit_cb = exit_cb(lambda _a, _b, _c, _d, _e: 0)
        self.lib.ngSpice_Init.argtypes = [ct.c_void_p] * 7
        self.lib.ngSpice_Init(
            self.stdout_cb, self.status_cb, self.exit_cb, None, None, None, None
        )
        self.lib.ngSpice_Command.argtypes = [ct.c_char_p]
        self.lib.ngSpice_Circ.argtypes = [ct.POINTER(ct.c_char_p)]
        self.lib.ngGet_Vec_Info.argtypes = [ct.c_char_p]
        self.lib.ngGet_Vec_Info.restype = ct.POINTER(VecInfo)
        self.command("version")
        self.version = "\n".join(self.logs)

    def _log(self, msg):
        self.logs.append(msg.decode(errors="replace"))
        return 0

    def command(self, command):
        result = self.lib.ngSpice_Command(command.encode())
        if result:
            raise RuntimeError((command, result))

    def run(self, name, netlist, vectors):
        self.command("destroy all")
        log_start = len(self.logs)
        (OUT / f"{name}.cir").write_text(netlist, encoding="ascii")
        lines = netlist.strip().splitlines()
        encoded = (ct.c_char_p * (len(lines) + 1))(
            *[line.encode() for line in lines], None
        )
        if self.lib.ngSpice_Circ(encoded):
            raise RuntimeError(f"Failed to load {name}")
        self.command("run")
        result = {}
        for label, vector in vectors.items():
            ptr = self.lib.ngGet_Vec_Info(vector.encode())
            if not ptr or ptr.contents.length < 1:
                raise RuntimeError((name, vector, self.logs[log_start:]))
            result[label] = np.ctypeslib.as_array(
                ptr.contents.real, (ptr.contents.length,)
            ).copy()
        log = "\n".join(self.logs[log_start:])
        (OUT / f"{name}.log").write_text(log, encoding="utf-8")
        if "Error:" in log or "Timestep too small" in log:
            raise RuntimeError(log)
        return result


def ref_load_pulse(capacitance):
    cap_line = "* no external REF capacitor" if capacitance is None else f"Cref ref 0 {capacitance}"
    return f"""DAC81416 REF load-pulse equivalent
* Published values used: 2.5 V reference, 0.1 ohm output impedance.
* 5 mA, 5 ns pulse is a sensitivity stimulus, not a claimed DAC load waveform.
.options reltol=1e-7 abstol=1e-13 vntol=1e-10 plotwinsize=0
Videal ideal 0 2.5
Rout ideal ref 0.1
Iload ref 0 PULSE(0 5m 1u 1n 1n 5n 2u)
{cap_line}
.tran 0.02n 1.02u
.save time v(ref)
.end
"""


def refcmp_rc(resistance, capacitance):
    stop = max(25e-6, 8.0 * resistance * capacitance)
    step = stop / 4000.0
    return f"""Normalized DAC81416 REFCMP RC sensitivity model
* Rint={resistance:g} ohm is swept because TI does not publish the internal value.
* This is not a reference-loop stability model.
.options reltol=1e-8 abstol=1e-13 vntol=1e-10 plotwinsize=0
Vdrive src 0 PULSE(0 1 1u 1n 1n {2*stop:g} {4*stop:g})
Rint src refcmp {resistance:g}
Ccomp refcmp 0 {capacitance:g}
.tran {step:g} {stop:g}
.save time v(refcmp)
.end
"""


def interpolate_at(time, values, target):
    return float(np.interp(target, time, values))


spice = Spice()

# REF output pulse check.
ref_cases = {}
for label, cap in (("missing", None), ("specified_150nF", "150n")):
    result = spice.run(
        f"ref_load_pulse_{label}",
        ref_load_pulse(cap),
        {"time_s": "time", "ref_V": "v(ref)"},
    )
    ref_cases[label] = result

with (OUT / "ref_load_pulse.csv").open("w", newline="", encoding="utf-8") as handle:
    writer = csv.writer(handle)
    writer.writerow(["time_s", "ref_missing_V", "ref_150nF_V"])
    count = min(len(v["time_s"]) for v in ref_cases.values())
    # ngspice uses matching timesteps here; interpolate to be robust if that changes.
    base_time = ref_cases["missing"]["time_s"][:count]
    with_cap = np.interp(
        base_time,
        ref_cases["specified_150nF"]["time_s"],
        ref_cases["specified_150nF"]["ref_V"],
    )
    for t, v0, v1 in zip(
        base_time,
        ref_cases["missing"]["ref_V"][:count],
        with_cap,
    ):
        writer.writerow([f"{t:.12g}", f"{v0:.12g}", f"{v1:.12g}"])

# REFCMP generic RC sweep.  Ratios are meaningful even though the absolute R is unknown.
resistances = [1e3, 10e3, 100e3, 1e6]
capacitances = {"specified_330pF": 330e-12, "assembled_100nF": 100e-9}
rc_rows = []
rc_traces = {}
for resistance in resistances:
    for label, capacitance in capacitances.items():
        result = spice.run(
            f"refcmp_R{resistance:g}_{label}",
            refcmp_rc(resistance, capacitance),
            {"time_s": "time", "refcmp_norm": "v(refcmp)"},
        )
        tau = resistance * capacitance
        t90 = 1e-6 + math.log(10) * tau
        t99 = 1e-6 + math.log(100) * tau
        t999 = 1e-6 + math.log(1000) * tau
        rc_rows.append({
            "assumed_internal_R_ohm": resistance,
            "case": label,
            "capacitance_F": capacitance,
            "tau_s": tau,
            "ngspice_at_1tau": interpolate_at(result["time_s"], result["refcmp_norm"], 1e-6 + tau),
            "ngspice_at_1ms_after_step": interpolate_at(result["time_s"], result["refcmp_norm"], 1.001e-3),
            "t90_s": t90 - 1e-6,
            "t99_s": t99 - 1e-6,
            "t99_9_s": t999 - 1e-6,
        })
        if resistance == 100e3:
            rc_traces[label] = result

with (OUT / "refcmp_rc_sweep.csv").open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=rc_rows[0].keys())
    writer.writeheader()
    writer.writerows(rc_rows)

# Plots.
fig, axes = plt.subplots(1, 2, figsize=(11.4, 4.2))
for label, result in ref_cases.items():
    axes[0].plot(
        (result["time_s"] - 1e-6) * 1e9,
        (2.5 - result["ref_V"]) * 1e3,
        label=label.replace("_", " "),
        linewidth=2,
    )
axes[0].set_xlim(-2, 15)
axes[0].set_xlabel("Time from load-pulse start (ns)")
axes[0].set_ylabel("REF droop (mV)")
axes[0].set_title("Published 0.1-ohm REF equivalent\n5 mA, 5 ns sensitivity pulse")
axes[0].grid(True, alpha=0.3)
axes[0].legend()

for label, result in rc_traces.items():
    axes[1].semilogx(
        np.maximum((result["time_s"] - 1e-6) * 1e3, 1e-6),
        result["refcmp_norm"],
        label=label.replace("_", " "),
        linewidth=2,
    )
axes[1].set_xlim(0.005, 100)
axes[1].set_ylim(-0.03, 1.05)
axes[1].set_xlabel("Time from step (ms), illustrative Rint = 100 kohm")
axes[1].set_ylabel("Normalized REFCMP response")
axes[1].set_title("RC sensitivity only; not a loop-stability model")
axes[1].grid(True, which="both", alpha=0.3)
axes[1].legend()
fig.tight_layout()
fig.savefig(OUT / "ngspice_reference_results.png", dpi=180)
plt.close(fig)

# Local PCB geometry, taken directly from the .kicad_pcb pad/segment records.
fig, ax = plt.subplots(figsize=(5.8, 7.2))
pad_y = 110.4625
for pin, x, net, color in [
    (32, 99.5125, "GND (VSS)", "#777777"),
    (33, 99.0125, "REF — NC", "#d62728"),
    (34, 98.5125, "REFCMP", "#ff7f0e"),
    (35, 98.0125, "REFGND", "#777777"),
]:
    ax.add_patch(plt.Rectangle((x - 0.18, pad_y - 0.30), 0.36, 0.60, color=color, alpha=0.85))
    ax.text(x, pad_y, str(pin), ha="center", va="center", fontsize=8, color="white", weight="bold")
    ax.text(x, pad_y + 0.46, net, ha="center", va="top", fontsize=8, rotation=35)
trace_x = [98.5125, 98.5125, 99.428502, 99.428502]
trace_y = [110.4625, 109.388971, 108.472969, 107.919401]
ax.plot(trace_x, trace_y, color="#c23b22", linewidth=4, solid_capstyle="round", label="REFCMP copper, ~2.92 mm")
ax.add_patch(plt.Rectangle((99.05, 105.75), 0.76, 2.15, fill=False, linewidth=2, color="#1f77b4"))
ax.scatter([99.4285, 99.4285], [107.2444, 105.6444], s=150, c=["#c23b22", "#777777"], zorder=5)
ax.text(99.9, 106.44, "C6 1206\n100 nF assembled\npad 2 = REFCMP\npad 1 = GND", va="center", fontsize=9)
ax.annotate("REF pin 33 has no copper\nand no capacitor", xy=(99.0125, 110.4625), xytext=(96.55, 109.1),
            arrowprops=dict(arrowstyle="->", color="#d62728"), color="#d62728", fontsize=10)
ax.annotate("REFCMP trace: 0.2 mm wide, ~2.92 mm long", xy=(98.9, 109.0), xytext=(96.55, 108.0),
            arrowprops=dict(arrowstyle="->", color="#c23b22"), color="#c23b22", fontsize=9)
ax.set_aspect("equal", adjustable="box")
ax.invert_yaxis()
ax.set_xlim(96.4, 101.4)
ax.set_ylim(111.35, 105.1)
ax.set_xlabel("PCB X (mm)")
ax.set_ylabel("PCB Y (mm)")
ax.set_title("U1 REF / REFCMP layout\n(reconstructed from KiCad coordinates)", fontsize=13)
ax.grid(True, alpha=0.15)
fig.tight_layout()
fig.savefig(OUT / "u1_reference_layout.png", dpi=180)
plt.close(fig)

missing_min = float(np.min(ref_cases["missing"]["ref_V"]))
cap_min = float(np.min(ref_cases["specified_150nF"]["ref_V"]))
summary = {
    "engine": spice.version,
    "source_facts": {
        "ref_nominal_V": 2.5,
        "ref_output_impedance_ohm": 0.1,
        "datasheet_REF_minimum_F": 150e-9,
        "datasheet_REFCMP_typical_F": 330e-12,
        "bom_C6_F": 100e-9,
    },
    "ref_pulse_sensitivity": {
        "stimulus_A": 5e-3,
        "pulse_width_s": 5e-9,
        "missing_cap_min_REF_V": missing_min,
        "specified_cap_min_REF_V": cap_min,
        "missing_cap_max_droop_V": 2.5 - missing_min,
        "specified_cap_max_droop_V": 2.5 - cap_min,
    },
    "refcmp_sensitivity": {
        "capacitance_ratio_100n_over_330p": 100e-9 / 330e-12,
        "pole_frequency_ratio_current_over_specified": 330e-12 / 100e-9,
        "note": "Absolute response and stability cannot be predicted without TI's analog internal-reference model; RC times scale by the reported capacitance ratio for every assumed Rint.",
    },
}
(OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

print(json.dumps(summary, indent=2))
