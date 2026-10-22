"""Summarize saved bench evidence; never accesses or changes hardware."""
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODES = ["read", "set", "reset", "cycle", "column", "array",
         "wb_read", "wb_set", "wb_reset", "wb_cycle"]


def main():
    deployment = json.loads((ROOT / "evidence/deployment.json").read_text())
    assessment_path = ROOT / "evidence/mode_assessment.json"
    assessment = json.loads(assessment_path.read_text()) if assessment_path.exists() else {}
    jobs = []
    for path in (ROOT / "runs").glob("*.json"):
        job = json.loads(path.read_text(encoding="utf-8"))
        if "parameters" in job and "id" in job:
            jobs.append(job)
    jobs.sort(key=lambda j: datetime.fromisoformat(j["started"]))
    matrix = {}
    for mode in MODES:
        matching = [j for j in jobs if j["parameters"]["mode"] == mode
                    and j["state"] == "completed"]
        if not matching:
            matrix[mode] = {"executed": False}
            continue
        job = matching[-1]
        results = job["results"]
        wb = [r for r in results if r["kind"] == "wb"]
        scan = [r for r in results if r["kind"] == "scan"]
        matrix[mode] = dict(
            executed=True, job_id=job["id"], parameters=job["parameters"],
            started=job["started"],
            tested_on_current_image=bool(deployment.get("programmed_at")) and
                datetime.fromisoformat(job["started"]) >=
                datetime.fromisoformat(deployment["programmed_at"]),
            tested_on_current_wb_sequence=(
                datetime.fromisoformat(job["started"]) >=
                datetime.fromisoformat(deployment["control_updated_at"])
                if mode.startswith("wb_") and deployment.get("control_updated_at") else None),
            capture_count=len(results), clipped=any(r["clipped"] for r in scan),
            uart_transport_verified=all(r["transport_verified"] for r in wb) if wb else None,
            valid_column_tdc=all(r["matching_column"] for r in wb) if wb else None,
            trace_points=max((len(r.get("trace", [])) for r in scan), default=0),
            read_currents_uA=[
                {"operation": r["operation"], "set_path": r["channels"][2]["delta_current_ua"]}
                for r in scan if len(scan) <= 6
            ],
            tdc=[{k: r[k] for k in ("operation", "selected", "coarse", "fine", "extra", "matching_column")}
                 for r in wb],
        )
    report = dict(
        generated=datetime.now(timezone.utc).isoformat(),
        modes=matrix,
        cancellations=[{"id": j["id"], "captures": len(j["results"])}
                       for j in jobs if j["state"] == "cancelled"],
        checks=[{"id": j["id"], "state": j["state"], "status": j.get("status")}
                for j in jobs if j["parameters"]["mode"] == "check"],
        calibration="56 ohm shunts and nominal gain 7; reported current is active-minus-idle supply current.",
        limitation="A completed SET/RESET or valid TDC word alone does not certify a resistance state.",
        image=deployment.get("hashes", {}),
        programmed_at=deployment.get("programmed_at"),
        measurements=deployment.get("manual_measurements", {}),
        assessment=assessment,
    )
    (ROOT / "evidence/validation.json").write_text(json.dumps(report, indent=2))
    lines = [
        "SenseEval / KC705 GUI bench validation",
        "Generated: " + report["generated"],
        "GUI: http://127.0.0.1:8771/",
        "",
        "Hardware jobs were executed through the GUI HTTP API. The browser also",
        "exercised all ten preview modes, live read, RESET/readback, and Stop.",
        "Scan programming cell: r0/c0. Wishbone programming cell: r0/c31.",
        "Column and full-array tests performed reads only.",
        "",
        "Mode                 Captures   ADC clipping   Valid WB column/TDC   Current image",
    ]
    for mode, item in matrix.items():
        lines.append(f"{mode:20} {item.get('capture_count', 0):8}   "
                     f"{str(item.get('clipped')):12}   {str(item.get('valid_column_tdc')):19}   "
                     f"{item.get('tested_on_current_image')}")
        if item.get("job_id"):
            lines.append("  Evidence: runs/" + item["job_id"] + ".json")
        if mode.startswith("wb_"):
            lines.append("  Current reference WB transaction sequence: " +
                         str(item.get("tested_on_current_wb_sequence")))
        for item_current in item.get("read_currents_uA", []):
            lines.append(f"  {item_current['operation']}: SET/R10 delta "
                         f"{item_current['set_path']:.3f} uA nominal")
    lines += [
        "", "Waveform",
        "Real ADC samples, baseline/selected/return-to-idle. Default 134 points",
        "at 10 us intervals, decimated from 10 MSPS. Export trace includes all",
        "three shunt paths. This is not a full-rate oscilloscope capture.",
        "",
        "Measured behavior and remaining limits",
        *assessment.get("notes", [deployment.get("validation_note", "Assessment pending.")]),
        "",
        "Final image",
        f"FMC properties unchanged: {deployment.get('fmc_properties_unchanged')}.",
        f"Setup slack {deployment.get('setup_slack_ns')} ns; "
        f"hold slack {deployment.get('hold_slack_ns')} ns.",
        "Timing applies to user-specified constraints; external asynchronous IO is not fully timed.",
        "See current-image column above; earlier jobs remain evidence for their original images.",
        "Bitstream: " + deployment.get("hashes", {}).get("build/kc705_adc_capture.bit", "unrecorded"),
        "A VIO cache issue during reload was corrected by explicitly reasserting",
        "ADC/DAC enable=0 immediately after programming; the retry initialized",
        "successfully before GUI operations were reenabled.",
        "",
        "Software/FPGA checks",
        "Seven model tests; DOM contract for all ten modes; actual browser previews.",
        "RTL simulation covers protected DAC channels, SPI edge, scan packet order,",
        "ADC sums/trace, WB SE/TM ownership, DAC power mask, WB command/UART bank,",
        "abort and ADC fault containment.",
        "See io_audit*.json and build/timing_summary.rpt for image validation.",
        "",
        "Deployment and limits",
        "Fixed supply targets: VDDA1 3.0 V, VCCD2 1.8 V; FMC electrical constraints",
        "unchanged. No VADJ writes. DAC14/DAC15 protected from runtime operations.",
        "Jobs restore the scan read profile and hold CPU reset when communication",
        "allows cleanup. Cancel was tested, followed by an explicit FPGA check.",
        "Bias/supply targets are commanded values, not live DMM telemetry.",
        report["calibration"],
        report["limitation"],
        "",
        "Running GUI versus saved source",
        "Automatic approval review blocked a server restart ('blocked by policy').",
        "The running server has the real trace and all modes. Later server error",
        "reporting/quarantine changes and Python minimum-hold validation await a",
        "restart. The deployed Tcl runner independently enforces hold >=20 clocks;",
        "the browser minimum is also 0.01 ms. No blocked restart was retried.",
        "",
        "Raw job JSON, JSONL, logs and trace JSON remain under runs/.",
    ]
    (ROOT / "evidence/validation_report.txt").write_text("\n".join(lines) + "\n")
    print(json.dumps({"modes": {m: {"captures": v.get("capture_count"),
          "valid_wb": v.get("valid_column_tdc")} for m, v in matrix.items()}}))


if __name__ == "__main__":
    main()
