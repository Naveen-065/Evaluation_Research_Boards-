"""Verify the proposed R53/R54 removal with the existing ngspice model."""

from pathlib import Path
import json
import runpy


HERE = Path(__file__).resolve().parent
model = runpy.run_path(str(HERE / "simulate_i2c.py"))
spice = model["spice"]


def without_low_side_pullups(host_low: bool):
    netlist = model["both_powered"](host_low)
    return netlist.replace(
        "R54 rail18 scl 10k\nR53 rail18 sda 10k\n",
        "* R54 and R53 removed: KC705 R316/R317 provide the side-1 pull-ups\n",
    )


vectors = {
    "connector_scl_V": "v(scl)",
    "connector_sda_V": "v(sda)",
    "si5351_scl_side_V": "v(scl2)",
    "si5351_sda_side_V": "v(sda2)",
    "u18_bias_V": "v(bias)",
}

idle = spice.run(
    "rework_R53_R54_removed_idle", without_low_side_pullups(False), vectors
)
low = spice.run(
    "rework_R53_R54_removed_host_low", without_low_side_pullups(True), vectors
)

low["kc705_pullup_current_A"] = (3.3 - low["connector_scl_V"]) / 4700
low["si5351_pullup_current_A"] = (3.3 - low["si5351_scl_side_V"]) / 10000
low["total_low_sink_current_A"] = (
    low["kc705_pullup_current_A"] + low["si5351_pullup_current_A"]
)

result = {
    "change": "Remove R53 and R54; retain R57/R58 and corrected U18",
    "idle": idle,
    "one_line_low": low,
}
(HERE / "rework_results.json").write_text(
    json.dumps(result, indent=2), encoding="utf-8"
)
print(json.dumps(result, indent=2))
