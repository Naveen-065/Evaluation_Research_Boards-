"""Streaming inference, live tensor protection, and asynchronous ReRAM readback."""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from faults import PROTECTED_BLOCK_BYTES, ZesTcpClient, bit_error_count, inject_faults
from hardware import BitmapToolRunner, HardwareBusy, HardwareConfig, SenseEvalClient
from runtimes import discover_runtime


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TensorProtection:
    """Serialize access to one live 1 KiB runtime tensor view."""

    def __init__(self, runtime, board_client: ZesTcpClient | None, threshold: int = 3):
        self.runtime = runtime
        self.board_client = board_client
        self.threshold = self._validated_threshold(threshold)
        self.lock = threading.RLock()
        self.baseline: bytes | None = None
        self.parity: bytes | None = None
        self.edac_mode: str | None = None
        self.tensor: dict[str, Any] | None = None
        self.last_injection: dict[str, Any] | None = None
        self.last_check: dict[str, Any] | None = None

    @staticmethod
    def _reference_encode(data: bytes) -> bytes:
        # Fixed 72-byte shape matches the board transport, but this is clearly
        # a host reference tag, not the proprietary ZES parity algorithm.
        return hashlib.shake_256(b"reference-edac-tag-v1" + data).digest(72)

    @staticmethod
    def _validated_threshold(threshold: int) -> int:
        if (not isinstance(threshold, int) or isinstance(threshold, bool) or
                not 1 <= threshold <= 8192):
            raise ValueError("threshold must be an integer from 1 to 8192")
        return threshold

    def _current(self) -> bytes:
        block = self.runtime.read_tensor_block()
        if len(block) != PROTECTED_BLOCK_BYTES:
            raise RuntimeError("runtime returned a tensor view with the wrong size")
        return block

    def public(self) -> dict[str, Any]:
        with self.lock:
            current = self._current() if self.baseline is not None else None
            return {
                "initialized": self.baseline is not None,
                "runtime": self.runtime.info.public(),
                "tensor": self.tensor,
                "edac_mode": self.edac_mode,
                "baseline_sha256": sha256(self.baseline) if self.baseline is not None else None,
                "current_sha256": sha256(current) if current is not None else None,
                "sha_verified": current == self.baseline if current is not None else None,
                "parity_sha256": sha256(self.parity) if self.parity is not None else None,
                "parity_bytes": len(self.parity) if self.parity is not None else 0,
                "parity_storage": "host-memory encoded copy; not physical ReRAM readback",
                "last_injection": self.last_injection,
                "last_check": self.last_check,
                "mutation_scope": "live in-memory tensor view only; model files are never written",
            }

    def initialize(self, edac_mode: str) -> dict[str, Any]:
        if edac_mode not in ("reference", "board"):
            raise ValueError("edac_mode must be reference or board")
        if edac_mode == "board" and self.board_client is None:
            raise ValueError("board EDAC requires ZES_EDAC_HOST")
        with self.lock, self.runtime.operation_lock:
            baseline = self._current()
            parity = (self.board_client.encode(baseline) if edac_mode == "board"
                      else self._reference_encode(baseline))
            if len(parity) != 72:
                raise RuntimeError("EDAC encoder did not return 72 parity bytes")
            self.baseline, self.parity, self.edac_mode = baseline, parity, edac_mode
            self.tensor = self.runtime.tensor_info()
            self.last_injection = None
            self.last_check = None
            return self.public()

    def inject(self, error_percent: float, seed: int) -> dict[str, Any]:
        with self.lock, self.runtime.operation_lock:
            if self.baseline is None:
                raise ValueError("initialize protection before injecting errors")
            injection = inject_faults(self.baseline, error_percent, seed)
            self.runtime.write_tensor_block(injection.corrupted)
            live = self._current()
            if live != injection.corrupted:
                raise RuntimeError("live tensor write verification failed")
            self.last_injection = injection.public() | {
                "current_sha256": sha256(live),
                "real_model_tensor": bool(self.tensor and self.tensor.get("real_model_tensor")),
            }
            self.last_check = None
            return self.public()

    def _evaluate(self, threshold: int, parity: bytes | None = None,
                  parity_source: str = "host-encoded-copy") -> tuple[dict[str, Any], bytes]:
        if self.baseline is None or self.parity is None or self.edac_mode is None:
            raise ValueError("initialize protection before checking or repairing")
        threshold = self._validated_threshold(threshold)
        active_parity = self.parity if parity is None else parity
        if len(active_parity) != 72:
            raise ValueError("active parity must contain exactly 72 bytes")
        current = self._current()
        bit_errors = bit_error_count(self.baseline, current)
        if self.edac_mode == "board":
            decoder, proposed = self.board_client.check_repair(current, active_parity, threshold)
            backend = "board-zes1"
        else:
            # Transparent host reference: one-bit correction only.
            decoder = 0 if bit_errors == 0 else (1 if bit_errors == 1 else 2)
            proposed = self.baseline if decoder == 1 else current
            backend = "reference-single-bit"
        report = {
            "backend": backend, "decoder_result": decoder,
            "outcome": {0: "no-error", 1: "detected-correctable", 2: "detected-uncorrectable"}[decoder],
            "threshold": threshold, "observed_bit_errors_vs_sha_baseline": bit_errors,
            "before_sha256": sha256(current), "proposed_sha256": sha256(proposed),
            "proposed_matches_baseline": proposed == self.baseline,
            "parity_source": parity_source,
            "parity_sha256": sha256(active_parity),
            "physical_parity_used": parity_source == "physical-readback-sha-verified",
            "live_tensor_mutated": False,
        }
        return report, proposed

    def check(self, threshold: int | None = None, parity: bytes | None = None,
              parity_source: str = "host-encoded-copy") -> dict[str, Any]:
        with self.lock, self.runtime.operation_lock:
            report, _ = self._evaluate(self.threshold if threshold is None else threshold,
                                       parity, parity_source)
            self.last_check = report
            return self.public()

    def repair(self, threshold: int | None = None, parity: bytes | None = None,
               parity_source: str = "host-encoded-copy") -> dict[str, Any]:
        with self.lock, self.runtime.operation_lock:
            report, proposed = self._evaluate(self.threshold if threshold is None else threshold,
                                              parity, parity_source)
            # Decoder result 2 is explicitly not repairable. Never overwrite
            # the live tensor with an unverified candidate.
            if report["decoder_result"] in (0, 1) and report["proposed_matches_baseline"]:
                self.runtime.write_tensor_block(proposed)
                verified = self._current() == self.baseline
                report["live_tensor_mutated"] = report["decoder_result"] == 1
                report["repair_sha_verified"] = verified
                if not verified:
                    raise RuntimeError("repair write completed but baseline SHA verification failed")
            else:
                report["repair_sha_verified"] = False
            self.last_check = report
            return self.public()

    def parity_bits(self) -> list[int] | None:
        with self.lock:
            if self.parity is None:
                return None
            return [(byte >> bit) & 1 for byte in self.parity for bit in range(8)]

    def parity_snapshot(self) -> dict[str, Any]:
        with self.lock:
            if self.parity is None:
                raise ValueError("initialize/protect parity first")
            parity = bytes(self.parity)
            bits = [(byte >> bit) & 1 for byte in parity for bit in range(8)]
            return {"bytes": parity, "bits": bits, "sha256": sha256(parity),
                    "byte_count": len(parity), "bit_order": "lsb0"}


def parity_layout(bits: list[int] | None) -> list[dict[str, Any]]:
    """Map the encoder's exact 576 parity bits to physical cells 0..575."""

    layout = []
    for index in range(1024):
        used = index < 576
        logical = bits[index] if bits is not None and used else None
        layout.append({"index": index, "row": index // 32, "col": index % 32,
                       "role": "encoded-parity" if used else "spare", "logical_bit": logical})
    return layout


@dataclass
class Session:
    id: str
    request: dict[str, Any]
    created: str = field(default_factory=now)
    state: str = "running"
    events: list[dict[str, Any]] = field(default_factory=list)
    output: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    hardware: dict[str, Any] = field(default_factory=lambda: {"state": "off"})
    error: str | None = None
    finished: str | None = None
    pending_parts: int = 1
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    condition: threading.Condition = field(default_factory=threading.Condition, repr=False)

    def emit(self, event_type: str, data: dict[str, Any]) -> None:
        with self.condition:
            self.events.append({"id": len(self.events) + 1, "type": event_type,
                                "time": now(), "data": data})
            self.condition.notify_all()

    def public(self, include_events: bool = False) -> dict:
        with self.condition:
            result = {"id": self.id, "request": self.request, "created": self.created,
                      "state": self.state, "output": self.output, "metrics": self.metrics,
                      "hardware": self.hardware, "error": self.error, "finished": self.finished,
                      "event_count": len(self.events)}
            if include_events:
                result["events"] = list(self.events)
            return result


class InferenceService:
    def __init__(self, runs_dir: Path, hardware: SenseEvalClient | None = None):
        self.runs_dir = runs_dir
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.hardware_client = hardware or SenseEvalClient(HardwareConfig(
            base_url=os.environ.get("SENSEEVAL_URL", "http://127.0.0.1:8771").rstrip("/")))
        self.bitmap_tool = BitmapToolRunner(Path(__file__).resolve().parent)
        self.runtime = discover_runtime()
        host = os.environ.get("ZES_EDAC_HOST", "").strip()
        port = int(os.environ.get("ZES_EDAC_PORT", "9106"))
        threshold = int(os.environ.get("ZES_EDAC_THRESHOLD", "3"))
        self.board_client = ZesTcpClient(host, port) if host else None
        self.protection = TensorProtection(self.runtime, self.board_client, threshold)
        self.sessions: dict[str, Session] = {}
        self.lock = threading.RLock()
        self.hardware_gate = threading.Lock()
        self.gate_state_lock = threading.Lock()
        self.hardware_gate_owner: str | None = None
        self.map_lock = threading.RLock()
        self.map_cancel = threading.Event()
        self.bitmap_job: dict[str, Any] = {"state": "idle"}
        self.map_state: dict[str, Any] = {
            "state": "idle", "source": None, "completed": 0, "total": 1024,
            "cells": [], "message": "Initialize parity, then acquire hardware readback.",
        }
        self.physical_parity: bytes | None = None
        self.physical_parity_job_id: str | None = None
        raw_failed = os.environ.get("RERAM_FAILED_CELLS", "")
        self.failed_cells = set()
        for token in raw_failed.split(";"):
            if not token.strip():
                continue
            try:
                row, col = (int(value) for value in token.split(",", 1))
                if 0 <= row < 32 and 0 <= col < 32:
                    self.failed_cells.add((row, col))
            except ValueError:
                pass
        self._restore_latest_physical_map()

    def _acquire_hardware_gate(self, owner: str) -> None:
        if not self.hardware_gate.acquire(blocking=False):
            with self.gate_state_lock:
                active = self.hardware_gate_owner or "another operation"
            raise HardwareBusy(f"hardware operation '{active}' is already active")
        with self.gate_state_lock:
            self.hardware_gate_owner = owner

    def _release_hardware_gate(self, owner: str) -> None:
        with self.gate_state_lock:
            if self.hardware_gate_owner != owner:
                raise RuntimeError(f"hardware gate ownership mismatch: {owner}")
            self.hardware_gate_owner = None
        self.hardware_gate.release()

    def initialize_protection(self, edac_mode: str) -> dict[str, Any]:
        owner = "initialize-parity"
        self._acquire_hardware_gate(owner)
        try:
            result = self.protection.initialize(edac_mode)
            snapshot = self.protection.parity_snapshot()
            with self.map_lock:
                prior = json.loads(json.dumps(self.map_state))
            retain = bool(
                prior.get("state") == "completed" and
                prior.get("source") == "bitmap-direct-readback" and
                prior.get("encoded_parity_sha256") == snapshot["sha256"] and
                len(prior.get("cells", [])) == 1024
            )
            if retain:
                reads = [{"row": cell["row"], "col": cell["col"],
                          "current_ua": cell.get("current_ua"),
                          "pass": cell.get("classification") != "failed"}
                         for cell in prior["cells"]]
                job_id = prior.get("readback_job_id")
                cells = self._classify_map(reads, "bitmap-direct-readback", job_id,
                                           snapshot["bits"])
                quality = self._map_quality(cells)
                measured = self._reconstruct_parity(cells)
                measured_sha = sha256(measured) if measured is not None else None
                sha_verified = measured_sha == snapshot["sha256"] if measured_sha else False
                usable = bool(sha_verified and not quality["parity_failed"] and
                              not quality["unknown"])
                with self.map_lock:
                    self.physical_parity = measured
                    self.physical_parity_job_id = job_id if measured is not None else None
                    self.bitmap_job = {"state": "idle"}
                    self.map_state = prior | {
                        "cells": cells, "restored_historical": False, **quality,
                        "physical_parity": {
                            "available": measured is not None,
                            "sha256": measured_sha,
                            "expected_sha256": snapshot["sha256"],
                            "sha_verified": sha_verified,
                            "usable_for_check_repair": usable,
                            "readback_job_id": job_id,
                        },
                        "message": ("Retained the last complete physical readback because "
                                    "its encoded parity SHA exactly matches this live tensor."),
                    }
                return result
            cells = [cell | {"classification": ("spare" if cell["role"] == "spare" else "unknown"),
                             "observed_bit": None,
                             "current_ua": None, "threshold_ua": 34.2563054,
                             "readback_job_id": None, "source": None}
                     for cell in parity_layout(snapshot["bits"])]
            with self.map_lock:
                self.physical_parity = None
                self.physical_parity_job_id = None
                self.bitmap_job = {"state": "idle"}
                self.map_state = {
                    "state": "idle", "source": None, "simulation": False,
                    "completed": 0, "total": 1024, "cells": cells,
                    "encoded_parity_sha256": snapshot["sha256"],
                    "physical_parity": {"available": False, "sha_verified": False},
                    "message": "Parity changed; previous physical readback was invalidated.",
                }
            return result
        finally:
            self._release_hardware_gate(owner)

    def _selected_parity(self, parity_source: str) -> tuple[bytes | None, str]:
        if parity_source == "host":
            return None, "host-encoded-copy"
        if parity_source != "physical":
            raise ValueError("parity_source must be host or physical")
        snapshot = self.protection.parity_snapshot()
        with self.map_lock:
            measured = bytes(self.physical_parity) if self.physical_parity is not None else None
            job_id = self.physical_parity_job_id
            map_state = self.map_state.get("state")
            source = self.map_state.get("source")
            usable = bool((self.map_state.get("physical_parity") or {}).get(
                "usable_for_check_repair"))
        if measured is None or map_state != "completed" or source != "bitmap-direct-readback":
            raise ValueError("physical parity requires one complete non-simulated 1024-cell readback")
        if sha256(measured) != snapshot["sha256"]:
            raise ValueError("physical parity SHA does not match the encoded parity; check/repair was blocked")
        if not usable:
            raise ValueError("physical parity readback contains failed or unknown cells; check/repair was blocked")
        if not job_id:
            raise ValueError("physical parity readback has no hardware evidence job ID")
        return measured, "physical-readback-sha-verified"

    def check_protection(self, threshold: int | None, parity_source: str) -> dict[str, Any]:
        owner = "edac-check"
        self._acquire_hardware_gate(owner)
        try:
            parity, source = self._selected_parity(parity_source)
            return self.protection.check(threshold, parity, source)
        finally:
            self._release_hardware_gate(owner)

    def repair_protection(self, threshold: int | None, parity_source: str) -> dict[str, Any]:
        owner = "edac-repair"
        self._acquire_hardware_gate(owner)
        try:
            parity, source = self._selected_parity(parity_source)
            return self.protection.repair(threshold, parity, source)
        finally:
            self._release_hardware_gate(owner)

    def capabilities(self) -> dict:
        board = self.board_client.safe_info() if self.board_client else {
            "available": False, "protocol": "ZES1/v1", "port": 9106,
            "error": "Set ZES_EDAC_HOST to the isolated ZCU106 Ethernet address."}
        return {
            "runtime": self.runtime.info.public(),
            "protection": self.protection.public(),
            "fault_model": {
                "unit": "bit errors in one live protected 1 KiB tensor view",
                "block_bytes": 1024, "block_bits": 8192,
                "one_bit_percent": 100 / 8192,
                "model_file_mutation": False,
                "live_tensor_mutation": self.runtime.info.real_model,
            },
            "edac_modes": {
                "reference": {"available": True, "real_board": False,
                              "note": "transparent single-bit correction mock"},
                "board": {"available": bool(board.get("available")), "real_board": True,
                          "info": board},
            },
            "hardware": self.hardware_summary(),
            "hardware_modes": {
                "off": "No FPGA command.",
                "probe": "Read-only 32-cell physical-row MAC probe, asynchronous and potentially slow.",
            },
        }

    def hardware_summary(self) -> dict[str, Any]:
        """Report direct-tool state without repeatedly querying old hashes."""

        with self.map_lock:
            activity = {
                "bitmap_job_state": self.bitmap_job.get("state", "idle"),
                "map_state": self.map_state.get("state", "idle"),
            }
        with self.gate_state_lock:
            activity["operation_gate"] = self.hardware_gate_owner or "idle"
        return self.bitmap_tool.capabilities() | activity | {
            "senseeval_url": self.hardware_client.config.base_url,
            "senseeval_busy_check": "deferred until a hardware action starts",
        }

    @staticmethod
    def validate_request(body: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise ValueError("JSON object required")
        allowed = {"prompt", "seed", "hardware_mode", "max_new_tokens"}
        if set(body) - allowed:
            raise ValueError("unknown request fields")
        prompt = body.get("prompt", "")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 8000:
            raise ValueError("prompt must contain 1–8000 characters")
        seed = body.get("seed", 20261023)
        if not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed <= 0xFFFFFFFF:
            raise ValueError("seed must be an integer from 0 to 4294967295")
        hardware_mode = body.get("hardware_mode", "off")
        if hardware_mode not in ("off", "probe"):
            raise ValueError("hardware_mode must be off or probe")
        max_new_tokens = body.get("max_new_tokens", 128)
        if not isinstance(max_new_tokens, int) or isinstance(max_new_tokens, bool) or not 1 <= max_new_tokens <= 256:
            raise ValueError("max_new_tokens must be an integer from 1 to 256")
        return {"prompt": prompt.strip(), "seed": seed, "hardware_mode": hardware_mode,
                "max_new_tokens": max_new_tokens}

    def start(self, body: dict[str, Any]) -> Session:
        request = self.validate_request(body)
        session = Session(uuid.uuid4().hex, request,
                          pending_parts=2 if request["hardware_mode"] == "probe" else 1)
        with self.lock:
            self.sessions[session.id] = session
        session.emit("session", {"session_id": session.id, "runtime": self.runtime.info.public(),
                                 "protection": self.protection.public()})
        threading.Thread(target=self._run_inference, args=(session,), daemon=True).start()
        if request["hardware_mode"] == "probe":
            session.hardware = {"state": "starting"}
            threading.Thread(target=self._run_hardware, args=(session,), daemon=True).start()
        return session

    def get(self, ident: str) -> Session:
        try:
            uuid.UUID(hex=ident)
        except ValueError as exc:
            raise KeyError("invalid session ID") from exc
        with self.lock:
            if ident not in self.sessions:
                raise KeyError("session not found")
            return self.sessions[ident]

    def cancel(self, ident: str) -> Session:
        session = self.get(ident)
        session.cancel.set()
        session.emit("cancelling", {"message": "Cancellation requested."})
        return session

    def list_runs(self) -> list[dict]:
        with self.lock:
            live = [session.public(False) for session in self.sessions.values()]
        saved, live_ids = [], {item["id"] for item in live}
        for path in sorted(self.runs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
            if path.stem in live_ids:
                continue
            try:
                saved.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                pass
        return sorted(live + saved, key=lambda item: item.get("created", ""), reverse=True)[:50]

    def parity_map(self) -> dict[str, Any]:
        with self.map_lock:
            return json.loads(json.dumps(self.map_state | {"bitmap_job": self.bitmap_job}))

    def _restore_latest_physical_map(self) -> None:
        """Restore the newest complete hardware read as historical evidence.

        The live tensor is intentionally not initialized here.  A restored map
        remains ineligible for EDAC until initialize_protection derives the
        exact same encoded parity SHA in the current process.
        """

        root = self.runs_dir / "bitmap"
        if not root.is_dir():
            return
        candidates = sorted(root.glob("*/physical_readback.json"),
                            key=lambda path: path.stat().st_mtime, reverse=True)
        for path in candidates:
            try:
                ident = path.parent.name
                snapshot_path = root / f"{ident}.parity_snapshot.json"
                raw = json.loads(path.read_text(encoding="utf-8"))
                snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
                bits = snapshot.get("bits")
                encoded = bytes.fromhex(snapshot.get("bytes_hex", ""))
                if (raw.get("protocol") != "ZCU106_BITMAP_READ_V1" or
                        not isinstance(bits, list) or len(bits) != 576 or
                        any(bit not in (0, 1) for bit in bits) or
                        len(encoded) != 72 or sha256(encoded) != snapshot.get("sha256")):
                    raise ValueError("invalid persisted parity/readback identity")

                normalized = []
                seen = set()
                for entry in raw.get("cells", []):
                    index = int(entry["physical_index"])
                    row, col = int(entry["row"]), int(entry["column"])
                    current = float(entry["current_uA"])
                    if (index in seen or index != row * 32 + col or
                            not 0 <= index < 1024 or not math.isfinite(current)):
                        raise ValueError("invalid persisted physical coordinate")
                    seen.add(index)
                    normalized.append({"index": index, "row": row, "col": col,
                                       "current_ua": current, "pass": True})
                if seen != set(range(1024)):
                    raise ValueError("persisted readback is not one complete 1Kbit map")

                cells = self._classify_map(normalized, "bitmap-direct-readback", ident, bits)
                quality = self._map_quality(cells)
                measured = self._reconstruct_parity(cells)
                measured_sha = sha256(measured) if measured is not None else None
                expected_sha = snapshot["sha256"]
                self.physical_parity = None
                self.physical_parity_job_id = None
                self.map_state = {
                    "id": ident, "state": "completed",
                    "source": "bitmap-direct-readback", "simulation": False,
                    "completed": 1024, "total": 1024, "cells": cells,
                    "readback_job_id": ident, "encoded_parity_sha256": expected_sha,
                    "restored_historical": True, **quality,
                    "evidence": {key: value for key, value in raw.items() if key != "cells"},
                    "physical_parity": {
                        "available": measured is not None,
                        "sha256": measured_sha, "expected_sha256": expected_sha,
                        "sha_verified": measured_sha == expected_sha if measured_sha else False,
                        "usable_for_check_repair": False,
                        "readback_job_id": ident,
                        "reason": "historical readback is not bound to the current live tensor",
                    },
                    "message": ("Restored the last complete hardware readback as historical "
                                "evidence; initialize protection to bind an exact parity SHA."),
                    "finished": datetime.fromtimestamp(path.stat().st_mtime,
                                                       timezone.utc).isoformat(),
                }
                return
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                continue

    def _direct_hardware_preflight(self) -> dict[str, Any]:
        if not self.bitmap_tool.exclusive_mode:
            raise HardwareBusy(
                "direct FPGA access is disabled; stop the legacy port 8771 service and relaunch with -ExclusiveHardware")
        status = self.hardware_client.busy_check()
        # Direct Vivado and the legacy service do not share a protocol lock.
        # Requiring the legacy listener to be closed eliminates the race rather
        # than relying on a one-time idle snapshot.
        if status.get("reachable") or status.get("port_open"):
            detail = "busy" if status.get("busy") else "still listening"
            raise HardwareBusy(
                f"legacy SenseEval service is {detail} on port 8771; stop it before direct FPGA access")
        return status

    def _snapshot_evidence(self, ident: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        public = {
            "bytes_hex": snapshot["bytes"].hex(), "bits": list(snapshot["bits"]),
            "sha256": snapshot["sha256"], "byte_count": snapshot["byte_count"],
            "bit_order": snapshot["bit_order"],
        }
        directory = self.runs_dir / "bitmap"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{ident}.parity_snapshot.json"
        path.write_text(json.dumps(public, indent=2) + "\n", encoding="utf-8")
        return public | {"evidence_file": str(path)}

    def start_bitmap_program(self) -> dict[str, Any]:
        ident = uuid.uuid4().hex
        owner = f"bitmap-program:{ident}"
        self._acquire_hardware_gate(owner)
        try:
            snapshot = self.protection.parity_snapshot()
            status = self._direct_hardware_preflight()
            with self.map_lock:
                if self.bitmap_job.get("state") in ("submitted", "running"):
                    raise HardwareBusy("a bitmap programming job is already running")
                if self.map_state.get("state") in ("submitted", "running", "cancelling"):
                    raise HardwareBusy("a physical map read is already running")
                public_snapshot = self._snapshot_evidence(ident, snapshot)
                self.bitmap_job = {"id": ident, "state": "submitted", "completed": 0,
                                   "total": 576, "failures": 0, "started": now(),
                                   "parity_snapshot": public_snapshot,
                                   "message": "Starting direct bitmap tool; requires the bitmap-capable bitstream.",
                                   "senseeval_busy_check": status}
                self.physical_parity = None
                self.physical_parity_job_id = None
                pending = [cell | {"classification": ("spare" if cell["role"] == "spare" else "unknown"),
                                   "observed_bit": None,
                                   "current_ua": None, "threshold_ua": 34.2563054,
                                   "readback_job_id": ident, "source": "bitmap-program-readback"}
                           for cell in parity_layout(snapshot["bits"])]
                self.map_state = {
                    "state": "programming", "source": "bitmap-program-readback",
                    "simulation": False, "completed": 0, "total": 576,
                    "cells": pending, "encoded_parity_sha256": snapshot["sha256"],
                    "physical_parity": {"available": False, "sha_verified": False,
                                        "reason": "programming invalidated prior readback"},
                    "message": self.bitmap_job["message"], "started": now(),
                }
            threading.Thread(target=self._run_bitmap_program,
                             args=(ident, snapshot, owner), daemon=True).start()
        except Exception:
            self._release_hardware_gate(owner)
            raise
        return self.parity_map()

    def _run_bitmap_program(self, ident: str, snapshot: dict[str, Any], owner: str) -> None:
        def progress(update: dict) -> None:
            with self.map_lock:
                if self.bitmap_job.get("id") == ident:
                    self.bitmap_job.update(update)
                    self.bitmap_job["total"] = 576
                    self.bitmap_job["message"] = (f"Programming parity cell {update.get('completed', 0)}/576; "
                                                   f"{update.get('failures', 0)} failed")
        try:
            result = self.bitmap_tool.program(snapshot["bits"], self.runs_dir / "bitmap" / ident, progress)
            cells = self._classify_map(result["rows"], "bitmap-program-readback", ident,
                                       snapshot["bits"])
            failures = int(result["manifest"].get("failures", 0))
            quality = self._map_quality(cells)
            with self.map_lock:
                evidence = {key: value for key, value in result.items() if key != "rows"}
                self.bitmap_job.update(evidence, id=ident, state="completed", completed=576,
                                       total=576, failures=failures, finished=now(),
                                       message=f"Parity programmed in physical range 0..575; {failures} failed.")
                self.map_state = {"state": "completed", "source": "bitmap-program-readback",
                                  "simulation": False, "completed": 576, "total": 576,
                                  "cells": cells, "readback_job_id": ident,
                                  "encoded_parity_sha256": snapshot["sha256"],
                                  "physical_parity": {"available": False, "sha_verified": False,
                                                      "reason": "full 1024-cell readback required"},
                                  **quality,
                                  "message": self.bitmap_job["message"], "finished": now()}
        except Exception as exc:
            with self.map_lock:
                self.bitmap_job.update(state="failed", error=str(exc), message=str(exc), finished=now())
                self.map_state.update(state="failed", source="bitmap-program-readback",
                                      simulation=False, error=str(exc), message=str(exc), finished=now())
        finally:
            self._release_hardware_gate(owner)

    def start_parity_read(self, simulation: bool = False) -> dict[str, Any]:
        if not isinstance(simulation, bool):
            raise ValueError("simulation must be boolean")
        ident = uuid.uuid4().hex
        owner = f"parity-read:{ident}"
        self._acquire_hardware_gate(owner)
        try:
            snapshot = self.protection.parity_snapshot()
            status = ({"skipped": True, "reason": "simulation"} if simulation
                      else self._direct_hardware_preflight())
            with self.map_lock:
                if self.map_state["state"] in ("submitted", "running", "cancelling"):
                    raise HardwareBusy("a parity-map read is already running")
                self.map_cancel = threading.Event()
                self.physical_parity = None
                self.physical_parity_job_id = None
                pending = [cell | {"classification": ("spare" if cell["role"] == "spare" else "unknown"),
                                   "observed_bit": None,
                                   "current_ua": None, "threshold_ua": 34.2563054,
                                   "readback_job_id": ident,
                                   "source": "simulation" if simulation else "bitmap-direct-readback"}
                           for cell in parity_layout(snapshot["bits"])]
                self.map_state = {"id": ident, "state": "submitted",
                                  "source": "simulation" if simulation else "bitmap-direct-readback",
                                  "simulation": simulation, "completed": 0, "total": 1024,
                                  "cells": pending,
                                  "encoded_parity_sha256": snapshot["sha256"],
                                  "parity_snapshot": self._snapshot_evidence(ident, snapshot),
                                  "physical_parity": {"available": False, "sha_verified": False},
                                  "message": ("Creating explicitly simulated map." if simulation
                                              else "Starting direct bitmap read; requires the bitmap-capable bitstream."),
                                  "senseeval_busy_check": status, "started": now()}
            threading.Thread(target=self._run_parity_read,
                             args=(simulation, ident, snapshot, owner), daemon=True).start()
        except Exception:
            self._release_hardware_gate(owner)
            raise
        return self.parity_map()

    def cancel_parity_read(self) -> dict[str, Any]:
        with self.map_lock:
            if self.map_state["state"] not in ("submitted", "running"):
                raise ValueError("no parity-map read is running")
            if self.map_state.get("source") == "bitmap-direct-readback":
                raise ValueError("direct bitmap read cannot be interrupted safely; wait for read-profile restoration")
            self.map_cancel.set()
            self.map_state.update(state="cancelling",
                                  message="Cancellation requested; waiting for safe hardware restoration.")
        return self.parity_map()

    @staticmethod
    def _map_quality(cells: list[dict[str, Any]]) -> dict[str, int]:
        used = [cell for cell in cells if cell.get("role") == "encoded-parity"]
        return {
            "mismatches": sum(cell.get("classification") == "mismatch" for cell in used),
            "unknown": sum(cell.get("classification") == "unknown" for cell in used),
            "failed": sum(cell.get("classification") == "failed" for cell in cells),
            "parity_failed": sum(cell.get("classification") == "failed" for cell in used),
        }

    @staticmethod
    def _reconstruct_parity(cells: list[dict[str, Any]]) -> bytes | None:
        by_index = {int(cell["index"]): cell for cell in cells}
        output = bytearray(72)
        for index in range(576):
            cell = by_index.get(index)
            bit = cell.get("observed_bit") if cell else None
            if bit not in (0, 1):
                return None
            output[index >> 3] |= int(bit) << (index & 7)
        return bytes(output)

    def _classify_map(self, read_cells: list[dict], source: str, job_id: str | None,
                      expected_bits: list[int]) -> list[dict]:
        by_coordinate = {(int(cell["row"]), int(cell["col"])): cell for cell in read_cells}
        threshold_ua = 34.2563054
        result = []
        for expected in parity_layout(expected_bits):
            row, col = expected["row"], expected["col"]
            measured = by_coordinate.get((row, col))
            current = measured.get("current_ua") if measured else None
            observed = (int(float(current) >= threshold_ua)
                        if isinstance(current, (int, float)) and math.isfinite(float(current)) else None)
            logical = expected["logical_bit"]
            if (row, col) in self.failed_cells or (measured is not None and measured.get("pass") is False):
                classification = "failed"
            elif expected["role"] == "spare":
                classification = "spare"
            elif logical is None or observed is None:
                classification = "unknown"
            elif observed != logical:
                classification = "mismatch"
            else:
                classification = "lrs" if observed else "hrs"
            result.append(expected | {"classification": classification, "observed_bit": observed,
                                      "current_ua": current, "threshold_ua": threshold_ua,
                                      "readback_job_id": job_id, "source": source})
        return result

    def _run_parity_read(self, simulation: bool, ident: str,
                         snapshot: dict[str, Any], owner: str) -> None:
        try:
            if simulation:
                reads = [{"row": cell["row"], "col": cell["col"],
                          "current_ua": 52.0 if cell["logical_bit"] else 18.0}
                         for cell in parity_layout(snapshot["bits"])]
                cells = self._classify_map(reads, "simulation", None, snapshot["bits"])
                quality = self._map_quality(cells)
                with self.map_lock:
                    self.map_state.update(state="completed", completed=1024, cells=cells,
                                          **quality,
                                          physical_parity={"available": False, "sha_verified": False,
                                                           "reason": "simulation is never EDAC input"},
                                          message="SIMULATION: deterministic currents; no FPGA read was performed.",
                                          finished=now())
                return

            def progress(update: dict) -> None:
                with self.map_lock:
                    self.map_state.update(update)
                    self.map_state.update(source="bitmap-direct-readback", simulation=False)
                    self.map_state["message"] = f"Direct physical read {update.get('completed', 0)}/1024"
            hardware = self.bitmap_tool.read(self.runs_dir / "bitmap" / ident, progress)
            cells = self._classify_map(hardware["rows"], "bitmap-direct-readback", ident,
                                       snapshot["bits"])
            quality = self._map_quality(cells)
            measured = self._reconstruct_parity(cells)
            measured_sha = sha256(measured) if measured is not None else None
            sha_verified = measured_sha == snapshot["sha256"] if measured_sha else False
            usable = bool(sha_verified and not quality["parity_failed"] and not quality["unknown"])
            with self.map_lock:
                self.physical_parity = measured
                self.physical_parity_job_id = ident if measured is not None else None
                self.map_state.update(state="completed", completed=1024, cells=cells,
                                      readback_job_id=ident, evidence=hardware["summary"], **quality,
                                      physical_parity={"available": measured is not None,
                                                       "sha256": measured_sha,
                                                       "expected_sha256": snapshot["sha256"],
                                                       "sha_verified": sha_verified,
                                                       "usable_for_check_repair": usable,
                                                       "readback_job_id": ident},
                                      message=("Hardware readback complete: "
                                               f"{quality['mismatches']} mismatch, "
                                               f"{quality['unknown']} unknown, {quality['failed']} failed."),
                                      finished=now())
        except Exception as exc:
            with self.map_lock:
                self.map_state.update(state="failed", error=str(exc), message=str(exc), finished=now())
        finally:
            self._release_hardware_gate(owner)

    def _run_inference(self, session: Session) -> None:
        try:
            session.metrics = {"runtime": self.runtime.info.public(),
                               "protection_at_start": self.protection.public()}
            for token in self.runtime.stream(session.request["prompt"],
                                             session.request["max_new_tokens"], session.cancel):
                session.output += token
                session.emit("token", {"token": token})
            session.emit("inference_complete", {"cancelled": session.cancel.is_set(),
                                                 "runtime": self.runtime.info.public()})
        except Exception as exc:
            session.error = str(exc)
            session.emit("error", {"component": "inference", "message": str(exc)})
        finally:
            self._part_done(session)

    def _run_hardware(self, session: Session) -> None:
        owner = f"row-probe:{session.id}"
        acquired = False

        def progress(data: dict) -> None:
            session.hardware = data
            session.emit("hardware", data)
        try:
            self._acquire_hardware_gate(owner)
            acquired = True
            result = self.hardware_client.run_sparse_row_probe(
                session.request["seed"], session.cancel.is_set, progress)
            session.hardware = result
            session.emit("hardware_complete", result)
        except HardwareBusy as exc:
            session.hardware = {"state": "skipped-busy", "error": str(exc)}
            session.emit("hardware_complete", session.hardware)
        except Exception as exc:
            session.hardware = {"state": "failed", "error": str(exc)}
            session.emit("hardware_complete", session.hardware)
        finally:
            if acquired:
                self._release_hardware_gate(owner)
            self._part_done(session)

    def _part_done(self, session: Session) -> None:
        with session.condition:
            session.pending_parts -= 1
            should_finish = session.pending_parts == 0
        if should_finish:
            final_state = ("cancelled" if session.cancel.is_set()
                           else ("failed" if session.error else "completed"))
            finished = now()
            session.emit("complete", {"state": final_state})
            path = self.runs_dir / f"{session.id}.json"
            temporary = path.with_suffix(".tmp")
            snapshot = session.public(True)
            snapshot["state"] = final_state
            snapshot["finished"] = finished
            temporary.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
            temporary.replace(path)
            # Publish the terminal state only after its evidence file is
            # durable, so observers never race cleanup against the writer.
            with session.condition:
                session.state = final_state
                session.finished = finished
                session.condition.notify_all()
