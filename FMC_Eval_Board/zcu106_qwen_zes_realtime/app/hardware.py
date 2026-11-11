"""Narrow client for the existing, validated SenseEval ZCU106 API."""

from __future__ import annotations

import json
import csv
import math
import os
import re
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class HardwareBusy(RuntimeError):
    pass


@dataclass(frozen=True)
class HardwareConfig:
    base_url: str = "http://127.0.0.1:8771"
    expected_revision: str = "fpga-array-scheduler-resetpath-v4.2"
    timeout_seconds: float = 5.0


class SenseEvalClient:
    """Use the old service as-is; never bypass its safety and recovery gates."""

    def __init__(self, config: HardwareConfig | None = None):
        self.config = config or HardwareConfig()

    def _request(self, path: str, body: dict | None = None, timeout: float | None = None) -> dict:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.config.base_url + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="GET" if data is None else "POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.config.timeout_seconds) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            try:
                reason = json.loads(exc.read()).get("error", str(exc))
            except (json.JSONDecodeError, AttributeError):
                reason = str(exc)
            raise RuntimeError(f"SenseEval rejected the request: {reason}") from exc
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"SenseEval is unavailable: {exc}") from exc

    def status(self, include_raw: bool = False) -> dict:
        state = self._request("/api/status")
        compatible = state.get("api_revision") == self.config.expected_revision
        deployment = state.get("deployment") or {}
        result = {
            "reachable": True,
            "compatible": compatible,
            "api_revision": state.get("api_revision"),
            "expected_revision": self.config.expected_revision,
            "target": state.get("target"),
            "busy": bool(state.get("busy")),
            "message": state.get("message"),
            "deployment_ready": bool(deployment.get("ready")),
        }
        if include_raw:
            result["_raw"] = state
        return result

    def safe_status(self) -> dict:
        try:
            return self.status()
        except RuntimeError as exc:
            return {"reachable": False, "compatible": False, "busy": False,
                    "deployment_ready": False, "error": str(exc)}

    def busy_check(self) -> dict:
        """One preflight check for direct tools; ignore legacy build hashes.

        The bitmap bitstream intentionally differs from the old SenseEval
        deployment.  Direct operations only need to know whether that service
        is already driving the shared hardware.
        """

        try:
            state = self._request("/api/status")
            return {"reachable": True, "busy": bool(state.get("busy")),
                    "port_open": True,
                    "message": state.get("message"),
                    "active_job_id": (state.get("job") or {}).get("id")}
        except RuntimeError as exc:
            from urllib.parse import urlparse
            parsed = urlparse(self.config.base_url)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or 80
            try:
                with socket.create_connection((host, port), timeout=0.5):
                    port_open = True
            except OSError:
                port_open = False
            return {"reachable": False, "port_open": port_open, "busy": False,
                    "error": str(exc)}

    def heatmap(self) -> dict:
        return self._request("/api/heatmap.json")

    def run_array_read(self, cancelled: Callable[[], bool], progress: Callable[[dict], None],
                       timeout_seconds: float = 900.0) -> dict:
        """Read all 1024 cells through the existing non-programming array mode."""

        status = self.status(include_raw=True)
        if not status["compatible"] or status.get("target") != "zcu106":
            raise RuntimeError("SenseEval ZCU106 API revision/target mismatch")
        if not status["deployment_ready"]:
            raise RuntimeError("SenseEval deployment is not ready")
        if status["busy"]:
            raise HardwareBusy("SenseEval already has a hardware job; parity read was not submitted")
        accepted = self._request("/api/run", {"mode": "array", "dry_run": False}, timeout=10)
        job_id = accepted["job_id"]
        progress({"state": "submitted", "job_id": job_id, "completed": 0, "total": 1024})
        deadline = time.monotonic() + timeout_seconds
        cancel_sent = False
        while time.monotonic() < deadline:
            state = self.status(include_raw=True)["_raw"]
            active = state.get("job") or {}
            jobs = {job.get("id"): job for job in state.get("jobs", [])}
            job = jobs.get(job_id) or (active if active.get("id") == job_id else None)
            completed = int((job or {}).get("result_count", 0))
            progress({"state": "running", "job_id": job_id, "completed": completed,
                      "total": 1024, "message": state.get("message", "Reading physical array")})
            if cancelled() and not cancel_sent and state.get("busy") and active.get("id") == job_id:
                self._request("/api/cancel", {}, timeout=10)
                cancel_sent = True
                progress({"state": "cancelling", "job_id": job_id,
                          "completed": completed, "total": 1024})
            if job and job.get("state") in ("completed", "failed", "cancelled"):
                if job["state"] != "completed":
                    raise RuntimeError(f"array read {job['state']}: {job.get('error') or 'no detail'}")
                cells = [cell for cell in self.heatmap().get("cells", []) if cell.get("job_id") == job_id]
                if len(cells) != 1024:
                    raise RuntimeError(f"array read completed but returned {len(cells)}/1024 fresh cells")
                return {"state": "completed", "job_id": job_id, "cells": cells}
            time.sleep(1.5)
        raise RuntimeError("array read timed out; inspect SenseEval before issuing another command")

    def run_sparse_row_probe(self, seed: int, cancelled: Callable[[], bool],
                             progress: Callable[[dict], None], timeout_seconds: float = 240.0) -> dict:
        """Run one physical 32-cell row through the existing FPGA MAC path.

        The submitted matrix is only a 32x32 shape descriptor because
        ``program_matrix`` is false.  Results come from the already-programmed
        physical array; no cell state is changed.
        """

        status = self.status(include_raw=True)
        if not status["compatible"] or status.get("target") != "zcu106":
            raise RuntimeError("SenseEval ZCU106 API revision/target mismatch")
        if not status["deployment_ready"]:
            raise RuntimeError("SenseEval deployment is not ready")
        if status["busy"]:
            raise HardwareBusy("SenseEval already has a hardware job; probe was not submitted")
        selected_row = seed % 32
        inputs = [0] * 32
        inputs[selected_row] = 1
        body = {
            "mode": "scan_mac",
            "weight_matrix": [[0] * 32 for _ in range(32)],
            "input_vector": inputs,
            "program_matrix": False,
            "dry_run": False,
        }
        accepted = self._request("/api/run", body, timeout=10)
        job_id = accepted["job_id"]
        progress({"state": "submitted", "job_id": job_id, "selected_row": selected_row,
                  "note": "Read-only 32-cell physical-row probe; submitted weights are not programmed."})
        deadline = time.monotonic() + timeout_seconds
        cancel_sent = False
        while time.monotonic() < deadline:
            state = self.status(include_raw=True)["_raw"]
            if cancelled() and not cancel_sent and state.get("busy") and state.get("job", {}).get("id") == job_id:
                self._request("/api/cancel", {}, timeout=10)
                cancel_sent = True
                progress({"state": "cancelling", "job_id": job_id})
            jobs = {job.get("id"): job for job in state.get("jobs", [])}
            job = jobs.get(job_id)
            if job and job.get("state") in ("completed", "failed", "cancelled"):
                outputs = sorted((row for row in state.get("history", [])
                                  if row.get("job_id") == job_id and row.get("kind") == "mac"),
                                 key=lambda row: row.get("col", -1))
                result = {
                    "state": job["state"], "job_id": job_id, "selected_row": selected_row,
                    "physical_array": True, "programmed_by_this_request": False,
                    "outputs": [{"column": row["col"],
                                 "nominal_current_dot_ua": row["nominal_current_dot_ua"],
                                 "raw_accumulator": row["raw_accumulator"]} for row in outputs],
                    "error": job.get("error"),
                }
                if job["state"] != "completed":
                    raise RuntimeError(f"hardware probe {job['state']}: {job.get('error') or 'no detail'}")
                return result
            progress({"state": "running", "job_id": job_id,
                      "message": state.get("message", "Hardware probe running")})
            time.sleep(1.5)
        raise RuntimeError("hardware probe timed out; inspect SenseEval before issuing another command")


class _HardwareFileLease:
    """Nonblocking, process-wide advisory lease for this project's direct tools."""

    def __init__(self, path: Path):
        self.path = path
        self.stream = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("a+b")
        self.stream.seek(0, os.SEEK_END)
        if self.stream.tell() == 0:
            self.stream.write(b"\0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            self.stream.close()
            self.stream = None
            raise HardwareBusy("another process owns the ZCU106 direct-hardware lease") from exc
        self.stream.seek(0)
        self.stream.truncate()
        self.stream.write(f"pid={os.getpid()} acquired_unix={time.time():.3f}\n".encode("ascii"))
        self.stream.flush()
        return self

    def __exit__(self, _kind, _value, _traceback):
        if self.stream is None:
            return
        try:
            self.stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        finally:
            self.stream.close()
            self.stream = None


class BitmapToolRunner:
    """Launch the new-folder bitmap Tcl tools without consulting old hashes."""

    DEFAULT_NO_PROGRESS_TIMEOUT_SECONDS = 300.0

    def __init__(self, app_dir: Path, no_progress_timeout_seconds: float | None = None):
        self.app_dir = app_dir.resolve()
        self.project_root = self.app_dir.parent
        self.tools = self.project_root / "fpga" / "tools"
        self.vivado = os.environ.get("BITMAP_VIVADO", "C:/Xilinx/Vivado/2022.2/bin/vivado.bat")
        self.exclusive_mode = os.environ.get("RERAM_EXCLUSIVE_HARDWARE", "").strip().lower() in {
            "1", "true", "yes", "on"
        }
        self.lease_file = self.project_root / "runtime" / "zcu106_hardware.lease"
        configured_timeout = (no_progress_timeout_seconds if no_progress_timeout_seconds is not None
                              else os.environ.get("BITMAP_NO_PROGRESS_TIMEOUT_SECONDS",
                                                  self.DEFAULT_NO_PROGRESS_TIMEOUT_SECONDS))
        try:
            self.no_progress_timeout_seconds = float(configured_timeout)
        except (TypeError, ValueError) as exc:
            raise ValueError("BITMAP_NO_PROGRESS_TIMEOUT_SECONDS must be a positive number") from exc
        if (not math.isfinite(self.no_progress_timeout_seconds) or
                self.no_progress_timeout_seconds <= 0):
            raise ValueError("BITMAP_NO_PROGRESS_TIMEOUT_SECONDS must be a positive finite number")

    def capabilities(self) -> dict:
        program = self.tools / "bitmap_program.tcl"
        read = self.tools / "bitmap_read.tcl"
        probes = self.project_root / "fpga" / "zcu106_cell_control" / "build" / "zcu106_adc_capture.ltx"
        tools_ready = (program.is_file() and read.is_file() and
                       Path(self.vivado).is_file() and probes.is_file())
        return {
            "configured": tools_ready and self.exclusive_mode,
            "tools_ready": tools_ready,
            "exclusive_mode": self.exclusive_mode,
            "exclusive_requirement": (
                "Launch app/run.ps1 -ExclusiveHardware only after the legacy port 8771 service is stopped."),
            "vivado": self.vivado,
            "program_tool": str(program), "program_tool_present": program.is_file(),
            "read_tool": str(read), "read_tool_present": read.is_file(),
            "probes_file": str(probes), "probes_file_present": probes.is_file(),
            "requires_bitmap_capable_bitstream": True,
            "legacy_deployment_hash_used": False,
            "no_progress_timeout_seconds": self.no_progress_timeout_seconds,
        }

    @staticmethod
    def _terminate_process_tree(process: subprocess.Popen) -> str:
        """Forcibly stop only ``process`` and the descendants it launched."""

        if process.poll() is not None:
            return f"pid {process.pid} had already exited"
        if os.name == "nt":
            # /T is deliberately rooted at the Popen PID.  Never use an image
            # name here: another Vivado session may belong to the user.
            completed = subprocess.run(
                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", timeout=20,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            detail = completed.stdout.strip()
            if completed.returncode and process.poll() is None:
                # The fallback remains scoped to the exact Popen handle.  The
                # failed taskkill result is retained in the watchdog error.
                process.kill()
            try:
                code = process.wait(timeout=20)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    f"taskkill did not stop Vivado pid {process.pid}: {detail or 'no detail'}") from exc
            return (f"taskkill /PID {process.pid} /T /F exited {completed.returncode}; "
                    f"Vivado exit={code}; {detail or 'no taskkill output'}")

        # The runner starts a dedicated session on POSIX, so this group is
        # likewise limited to the launched Vivado tree.
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            code = process.wait(timeout=20)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"process group {process.pid} did not stop") from exc
        return f"killed process group {process.pid}; Vivado exit={code}"

    @staticmethod
    def row_words(bits: list[int]) -> list[int]:
        if len(bits) != 576 or any(bit not in (0, 1) for bit in bits):
            raise ValueError("exactly 576 binary parity bits are required")
        words = [0] * 32
        for index, bit in enumerate(bits):
            if bit:
                words[index >> 5] |= 1 << (index & 31)
        return words

    @staticmethod
    def _read_csv(path: Path) -> list[dict]:
        with path.open(newline="", encoding="utf-8") as stream:
            rows = []
            for row in csv.DictReader(stream):
                rows.append({
                    "index": int(row.get("physical_index", row.get("index", "0"))),
                    "row": int(row["row"]), "col": int(row.get("column", row.get("col", "0"))),
                    "requested_bit": int(row.get("requested_bit", "0")) if row.get("requested_bit") not in (None, "") else None,
                    "pass": bool(int(row.get("pass", "1"))),
                    "pulses": int(row.get("pulses", "0")),
                    "clipped": bool(int(row.get("clipped", "0"))),
                    "current_ua": float(row.get("current_uA", row.get("current_ua", "nan"))),
                })
        return rows

    def _run(self, script: Path, arguments: list[str], progress: Callable[[dict], None],
             progress_pattern: re.Pattern, done_prefix: str) -> tuple[list[str], int]:
        if not self.exclusive_mode:
            raise HardwareBusy(
                "direct FPGA access is disabled; stop the legacy service and relaunch with -ExclusiveHardware")
        if not script.is_file():
            raise RuntimeError(f"required bitmap tool is missing: {script}")
        if not Path(self.vivado).is_file():
            raise RuntimeError(f"Vivado executable not found: {self.vivado}")
        probes = self.project_root / "fpga" / "zcu106_cell_control" / "build" / "zcu106_adc_capture.ltx"
        if not probes.is_file():
            raise RuntimeError(
                f"bitmap probe file is missing: {probes}. Build and deploy the bitmap-capable bitstream first")
        command = [self.vivado, "-mode", "batch", "-source", str(script), "-tclargs", *arguments]
        with _HardwareFileLease(self.lease_file):
            # Vivado launches hw_server as a descendant on Windows.  That
            # descendant can inherit a stdout pipe and keep it open after the
            # Vivado process exits, leaving a Python iterator blocked forever
            # even though all output artifacts are complete.  A regular file
            # preserves streaming progress without depending on pipe EOF.
            capture_path = self.project_root / "runtime" / (
                f"{script.stem}-{os.getpid()}-{time.time_ns()}.log")
            capture_path.parent.mkdir(parents=True, exist_ok=True)
            lines, done_seen = [], False
            timed_out = False
            idle_seconds = 0.0
            termination_detail = ""

            def consume(stream) -> bool:
                nonlocal done_seen
                saw_output = False
                while True:
                    line = stream.readline()
                    if not line:
                        break
                    saw_output = True
                    text = line.rstrip()
                    lines.append(text)
                    match = progress_pattern.search(text)
                    if match:
                        progress({"state": "running", **{
                            key: int(value) for key, value in match.groupdict().items()}})
                    if text.startswith(done_prefix):
                        done_seen = True
                    if len(lines) > 300:
                        lines.pop(0)
                return saw_output

            try:
                with capture_path.open("w", encoding="utf-8", errors="replace") as sink:
                    popen_options = {
                        "cwd": self.tools,
                        "stdout": sink,
                        "stderr": subprocess.STDOUT,
                    }
                    if os.name == "nt":
                        popen_options["creationflags"] = getattr(
                            subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                    else:
                        popen_options["start_new_session"] = True
                    process = subprocess.Popen(command, **popen_options)
                    last_activity = time.monotonic()
                    with capture_path.open("r", encoding="utf-8", errors="replace") as source:
                        while process.poll() is None:
                            if consume(source):
                                last_activity = time.monotonic()
                            idle_seconds = time.monotonic() - last_activity
                            if idle_seconds >= self.no_progress_timeout_seconds:
                                timed_out = True
                                try:
                                    termination_detail = self._terminate_process_tree(process)
                                except Exception as exc:  # retain evidence even if OS termination reports trouble
                                    termination_detail = f"process-tree termination error: {exc}"
                                    if process.poll() is None:
                                        process.kill()
                                        process.wait(timeout=20)
                                break
                            time.sleep(0.1)
                        code = process.wait(timeout=20) if timed_out else process.wait()
                        consume(source)
            except Exception:
                # A launch failure has no useful Vivado evidence.  Runtime or
                # watchdog failures retain the complete capture below.
                if "process" not in locals():
                    try:
                        capture_path.unlink()
                    except OSError:
                        pass
                raise
        if timed_out:
            detail = "\n".join(lines[-12:]) or "(no Vivado output captured)"
            raise RuntimeError(
                "bitmap tool no-progress watchdog expired after "
                f"{idle_seconds:.1f}s (limit {self.no_progress_timeout_seconds:g}s). "
                f"{termination_detail}. No hardware-restore Vivado session was started; "
                "confirm recovery state before another hardware command.\n"
                f"Evidence log: {capture_path}\nLast output:\n{detail}")
        if code or not done_seen:
            detail = "\n".join(lines[-12:])
            hint = (" The bitmap-capable bitstream is required before this tool can run."
                    if "Bitmap-capable" in detail or "signature" in detail.lower() else "")
            raise RuntimeError(
                f"bitmap tool failed (exit {code}).{hint}\n"
                f"Evidence log: {capture_path}\n{detail}")
        try:
            capture_path.unlink()
        except OSError:
            pass
        return lines, code

    def program(self, parity_bits: list[int], job_dir: Path, progress: Callable[[dict], None]) -> dict:
        job_dir.mkdir(parents=True, exist_ok=False)
        words = self.row_words(parity_bits)
        bitmap = job_dir / "parity_bitmap.hex"
        bitmap.write_text("\n".join(f"{word:08X}" for word in words) + "\n", encoding="ascii")
        output_prefix = job_dir / "program_readback"
        pattern = re.compile(r"BITMAP_PROGRESS completed=(?P<completed>\d+) failures=(?P<failures>\d+) row=(?P<row>\d+) column=(?P<col>\d+) target=(?P<target>\d+)")
        self._run(self.tools / "bitmap_program.tcl",
                  [str(bitmap), str(output_prefix), "0", "576", "2400", "2"],
                  progress, pattern, "BITMAP_DONE ")
        manifest_path = Path(f"{output_prefix}.manifest.json")
        csv_path = Path(f"{output_prefix}.csv")
        if not manifest_path.is_file() or not csv_path.is_file():
            raise RuntimeError("bitmap program completed without manifest/CSV evidence")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        rows = self._read_csv(csv_path)
        if len(rows) != 576:
            raise RuntimeError(f"bitmap program returned {len(rows)}/576 physical results")
        return {"state": "completed", "manifest": manifest, "rows": rows,
                "bitmap_file": str(bitmap), "csv_file": str(csv_path),
                "programmed_range": [0, 575], "spares_programmed": False}

    def read(self, job_dir: Path, progress: Callable[[dict], None]) -> dict:
        job_dir.mkdir(parents=True, exist_ok=False)
        output_prefix = job_dir / "physical_readback"
        pattern = re.compile(r"READ_PROGRESS completed=(?P<completed>\d+) count=(?P<total>\d+) row=(?P<row>\d+) column=(?P<col>\d+) lrs=(?P<lrs>\d+) hrs=(?P<hrs>\d+)")
        self._run(self.tools / "bitmap_read.tcl", [str(output_prefix), "0", "1024"],
                  progress, pattern, "READ_DONE ")
        json_path = Path(f"{output_prefix}.json")
        csv_path = Path(f"{output_prefix}.csv")
        if not json_path.is_file() or not csv_path.is_file():
            raise RuntimeError("bitmap read completed without JSON/CSV evidence")
        summary = json.loads(json_path.read_text(encoding="utf-8"))
        rows = self._read_csv(csv_path)
        if len(rows) != 1024:
            raise RuntimeError(f"bitmap read returned {len(rows)}/1024 physical cells")
        return {"state": "completed", "summary": {k: v for k, v in summary.items() if k != "cells"},
                "rows": rows, "csv_file": str(csv_path), "json_file": str(json_path)}
