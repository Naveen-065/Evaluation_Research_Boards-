import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hardware import BitmapToolRunner, HardwareBusy, SenseEvalClient, _HardwareFileLease


class FixtureSenseEval(SenseEvalClient):
    def _request(self, _path, body=None, timeout=None):
        return {
            "api_revision": self.config.expected_revision,
            "target": "zcu106", "busy": False, "message": "fixture",
            "deployment": {"ready": True},
            "history": [{"payload": "x" * 10000}],
            "jobs": [{"result": "y" * 10000}],
        }


class HardwareTests(unittest.TestCase):
    def test_public_status_is_compact(self):
        status = FixtureSenseEval().status()
        self.assertNotIn("raw", status)
        self.assertNotIn("_raw", status)
        self.assertNotIn("history", status)
        self.assertNotIn("jobs", status)
        self.assertTrue(status["deployment_ready"])

    def test_bitmap_program_uses_only_physical_zero_through_575(self):
        app_dir = Path(__file__).resolve().parents[1]
        runner = BitmapToolRunner(app_dir)
        bits = [index & 1 for index in range(576)]
        captured = {}

        def fake_run(_script, arguments, _progress, _pattern, _done_prefix):
            captured["arguments"] = list(arguments)
            prefix = Path(arguments[1])
            Path(f"{prefix}.manifest.json").write_text(
                json.dumps({"failures": 0}), encoding="utf-8")
            rows = ["physical_index,row,column,requested_bit,pass,pulses,clipped,current_uA"]
            for index in range(576):
                rows.append(f"{index},{index // 32},{index % 32},{bits[index]},1,0,0,18.0")
            Path(f"{prefix}.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
            return [], 0

        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(runner, "_run", side_effect=fake_run):
                result = runner.program(bits, Path(temporary) / "job", lambda _update: None)
        self.assertEqual(captured["arguments"][2:4], ["0", "576"])
        self.assertEqual(result["programmed_range"], [0, 575])
        self.assertFalse(result["spares_programmed"])

    def test_cross_process_lease_is_nonblocking_and_exclusive(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "hardware.lease"
            with _HardwareFileLease(path):
                with self.assertRaises(HardwareBusy):
                    with _HardwareFileLease(path):
                        pass


if __name__ == "__main__":
    unittest.main()
