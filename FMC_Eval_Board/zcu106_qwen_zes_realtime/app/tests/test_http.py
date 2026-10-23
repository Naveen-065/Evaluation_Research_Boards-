import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import create_server
from service import InferenceService
from test_service import FakeHardware


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = InferenceService(Path(self.temp.name), FakeHardware())
        self.server = create_server(port=0, service=self.service)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data,
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())

    def test_protection_and_inference_api(self):
        _, initialized = self.request("/api/protection/initialize", {"edac_mode": "reference"})
        self.assertTrue(initialized["initialized"])
        _, injected = self.request("/api/protection/inject", {"error_percent": 100 / 8192, "seed": 4})
        self.assertEqual(injected["last_injection"]["injected_bits"], 1)
        _, checked = self.request("/api/protection/check", {"threshold": 3})
        self.assertFalse(checked["sha_verified"])
        self.assertEqual(checked["last_check"]["parity_source"], "host-encoded-copy")
        self.assertFalse(checked["last_check"]["physical_parity_used"])
        _, repaired = self.request("/api/protection/repair", {"threshold": 3})
        self.assertTrue(repaired["sha_verified"])
        status, accepted = self.request("/api/inference", {"prompt": "test", "hardware_mode": "off"})
        self.assertEqual(status, 202)
        with urllib.request.urlopen(self.base + accepted["events"], timeout=5) as stream:
            text = stream.read().decode()
        self.assertIn("event: token", text)
        self.assertIn("event: complete", text)

    def test_memory_map_alias(self):
        _, result = self.request("/api/memory-map")
        self.assertEqual(result["state"], "idle")

    def test_simulation_boolean_is_not_coerced(self):
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.request("/api/memory-map/read", {"simulation": "false"})
        self.assertEqual(raised.exception.code, 400)
        raised.exception.close()

    def test_non_object_json_and_invalid_event_cursor_return_json_400(self):
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.request("/api/protection/initialize", [])
        self.assertEqual(raised.exception.code, 400)
        self.assertEqual(json.loads(raised.exception.read())["error"],
                         "request body must be a JSON object")
        raised.exception.close()

        _, accepted = self.request("/api/inference", {"prompt": "cursor test"})
        with self.assertRaises(urllib.error.HTTPError) as raised_cursor:
            self.request(accepted["events"] + "?cursor=not-an-integer")
        self.assertEqual(raised_cursor.exception.code, 400)
        self.assertIn("nonnegative integer", json.loads(raised_cursor.exception.read())["error"])
        raised_cursor.exception.close()

    def test_unknown_fields_are_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.request("/api/protection/initialize", {"edac_mode": "reference", "extra": 1})
        self.assertEqual(raised.exception.code, 400)
        raised.exception.close()


if __name__ == "__main__":
    unittest.main()
