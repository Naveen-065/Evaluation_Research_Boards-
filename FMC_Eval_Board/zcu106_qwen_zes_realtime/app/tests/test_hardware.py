import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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

    def test_runner_does_not_wait_for_inherited_stdout_handle_to_close(self):
        inherited_handles = []
        try:
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                app_dir = root / "app"
                tools = root / "fpga" / "tools"
                probes = root / "fpga" / "zcu106_cell_control" / "build" / "zcu106_adc_capture.ltx"
                executable = root / "fake-vivado.exe"
                script = tools / "bitmap_program.tcl"
                app_dir.mkdir()
                tools.mkdir(parents=True)
                probes.parent.mkdir(parents=True)
                probes.touch()
                executable.touch()
                script.touch()

                class ExitedVivadoWithLiveDescendant:
                    def __init__(self, _command, cwd, stdout, stderr, **_options):
                        self.returncode = 0
                        self.stdout = None
                        self.inherited_handle = os.dup(stdout.fileno())
                        inherited_handles.append(self.inherited_handle)
                        os.write(stdout.fileno(), (
                            b"BITMAP_PROGRESS completed=1 failures=0 row=0 column=0 target=1\n"
                            b"BITMAP_DONE completed=1 failures=0\n"
                        ))
                        os.fsync(stdout.fileno())

                    def poll(self):
                        return self.returncode

                    def wait(self):
                        return self.returncode

                try:
                    with patch.dict(os.environ, {
                        "RERAM_EXCLUSIVE_HARDWARE": "1",
                        "BITMAP_VIVADO": str(executable),
                    }), patch("hardware.subprocess.Popen", ExitedVivadoWithLiveDescendant):
                        updates = []
                        runner = BitmapToolRunner(app_dir)
                        lines, code = runner._run(
                            script, [], updates.append,
                            re.compile(
                                r"BITMAP_PROGRESS completed=(?P<completed>\d+) failures=(?P<failures>\d+) "
                                r"row=(?P<row>\d+) column=(?P<col>\d+) target=(?P<target>\d+)"),
                            "BITMAP_DONE ",
                        )
                        self.assertTrue(
                            inherited_handles,
                            "fixture must retain a descendant-like output handle",
                        )
                finally:
                    for handle in inherited_handles:
                        os.close(handle)
                    inherited_handles.clear()

                self.assertEqual(code, 0)
                self.assertEqual(updates[0]["completed"], 1)
                self.assertTrue(any(line.startswith("BITMAP_DONE ") for line in lines))
        finally:
            for handle in inherited_handles:
                os.close(handle)

    def test_watchdog_kills_only_launched_tree_and_retains_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app_dir = root / "app"
            tools = root / "fpga" / "tools"
            probes = root / "fpga" / "zcu106_cell_control" / "build" / "zcu106_adc_capture.ltx"
            executable = root / "fake-vivado.exe"
            script = tools / "bitmap_program.tcl"
            app_dir.mkdir()
            tools.mkdir(parents=True)
            probes.parent.mkdir(parents=True)
            probes.touch()
            executable.touch()
            script.touch()

            class HangingVivado:
                def __init__(self, _command, cwd, stdout, stderr, **_options):
                    self.pid = 424242
                    self.returncode = None
                    os.write(stdout.fileno(), b"Vivado reached refresh_hw_vio\n")
                    os.fsync(stdout.fileno())

                def poll(self):
                    return self.returncode

                def wait(self, timeout=None):
                    return self.returncode

                def kill(self):
                    self.returncode = -9

            terminated = []

            def terminate_exact(process):
                terminated.append(process)
                process.returncode = -9
                return "taskkill /PID 424242 /T /F exited 0; Vivado exit=-9"

            with patch.dict(os.environ, {
                "RERAM_EXCLUSIVE_HARDWARE": "1",
                "BITMAP_VIVADO": str(executable),
            }), patch("hardware.subprocess.Popen", HangingVivado), patch.object(
                    BitmapToolRunner, "_terminate_process_tree", side_effect=terminate_exact):
                runner = BitmapToolRunner(app_dir, no_progress_timeout_seconds=0.05)
                with self.assertRaisesRegex(RuntimeError, "no-progress watchdog expired") as raised:
                    runner._run(script, [], lambda _update: None, re.compile(r"never"), "BITMAP_DONE ")

            self.assertEqual(len(terminated), 1)
            logs = list((root / "runtime").glob("bitmap_program-*.log"))
            self.assertEqual(len(logs), 1)
            self.assertIn("Vivado reached refresh_hw_vio", logs[0].read_text(encoding="utf-8"))
            self.assertIn(str(logs[0]), str(raised.exception))
            self.assertIn("No hardware-restore Vivado session was started", str(raised.exception))

    def test_windows_tree_termination_is_scoped_to_popen_pid(self):
        class Process:
            pid = 4312
            returncode = None

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                self.returncode = -9
                return self.returncode

            def kill(self):
                self.returncode = -9

        completed = SimpleNamespace(returncode=0, stdout="SUCCESS: terminated tree")
        with patch("hardware.os.name", "nt"), patch(
                "hardware.subprocess.run", return_value=completed) as run:
            detail = BitmapToolRunner._terminate_process_tree(Process())

        self.assertEqual(
            run.call_args.args[0],
            ["taskkill.exe", "/PID", "4312", "/T", "/F"],
        )
        self.assertIn("taskkill /PID 4312 /T /F", detail)

    def test_output_activity_resets_watchdog_deadline(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app_dir = root / "app"
            tools = root / "fpga" / "tools"
            probes = root / "fpga" / "zcu106_cell_control" / "build" / "zcu106_adc_capture.ltx"
            executable = root / "fake-vivado.exe"
            script = tools / "bitmap_program.tcl"
            app_dir.mkdir()
            tools.mkdir(parents=True)
            probes.parent.mkdir(parents=True)
            probes.touch()
            executable.touch()
            script.touch()

            class ActiveVivado:
                def __init__(self, _command, cwd, stdout, stderr, **_options):
                    self.stdout = stdout
                    self.pid = 5151
                    self.returncode = None
                    self.polls = 0

                def poll(self):
                    self.polls += 1
                    if self.polls <= 2:
                        os.write(self.stdout.fileno(), f"activity {self.polls}\n".encode("ascii"))
                        os.fsync(self.stdout.fileno())
                        return None
                    os.write(self.stdout.fileno(), b"BITMAP_DONE completed=1 failures=0\n")
                    os.fsync(self.stdout.fileno())
                    self.returncode = 0
                    return self.returncode

                def wait(self, timeout=None):
                    return self.returncode

            with patch.dict(os.environ, {
                "RERAM_EXCLUSIVE_HARDWARE": "1",
                "BITMAP_VIVADO": str(executable),
            }), patch("hardware.subprocess.Popen", ActiveVivado):
                runner = BitmapToolRunner(app_dir, no_progress_timeout_seconds=0.15)
                lines, code = runner._run(
                    script, [], lambda _update: None, re.compile(r"never"), "BITMAP_DONE ")

            self.assertEqual(code, 0)
            self.assertIn("activity 2", lines)
            self.assertTrue(any(line.startswith("BITMAP_DONE ") for line in lines))


if __name__ == "__main__":
    unittest.main()
