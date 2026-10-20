"""Read-only check of a routed image against the proven FMC port configuration."""
import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def ports(path):
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    assert len(rows) == len({r["PORT"] for r in rows}) == 41
    return {r["PORT"]: r for r in rows}


def audit(build):
    baseline = ports(ROOT / "build_before_wb_dac2_fix/port_properties.tsv")
    current = ports(build / "port_properties.tsv")
    differences = {p: {"before": baseline.get(p), "after": current.get(p)}
                   for p in baseline.keys() | current.keys()
                   if baseline.get(p) != current.get(p)}
    assert not differences, differences
    timing = (build / "timing_summary.rpt").read_text()
    assert "All user specified timing constraints are met." in timing
    table = timing.split("WNS(ns)", 1)[1]
    values = next(line.split() for line in table.splitlines()
                  if re.match(r"^\s+-?\d+\.\d+\s", line))
    setup, hold = float(values[0]), float(values[4])
    assert setup >= 0 and hold >= 0
    drc = (build / "drc.rpt").read_text()
    assert not re.search(r"\|\s*(Error|Critical Warning)\s*\|", drc)
    hashes = {}
    for name in ("kc705_adc_capture.bit", "kc705_adc_capture.ltx"):
        data = (build / name).read_bytes()
        assert len(data) > 1000
        hashes[name] = hashlib.sha256(data).hexdigest()
    return dict(passed=True, ports=41, differences=differences,
                setup_slack_ns=setup, hold_slack_ns=hold,
                critical_drc=0, hashes=hashes,
                timing_scope="User-specified constraints; external asynchronous IO is not fully timed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("build", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.build)
    if args.output:
        args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
