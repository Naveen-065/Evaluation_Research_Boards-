"""KC705 FMC management-I2C / daughtercard C30-C31 ngspice study.

The circuit values come from the two board designs:
  KC705: 4.7 kOhm pull-ups to 3.3 V on C30/C31.
  Card:  R54/R53 = 10 kOhm pull-ups to +1V8, followed by U18 PCA9306.

U18 is represented by a generic level-1 NMOS functional model.  It is not a
TI transistor model.  The direct pull-up/back-power results do not depend on
the U18 model because R53/R54 connect C30/C31 directly to +1V8.
"""
from pathlib import Path
import ctypes as ct
import csv
import json
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
        self.dll_path = os.add_dll_directory(str(DLLDIR))
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
        data = {}
        for label, vector in vectors.items():
            ptr = self.lib.ngGet_Vec_Info(vector.encode())
            if not ptr or ptr.contents.length < 1:
                raise RuntimeError((name, vector, self.logs[log_start:]))
            data[label] = np.ctypeslib.as_array(
                ptr.contents.real, (ptr.contents.length,)
            ).copy()
        log = "\n".join(self.logs[log_start:])
        (OUT / f"{name}.log").write_text(log, encoding="utf-8")
        if "Error:" in log or "Timestep too small" in log:
            raise RuntimeError(log)
        return {label: float(values[-1]) for label, values in data.items()}


def both_powered(host_low=False):
    sink = "Rhost_low scl 0 10" if host_low else "* host releases bus"
    return f"""Both boards powered; corrected U18 functional equivalent
.options reltol=1e-7 abstol=1e-12 vntol=1e-9
VKC kc3 0 3.3
V18 rail18 0 1.8
V33 card3 0 3.3
Rkc_scl kc3 scl 4.7k
Rkc_sda kc3 sda 4.7k
R54 rail18 scl 10k
R53 rail18 sda 10k
R58 card3 scl2 10k
R57 card3 sda2 10k
R56 card3 bias 200k
Mref bias bias rail18 0 PASS W=1u L=1u
Mscl scl2 bias scl 0 PASS W=1u L=1u
Msda sda2 bias sda 0 PASS W=1u L=1u
.model PASS NMOS (LEVEL=1 VTO=0.6 KP=0.02 LAMBDA=0 GAMMA=0)
{sink}
.op
.save v(scl) v(sda) v(scl2) v(sda2) v(bias)
.end
"""


def kc_on_card_off(load_ohm):
    return f"""KC705 on, daughtercard +1V8 unpowered; direct R53/R54 back-power path
.options reltol=1e-8 abstol=1e-13 vntol=1e-10
VKC kc3 0 3.3
Rkc_scl kc3 scl 4.7k
Rkc_sda kc3 sda 4.7k
R54 rail18 scl 10k
R53 rail18 sda 10k
Rload18 rail18 0 {load_ohm}
R58 card3 scl2 10k
R57 card3 sda2 10k
Rload33 card3 0 {load_ohm}
R56 card3 bias 200k
Mref bias bias rail18 0 PASS W=1u L=1u
Mscl scl2 bias scl 0 PASS W=1u L=1u
Msda sda2 bias sda 0 PASS W=1u L=1u
.model PASS NMOS (LEVEL=1 VTO=0.6 KP=0.02 LAMBDA=0 GAMMA=0)
.op
.save v(scl) v(sda) v(rail18) v(card3)
.end
"""


def card_on_kc_off(load_ohm):
    return f"""Daughtercard rails on, KC705 3.3-V management rail unpowered
.options reltol=1e-8 abstol=1e-13 vntol=1e-10
V18 rail18 0 1.8
V33 card3 0 3.3
R54 rail18 scl 10k
R53 rail18 sda 10k
R58 card3 scl2 10k
R57 card3 sda2 10k
R56 card3 bias 200k
Mref bias bias rail18 0 PASS W=1u L=1u
Mscl scl2 bias scl 0 PASS W=1u L=1u
Msda sda2 bias sda 0 PASS W=1u L=1u
.model PASS NMOS (LEVEL=1 VTO=0.6 KP=0.02 LAMBDA=0 GAMMA=0)
Rkc_scl kc3 scl 4.7k
Rkc_sda kc3 sda 4.7k
Rload_kc kc3 0 {load_ohm}
.op
.save v(scl) v(sda) v(scl2) v(sda2) v(kc3) v(bias)
.end
"""


def kc_on_card_off_transient(load_ohm):
    return f"""KC705 startup charging an unpowered daughtercard +1V8 rail through C30/C31
.options reltol=1e-6 abstol=1e-12 vntol=1e-8
VKC kc3 0 PWL(0 0 1u 0 2u 3.3)
Rkc_scl kc3 scl 4.7k
Rkc_sda kc3 sda 4.7k
R54 rail18 scl 10k
R53 rail18 sda 10k
Rload18 rail18 0 {load_ohm}
Crail18 rail18 0 10u
.tran 0.1m 0.5 0 0.1m uic
.save time v(scl) v(rail18)
.end
"""


spice = Spice()
vectors_both = {
    "connector_scl_V": "v(scl)",
    "connector_sda_V": "v(sda)",
    "si5351_scl_side_V": "v(scl2)",
    "si5351_sda_side_V": "v(sda2)",
    "u18_bias_V": "v(bias)",
}
idle = spice.run("both_powered_idle", both_powered(False), vectors_both)
low = spice.run("both_powered_host_low", both_powered(True), vectors_both)

load_values = [100, 1e3, 1.8e3, 10e3, 100e3, 1e6, 10e6]
kc_on_rows = []
card_on_rows = []
for load in load_values:
    tag = f"{load:g}".replace("+", "").replace(".", "p")
    result = spice.run(
        f"kc705_on_card_off_load_{tag}",
        kc_on_card_off(load),
        {"connector_V": "v(scl)", "card_1v8_rail_V": "v(rail18)",
         "card_3v3_rail_V": "v(card3)"},
    )
    result["load_ohm"] = load
    result["total_injection_A"] = result["card_1v8_rail_V"] / load
    kc_on_rows.append(result)

    result = spice.run(
        f"card_on_kc705_off_load_{tag}",
        card_on_kc_off(load),
        {"connector_V": "v(scl)", "si5351_side_V": "v(scl2)",
         "kc705_3v3_rail_V": "v(kc3)", "u18_bias_V": "v(bias)"},
    )
    result["load_ohm"] = load
    result["total_injection_A"] = result["kc705_3v3_rail_V"] / load
    card_on_rows.append(result)

transient = spice.run(
    "kc705_on_card_off_transient_100k",
    kc_on_card_off_transient(100e3),
    {"time_s": "time", "connector_V": "v(scl)", "card_1v8_rail_V": "v(rail18)"},
)

# Derived currents for the both-powered operating points.
idle["injection_into_1v8_per_line_A"] = (
    idle["connector_scl_V"] - 1.8
) / 10e3
idle["injection_into_1v8_total_A"] = 2 * idle["injection_into_1v8_per_line_A"]
low["host_sink_from_kc_pullup_A"] = (3.3 - low["connector_scl_V"]) / 4.7e3
low["host_sink_from_card_1v8_pullup_A"] = (1.8 - low["connector_scl_V"]) / 10e3
low["host_sink_from_card_3v3_pullup_A"] = (
    3.3 - low["si5351_scl_side_V"]
) / 10e3
low["host_sink_total_A"] = (
    low["host_sink_from_kc_pullup_A"]
    + low["host_sink_from_card_1v8_pullup_A"]
    + low["host_sink_from_card_3v3_pullup_A"]
)

for name, rows in [("kc705_on_card_off_sweep.csv", kc_on_rows),
                   ("card_on_kc705_off_sweep.csv", card_on_rows)]:
    with (OUT / name).open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

summary = {
    "engine": spice.version,
    "model_scope": [
        "Actual resistor values and board connections",
        "Generic level-1 MOS functional equivalent for corrected U18",
        "Unpowered-rail load swept because real regulator reverse behavior and board load are unknown",
        "No prediction of silicon damage or regulator thermal behavior",
    ],
    "both_powered_idle": idle,
    "both_powered_host_low": low,
    "kc705_on_card_off_sweep": kc_on_rows,
    "card_on_kc705_off_sweep": card_on_rows,
    "transient_100k_final": transient,
}
(OUT / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

loads = np.array([row["load_ohm"] for row in kc_on_rows])
fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
axes[0].semilogx(loads, [row["card_1v8_rail_V"] for row in kc_on_rows], "o-", label="card +1V8 rail")
axes[0].semilogx(loads, [row["connector_V"] for row in kc_on_rows], "s--", label="C30/C31")
axes[0].axhline(1.8, color="#777", linestyle=":", linewidth=1)
axes[0].set(title="KC705 on, daughtercard off", xlabel="Equivalent unpowered-card load (ohm)", ylabel="Voltage (V)")
axes[0].legend()
axes[1].semilogx(loads, [row["kc705_3v3_rail_V"] for row in card_on_rows], "o-", label="KC705 3.3-V rail")
axes[1].semilogx(loads, [row["connector_V"] for row in card_on_rows], "s--", label="C30/C31")
axes[1].axhline(1.8, color="#777", linestyle=":", linewidth=1)
axes[1].set(title="Daughtercard on, KC705 off", xlabel="Equivalent unpowered-carrier load (ohm)", ylabel="Voltage (V)")
axes[1].legend()
for axis in axes:
    axis.grid(alpha=0.2)
fig.suptitle("FMC C30/C31 pull-up and back-power paths (ngspice 46)", fontweight="bold")
fig.tight_layout()
fig.savefig(OUT / "simulation_results.png", dpi=170)

print(json.dumps(summary, indent=2))
