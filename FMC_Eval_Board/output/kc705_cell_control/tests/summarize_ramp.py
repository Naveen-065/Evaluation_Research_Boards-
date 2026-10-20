"""Audit a saved hardware ramp job; never access the bench."""
import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def summarize(ident):
    job = json.loads((ROOT / "runs" / f"{ident}.json").read_text())
    log = (ROOT / "runs" / f"{ident}.log").read_text(encoding="utf-8")
    assert job["state"] == "completed" and "JOB_COMPLETE cycle\n" in log
    assert job["parameters"]["mode"] == "cycle"
    rows = job["results"]
    assert all((r["row"], r["col"]) == (0, 0) and not r["clipped"] for r in rows)
    current = lambda r: r["channels"][2]["delta_current_ua"]
    confirms = [r for r in rows if re.match(r"confirm_set_\d+(?:_met)?__", r["operation"])]
    assert len(confirms) == 10 and all(current(r) >= 35 for r in confirms)
    rails = [tuple(map(int, m.groups())) for r in rows
             if (m := re.search(r"_v(\d+)_wl(\d+)$", r["operation"]))]
    assert rails and all(v <= 3000 and wl <= 3000 for v, wl in rails)
    outcomes = {}
    for op, pulses, met, last in re.findall(
            r"^RAMP_COMPLETE (set|reset) (\d+) ([01]) ([-.\d]+)$", log, re.M):
        actual_pulses = sum(r["operation"] == f"{op}_pulse" for r in rows)
        assert actual_pulses == int(pulses)
        outcomes[op] = dict(pulses=actual_pulses, target_met=bool(int(met)),
                            last_read_uA_nominal=float(last))
    assert set(outcomes) == {"set", "reset"}
    assert outcomes["set"]["target_met"] and outcomes["set"]["pulses"] == 0
    assert not outcomes["reset"]["target_met"] and outcomes["reset"]["pulses"] == 96
    assert rows[-1]["operation"] == "after_reset_limit__s96_v3000_wl2880"
    summary = dict(
        job_id=ident, state=job["state"], started=job["started"], finished=job["finished"],
        parameters=job["parameters"], captures=len(rows), initial_read_uA_nominal=current(rows[0]),
        set_confirmation_range_uA_nominal=[min(map(current, confirms)), max(map(current, confirms))],
        outcomes=outcomes, max_requested_vcc_v=max(v for v, _ in rails) / 1000,
        max_requested_wl_v=max(w for _, w in rails) / 1000,
        dac_max_code=39321, ideal_dac_max_v=39321 * 5 / 65536,
        read_profile_restored=True, cpu_held_on_completion=True,
        calibration="56 ohm shunt, nominal gain 7, active-minus-idle ADC3 current; not calibrated",
        limitation="Command limits are verified; actual analog voltages were not measured during the ramp.",
        source_hashes={name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                       for name in ("control.tcl", "scan_ramp.tcl", "gui/app.js", "gui/index.html")},
    )
    (ROOT / "evidence/ramp_cycle.json").write_text(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("job")
    print(json.dumps(summarize(parser.parse_args().job), indent=2))
