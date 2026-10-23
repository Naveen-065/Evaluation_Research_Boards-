import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hardware import BitmapToolRunner, HardwareConfig
from hardware import HardwareBusy
from service import InferenceService, parity_layout


class FakeHardware:
    config = HardwareConfig(base_url="http://fixture.invalid")

    def safe_status(self):
        return {"reachable": True, "compatible": True, "target": "zcu106",
                "busy": False, "deployment_ready": True, "message": "fixture"}

    def busy_check(self):
        return {"reachable": False, "port_open": False, "busy": False,
                "message": "fixture standalone mode"}

    def run_sparse_row_probe(self, seed, cancelled, progress):
        progress({"state": "running", "message": "fixture probe"})
        return {"state": "completed", "outputs": [], "selected_row": seed % 32}


class FakeBitmap:
    def __init__(self, bits, mismatch_index=None):
        self.bits = bits
        self.mismatch_index = mismatch_index
        self.exclusive_mode = True

    def capabilities(self):
        return {"configured": True, "probes_file_present": True}

    def _rows(self, count):
        rows = []
        for index in range(count):
            bit = self.bits[index] if index < 576 else 0
            if index == self.mismatch_index:
                bit = 1 - bit
            rows.append({"index": index, "row": index // 32, "col": index % 32,
                         "pass": True, "current_ua": 52.0 if bit else 18.0})
        return rows

    def read(self, _job_dir, progress):
        progress({"state": "running", "completed": 1024, "total": 1024})
        return {"rows": self._rows(1024), "summary": {"fixture": True}}

    def program(self, _bits, _job_dir, progress):
        progress({"state": "running", "completed": 576, "failures": 0,
                  "row": 17, "col": 31, "target": self.bits[-1]})
        return {"rows": self._rows(576), "manifest": {"failures": 0},
                "state": "completed", "programmed_range": [0, 575],
                "spares_programmed": False}


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = InferenceService(Path(self.temp.name), FakeHardware())

    def tearDown(self):
        self.temp.cleanup()

    def test_live_block_initialize_inject_check_repair(self):
        initialized = self.service.protection.initialize("reference")
        self.assertTrue(initialized["sha_verified"])
        self.assertEqual(initialized["parity_bytes"], 72)
        injected = self.service.protection.inject(100 / 8192, 123)
        self.assertEqual(injected["last_injection"]["injected_bits"], 1)
        self.assertFalse(injected["sha_verified"])
        checked = self.service.protection.check(3)
        self.assertFalse(checked["last_check"]["live_tensor_mutated"])
        self.assertFalse(checked["sha_verified"])
        repaired = self.service.protection.repair(3)
        self.assertTrue(repaired["sha_verified"])
        self.assertTrue(repaired["last_check"]["repair_sha_verified"])

    def test_inference_stream_is_actual_runtime_output(self):
        session = self.service.start({"prompt": "hello", "hardware_mode": "off", "max_new_tokens": 50})
        deadline = time.monotonic() + 3
        while session.state == "running" and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(session.state, "completed")
        self.assertIn("Demo response", session.output)
        self.assertTrue(any(event["type"] == "token" for event in session.events))

    def test_parity_layout_uses_576_encoded_bits_then_spares(self):
        bits = [index & 1 for index in range(576)]
        layout = parity_layout(bits)
        self.assertEqual(len(layout), 1024)
        self.assertEqual(layout[575]["logical_bit"], 1)
        self.assertEqual(layout[576]["role"], "spare")
        self.assertIsNone(layout[576]["logical_bit"])

    def test_bitmap_words_are_lsb_column_order(self):
        bits = [0] * 576
        bits[0] = 1; bits[31] = 1; bits[32] = 1; bits[575] = 1
        words = BitmapToolRunner.row_words(bits)
        self.assertEqual(words[0], 0x80000001)
        self.assertEqual(words[1], 1)
        self.assertEqual(words[17], 0x80000000)
        self.assertTrue(all(word == 0 for word in words[18:]))

    def test_simulation_map_is_explicit(self):
        self.service.protection.initialize("reference")
        self.service.start_parity_read(True)
        deadline = time.monotonic() + 2
        while self.service.parity_map()["state"] != "completed" and time.monotonic() < deadline:
            time.sleep(0.01)
        result = self.service.parity_map()
        self.assertEqual(result["source"], "simulation")
        self.assertTrue(result["simulation"])
        self.assertIn("SIMULATION", result["message"])

    def test_complete_physical_map_supplies_sha_verified_parity(self):
        self.service.initialize_protection("reference")
        bits = self.service.protection.parity_snapshot()["bits"]
        self.service.bitmap_tool = FakeBitmap(bits)
        self.service.start_parity_read(False)
        deadline = time.monotonic() + 2
        while self.service.parity_map()["state"] != "completed" and time.monotonic() < deadline:
            time.sleep(0.01)
        physical = self.service.parity_map()["physical_parity"]
        self.assertTrue(physical["sha_verified"])
        self.assertTrue(physical["usable_for_check_repair"])
        checked = self.service.check_protection(3, "physical")
        self.assertEqual(checked["last_check"]["parity_source"],
                         "physical-readback-sha-verified")
        self.assertTrue(checked["last_check"]["physical_parity_used"])

    def test_physical_parity_sha_mismatch_blocks_edac(self):
        self.service.initialize_protection("reference")
        bits = self.service.protection.parity_snapshot()["bits"]
        self.service.bitmap_tool = FakeBitmap(bits, mismatch_index=0)
        self.service.start_parity_read(False)
        deadline = time.monotonic() + 2
        while self.service.parity_map()["state"] != "completed" and time.monotonic() < deadline:
            time.sleep(0.01)
        result = self.service.parity_map()
        self.assertFalse(result["physical_parity"]["sha_verified"])
        self.assertEqual(result["mismatches"], 1)
        with self.assertRaisesRegex(ValueError, "SHA does not match"):
            self.service.check_protection(3, "physical")

    def test_physical_map_reports_measured_bit_separately_from_intent(self):
        self.service.initialize_protection("reference")
        bits = self.service.protection.parity_snapshot()["bits"]
        self.service.bitmap_tool = FakeBitmap(bits, mismatch_index=0)
        self.service.start_parity_read(False)
        deadline = time.monotonic() + 2
        while self.service.parity_map()["state"] != "completed" and time.monotonic() < deadline:
            time.sleep(0.01)
        cells = self.service.parity_map()["cells"]
        self.assertEqual(cells[0]["logical_bit"], bits[0])
        self.assertEqual(cells[0]["observed_bit"], 1 - bits[0])
        self.assertEqual(cells[0]["classification"], "mismatch")
        self.assertEqual(cells[575]["role"], "encoded-parity")
        self.assertEqual(cells[576]["role"], "spare")
        self.assertIsNone(cells[576]["logical_bit"])
        self.assertIn(cells[576]["observed_bit"], (0, 1))

    def test_complete_physical_map_survives_restart_and_sha_rebinds(self):
        self.service.initialize_protection("reference")
        snapshot = self.service.protection.parity_snapshot()
        ident = "0123456789abcdef0123456789abcdef"
        bitmap_root = Path(self.temp.name) / "bitmap"
        job_dir = bitmap_root / ident
        job_dir.mkdir(parents=True)
        public_snapshot = {
            "bytes_hex": snapshot["bytes"].hex(), "bits": snapshot["bits"],
            "sha256": snapshot["sha256"], "byte_count": 72, "bit_order": "lsb0",
        }
        (bitmap_root / f"{ident}.parity_snapshot.json").write_text(
            json.dumps(public_snapshot), encoding="utf-8")
        raw_cells = []
        for index in range(1024):
            bit = snapshot["bits"][index] if index < 576 else 0
            raw_cells.append({"physical_index": index, "row": index // 32,
                              "column": index % 32,
                              "current_uA": 52.0 if bit else 18.0,
                              "observed_bit": bit})
        (job_dir / "physical_readback.json").write_text(json.dumps({
            "protocol": "ZCU106_BITMAP_READ_V1", "start": 0, "count": 1024,
            "threshold_uA": 34.2563054, "cells": raw_cells,
        }), encoding="utf-8")

        restored = InferenceService(Path(self.temp.name), FakeHardware())
        historical = restored.parity_map()
        self.assertTrue(historical["restored_historical"])
        self.assertEqual(historical["readback_job_id"], ident)
        self.assertEqual(len(historical["cells"]), 1024)
        self.assertFalse(historical["physical_parity"]["usable_for_check_repair"])
        self.assertFalse(restored.protection.public()["initialized"])

        restored.initialize_protection("reference")
        rebound = restored.parity_map()
        self.assertFalse(rebound["restored_historical"])
        self.assertEqual(rebound["source"], "bitmap-direct-readback")
        self.assertTrue(rebound["physical_parity"]["sha_verified"])
        self.assertTrue(rebound["physical_parity"]["usable_for_check_repair"])

    def test_bitmap_job_snapshots_exact_parity_and_leaves_spares(self):
        self.service.initialize_protection("reference")
        snapshot = self.service.protection.parity_snapshot()
        self.service.bitmap_tool = FakeBitmap(snapshot["bits"])
        self.service.start_bitmap_program()
        deadline = time.monotonic() + 2
        while self.service.parity_map()["bitmap_job"]["state"] not in ("completed", "failed") and time.monotonic() < deadline:
            time.sleep(0.01)
        result = self.service.parity_map()
        captured = result["bitmap_job"]["parity_snapshot"]
        self.assertEqual(captured["sha256"], snapshot["sha256"])
        self.assertEqual(captured["bytes_hex"], snapshot["bytes"].hex())
        self.assertEqual(captured["bits"], snapshot["bits"])
        self.assertTrue(Path(captured["evidence_file"]).is_file())
        self.assertEqual(result["bitmap_job"]["programmed_range"], [0, 575])
        self.assertFalse(result["bitmap_job"]["spares_programmed"])

    def test_initialize_invalidates_old_map_and_gate_serializes(self):
        self.service.initialize_protection("reference")
        self.service.start_parity_read(True)
        deadline = time.monotonic() + 2
        while self.service.parity_map()["state"] != "completed" and time.monotonic() < deadline:
            time.sleep(0.01)
        self.service.initialize_protection("reference")
        invalidated = self.service.parity_map()
        self.assertIsNone(invalidated["source"])
        self.assertEqual(len(invalidated["cells"]), 1024)
        self.assertTrue(all(cell["classification"] in ("unknown", "spare")
                            for cell in invalidated["cells"][:576]))
        self.assertEqual(invalidated["cells"][576]["classification"], "spare")
        self.service._acquire_hardware_gate("fixture")
        try:
            with self.assertRaises(HardwareBusy):
                self.service.initialize_protection("reference")
        finally:
            self.service._release_hardware_gate("fixture")

    def test_threshold_policy_is_one_to_8192(self):
        self.service.protection.initialize("reference")
        for invalid in (0, 8193, False):
            with self.assertRaisesRegex(ValueError, "1 to 8192"):
                self.service.protection.check(invalid)

    def test_direct_hardware_is_fail_closed_without_exclusive_mode(self):
        self.service.initialize_protection("reference")
        bits = self.service.protection.parity_snapshot()["bits"]
        tool = FakeBitmap(bits)
        tool.exclusive_mode = False
        self.service.bitmap_tool = tool
        with self.assertRaisesRegex(HardwareBusy, "ExclusiveHardware"):
            self.service.start_parity_read(False)

    def test_direct_hardware_rejects_live_legacy_listener(self):
        self.service.initialize_protection("reference")
        bits = self.service.protection.parity_snapshot()["bits"]
        self.service.bitmap_tool = FakeBitmap(bits)
        with patch.object(self.service.hardware_client, "busy_check",
                          return_value={"reachable": True, "port_open": True, "busy": False}):
            with self.assertRaisesRegex(HardwareBusy, "still listening"):
                self.service.start_bitmap_program()


if __name__ == "__main__":
    unittest.main()
