"""Fault injection only: no network or hardware is accessed."""
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gui"))
import ssh_transport as transport
import server

BANNER_TIMEOUT = ("Connection timed out during banner exchange\n"
                  "Connection to UNKNOWN port 65535 timed out\n")
CHECK_OUTPUT = ("CONTROL_STATUS 0000001b00000000 "
                "5343523200000000000000000000000000000000000000000000000000000000\n")


class Process:
    def __init__(self, output, code):
        self.stdout, self.code = io.StringIO(output), code

    def wait(self):
        return self.code

    def poll(self):
        return self.code


class TransportTests(unittest.TestCase):
    def execute(self, responses, job=None, on_update=None):
        job = job if job is not None else {}
        log, messages = io.StringIO(), []
        def update(message):
            messages.append(message)
            if on_update:
                on_update(message, job)
        run = transport.RemoteRun(["ssh", "fixture"], job, log, update)
        with patch.object(transport.subprocess, "Popen", side_effect=responses) as launch, \
                patch.object(transport.time, "sleep"):
            lines = list(run)
        return run, job, lines, log.getvalue(), messages, launch.call_count

    def test_banner_timeout_retries_before_single_successful_launch(self):
        run, job, lines, log, messages, calls = self.execute([
            Process(BANNER_TIMEOUT, 255), Process(CHECK_OUTPUT, 0)])
        self.assertEqual((calls, run.returncode, job["connection_attempt"]), (2, 0, 2))
        self.assertEqual("".join(lines).count("CONTROL_STATUS"), 1)
        self.assertIn("API_SSH_ATTEMPT 2/3", log)
        self.assertTrue(any("No hardware command was sent" in x for x in messages))

    def test_bounded_failure_has_clear_no_command_message(self):
        run, job, _, _, _, calls = self.execute([Process(BANNER_TIMEOUT, 255) for _ in range(3)])
        self.assertEqual(calls, 3)
        self.assertTrue(run.prelaunch_failure)
        self.assertIn("no hardware command was sent", run.failure_message())

    def test_ambiguous_disconnect_never_retries(self):
        for output in ["", "client_loop: send disconnect: Broken pipe\n",
                       CHECK_OUTPUT + BANNER_TIMEOUT,
                       "EVENT SET pulse started\n" + BANNER_TIMEOUT,
                       "Connection to UNKNOWN port 65535 timed out\n"]:
            with self.subTest(output=output):
                run, _, _, _, _, calls = self.execute([Process(output, 255)])
                self.assertEqual(calls, 1)
                self.assertFalse(run.prelaunch_failure)
                self.assertIn("not retried", run.failure_message())

    def test_non_ssh_hardware_error_never_retries(self):
        run, _, _, _, _, calls = self.execute([Process("ERROR: ADC not healthy\n", 1)])
        self.assertEqual(calls, 1)
        self.assertEqual(run.returncode, 1)

    def test_connect_refusal_is_prelaunch_but_auth_failure_is_not_retried(self):
        self.assertTrue(transport.confirmed_prelaunch_failure(255, [
            "ssh: connect to host 100.98.132.51 port 22: Connection refused\n"]))
        self.assertFalse(transport.confirmed_prelaunch_failure(255, [
            "fpga@10.0.2.2: Permission denied (publickey,password).\n"]))

    def test_cancel_before_connect_launches_nothing(self):
        run, _, _, _, _, calls = self.execute([], {"cancel_requested": True})
        self.assertEqual(calls, 0)
        self.assertTrue(run.cancelled_before_launch)

    def test_cancel_during_backoff_prevents_second_connection(self):
        def cancel(message, job):
            if "retrying connection" in message:
                job["cancel_requested"] = True
        run, _, _, _, _, calls = self.execute([Process(BANNER_TIMEOUT, 255)], on_update=cancel)
        self.assertEqual(calls, 1)
        self.assertTrue(run.cancelled_before_launch)


class WorkerTests(unittest.TestCase):
    def run_worker(self, mode, responses):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "runs").mkdir()
            (root / "evidence").mkdir()
            (root / "evidence/deployment.json").write_text(json.dumps({"ready": True}))
            state = {"busy": True, "history": [], "jobs": []}
            job = {"id": "a" * 32, "state": "running", "results": [],
                   "parameters": server.validate({"mode": mode, "dry_run": False, "row": 0, "col": 0})}
            with patch.object(server, "ROOT", root), patch.object(server, "STATE", state), \
                    patch.object(transport.subprocess, "Popen", side_effect=responses) as launch, \
                    patch.object(transport.time, "sleep"):
                server.worker(job)
            saved = json.loads((root / "runs" / f"{job['id']}.json").read_text())
            deployment = json.loads((root / "evidence/deployment.json").read_text())
            return saved, deployment, state, launch.call_count

    def test_api_worker_recovers_check_and_records_attempts(self):
        job, deployment, state, calls = self.run_worker(
            "check", [Process(BANNER_TIMEOUT, 255), Process(CHECK_OUTPUT, 0)])
        self.assertEqual((job["state"], job["connection_attempt"], calls), ("completed", 2, 2))
        self.assertTrue(job["status"]["adc_healthy"])
        self.assertTrue(deployment["ready"])
        self.assertFalse(state["busy"])

    def test_exhausted_startup_does_not_quarantine_unchanged_hardware(self):
        job, deployment, state, calls = self.run_worker(
            "cycle", [Process(BANNER_TIMEOUT, 255) for _ in range(3)])
        self.assertEqual((job["state"], job["remote_execution"], calls), ("failed", "not_started", 3))
        self.assertEqual(job["results"], [])
        self.assertTrue(deployment["ready"])
        self.assertFalse(state["busy"])

    def test_disconnect_after_start_blocks_new_operations_and_never_replays(self):
        job, deployment, _, calls = self.run_worker(
            "cycle", [Process(CHECK_OUTPUT + "client_loop: send disconnect: Broken pipe\n", 255)])
        self.assertEqual(calls, 1)
        self.assertEqual(job["remote_execution"], "uncertain")
        self.assertTrue(job["requires_recovery"])
        self.assertFalse(deployment["ready"])
        self.assertIn("not retried", job["error"])


class HttpApiTests(unittest.TestCase):
    def test_http_api_recovers_startup_timeout_and_exposes_the_log(self):
        # A temporary test listener with mocked SSH; never connects to the bench.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "runs").mkdir()
            (root / "evidence").mkdir()
            (root / "evidence/deployment.json").write_text(json.dumps({"ready": True}))
            state = {"busy": False, "job": None, "history": [], "jobs": [], "message": "Test fixture"}
            with patch.object(server, "ROOT", root), patch.object(server, "STATE", state), \
                    patch.object(transport.subprocess, "Popen", side_effect=[
                        Process(BANNER_TIMEOUT, 255), Process(CHECK_OUTPUT, 0)]) as launch:
                listener = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
                thread = threading.Thread(target=listener.serve_forever, daemon=True)
                thread.start()
                url = f"http://127.0.0.1:{listener.server_port}"
                def request(path, body=None):
                    raw = None if body is None else json.dumps(body).encode()
                    with urllib.request.urlopen(urllib.request.Request(
                            url + path, data=raw, headers={"Content-Type": "application/json"}), timeout=5) as response:
                        return response.read()
                try:
                    submitted = json.loads(request("/api/run", {"mode": "check", "dry_run": False}))
                    deadline = time.monotonic() + 8
                    while True:
                        status = json.loads(request("/api/status"))
                        if not status["busy"]:
                            break
                        self.assertLess(time.monotonic(), deadline, "Fixture worker did not finish")
                        time.sleep(0.05)
                    self.assertEqual(status["api_revision"], "fpga-array-scheduler-resetpath-v4.2")
                    self.assertEqual(status["transport"]["connect_timeout_seconds"], 30)
                    self.assertEqual(status["job"]["state"], "completed")
                    self.assertEqual(status["job"]["connection_attempt"], 2)
                    self.assertEqual(launch.call_count, 2)
                    log = request("/api/run-log/" + submitted["job_id"]).decode()
                    self.assertIn("API_SSH_ATTEMPT 2/3", log)
                    self.assertIn("Connection timed out during banner exchange", log)
                    self.assertEqual(log.count("CONTROL_STATUS"), 1)
                finally:
                    listener.shutdown()
                    listener.server_close()
                    thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
