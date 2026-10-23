"""Local-only stdlib HTTP/SSE server for Qwen + EDAC + ZCU106 orchestration."""

from __future__ import annotations

import argparse
import json
import mimetypes
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from service import InferenceService


HERE = Path(__file__).resolve().parent
STATIC = HERE / "web"
RUNS = HERE / "runs"


class AppHandler(BaseHTTPRequestHandler):
    service: InferenceService
    server_version = "ZCU106-Qwen-ZES/1.0"

    def _json(self, code: int, data: object) -> None:
        raw = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 65536:
            raise ValueError("request body must contain 1–65536 bytes")
        body = json.loads(self.rfile.read(length))
        if not isinstance(body, dict):
            raise ValueError("request body must be a JSON object")
        return body

    @staticmethod
    def _allow_fields(body: dict, *allowed: str) -> None:
        unknown = set(body) - set(allowed)
        if unknown:
            raise ValueError(f"unknown request field(s): {', '.join(sorted(unknown))}")

    def _same_origin(self) -> bool:
        host = self.headers.get("Host", "")
        allowed_hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        origin = self.headers.get("Origin")
        return host in allowed_hosts and origin in (None, f"http://{host}")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/app.js", "/styles.css"):
            asset = STATIC / ("index.html" if path == "/" else path[1:])
            if not asset.is_file():
                return self._json(404, {"error": "asset not found"})
            raw = asset.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(asset.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            return self.wfile.write(raw)
        if path == "/api/capabilities":
            return self._json(200, self.service.capabilities())
        if path == "/api/protection":
            return self._json(200, self.service.protection.public())
        if path == "/api/hardware/status":
            return self._json(200, self.service.hardware_summary())
        if path in ("/api/hardware/parity-map", "/api/memory-map"):
            return self._json(200, self.service.parity_map())
        if path == "/api/runs":
            return self._json(200, {"runs": self.service.list_runs()})
        parts = [part for part in path.split("/") if part]
        if len(parts) == 3 and parts[:2] == ["api", "inference"]:
            try:
                return self._json(200, self.service.get(parts[2]).public(True))
            except KeyError as exc:
                return self._json(404, {"error": str(exc)})
        if len(parts) == 4 and parts[:2] == ["api", "inference"] and parts[3] == "events":
            cursor_value = parse_qs(parsed.query).get("cursor", ["0"])[0]
            try:
                cursor = int(cursor_value)
            except (TypeError, ValueError):
                return self._json(400, {"error": "cursor must be a nonnegative integer"})
            if cursor < 0:
                return self._json(400, {"error": "cursor must be a nonnegative integer"})
            return self._events(parts[2], cursor)
        return self._json(404, {"error": "not found"})

    def _events(self, ident: str, cursor: int) -> None:
        try:
            session = self.service.get(ident)
        except KeyError as exc:
            return self._json(404, {"error": str(exc)})
        cursor = max(0, cursor)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        # EventSource reconnects itself. Closing a completed HTTP/1.0 stream is
        # important for non-browser clients too; advertising keep-alive here
        # leaves response.read() waiting for bytes that will never arrive.
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            while True:
                with session.condition:
                    if cursor >= len(session.events) and session.state == "running":
                        session.condition.wait(timeout=12)
                    events = session.events[cursor:]
                    terminal = session.state != "running"
                if not events:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                for event in events:
                    raw = json.dumps(event["data"], separators=(",", ":"))
                    packet = f'id: {event["id"]}\nevent: {event["type"]}\ndata: {raw}\n\n'.encode("utf-8")
                    self.wfile.write(packet)
                    self.wfile.flush()
                    cursor += 1
                if terminal and cursor >= len(session.events):
                    self.close_connection = True
                    return
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_POST(self) -> None:
        if not self._same_origin():
            return self._json(403, {"error": "local same-origin request required"})
        try:
            body = self._body()
            if self.path == "/api/inference":
                session = self.service.start(body)
                return self._json(202, {"session_id": session.id, "events": f"/api/inference/{session.id}/events"})
            if self.path == "/api/protection/initialize":
                self._allow_fields(body, "edac_mode")
                return self._json(200, self.service.initialize_protection(body.get("edac_mode", "reference")))
            if self.path == "/api/protection/inject":
                self._allow_fields(body, "error_percent", "seed")
                return self._json(200, self.service.protection.inject(
                    body.get("error_percent", 0.0), body.get("seed", 20261023)))
            if self.path == "/api/protection/check":
                self._allow_fields(body, "threshold", "parity_source")
                return self._json(200, self.service.check_protection(
                    body.get("threshold"), body.get("parity_source", "host")))
            if self.path == "/api/protection/repair":
                self._allow_fields(body, "threshold", "parity_source")
                return self._json(200, self.service.repair_protection(
                    body.get("threshold"), body.get("parity_source", "host")))
            if self.path in ("/api/hardware/parity-program", "/api/memory-map/program"):
                self._allow_fields(body)
                return self._json(202, self.service.start_bitmap_program())
            if self.path in ("/api/hardware/parity-map/read", "/api/memory-map/read"):
                self._allow_fields(body, "simulation")
                return self._json(202, self.service.start_parity_read(body.get("simulation", False)))
            if self.path in ("/api/hardware/parity-map/cancel", "/api/memory-map/cancel"):
                self._allow_fields(body)
                return self._json(202, self.service.cancel_parity_read())
            parts = [part for part in urlparse(self.path).path.split("/") if part]
            if len(parts) == 4 and parts[:2] == ["api", "inference"] and parts[3] == "cancel":
                self._allow_fields(body)
                session = self.service.cancel(parts[2])
                return self._json(202, {"session_id": session.id, "state": "cancelling"})
            return self._json(404, {"error": "not found"})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return self._json(400, {"error": str(exc)})
        except RuntimeError as exc:
            return self._json(409, {"error": str(exc)})
        except KeyError as exc:
            return self._json(404, {"error": str(exc)})

    def log_message(self, *_args) -> None:
        pass


def create_server(host: str = "127.0.0.1", port: int = 8780,
                  service: InferenceService | None = None) -> ThreadingHTTPServer:
    AppHandler.service = service or InferenceService(RUNS)
    return ThreadingHTTPServer((host, port), AppHandler)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8780)
    args = parser.parse_args()
    server = create_server(port=args.port)
    print(f"ZCU106 Qwen + ZES realtime UI: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
