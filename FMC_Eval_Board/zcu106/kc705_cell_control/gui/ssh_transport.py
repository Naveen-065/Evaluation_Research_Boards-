"""Bounded SSH startup retries. Never replay a command after an uncertain launch."""
import os
import re
import subprocess
import time

CONNECT_TIMEOUT_SECONDS = 30
MAX_CONNECT_ATTEMPTS = 3

# Match only diagnostics emitted by OpenSSH before authentication/remote exec.
# An arbitrary exit 255, a broken pipe, or any Vivado output is NOT retryable.
_PRELAUNCH_LINES = [
    re.compile(r"Connection timed out during banner exchange"),
    re.compile(r"Connection to .+ port \d+ timed out"),
    re.compile(r"ssh: connect to host .+ port \d+: "
               r"(?:Connection timed out|Connection refused|No route to host|Network is unreachable)"),
    re.compile(r"channel \d+: open failed: connect failed: "
               r"(?:Connection timed out|Connection refused|No route to host|Network is unreachable)"),
    re.compile(r"stdio forwarding failed"),
    re.compile(r"kex_exchange_identification: Connection closed by remote host"),
    re.compile(r"Connection closed by UNKNOWN port 65535"),
]


def confirmed_prelaunch_failure(code, lines):
    """Require exclusively recognized connection diagnostics, with positive proof."""
    text = [line.strip() for line in lines if line.strip()]
    positive = any(
        line == "Connection timed out during banner exchange"
        or line.startswith(("ssh: connect to host ", "channel "))
        for line in text
    )
    return (code == 255 and positive and
            all(any(pattern.fullmatch(line) for pattern in _PRELAUNCH_LINES) for line in text))


class RemoteRun:
    def __init__(self, command, job, log, update):
        self.command, self.job, self.log, self.update = command, job, log, update
        self.process = None
        self.returncode = None
        self.prelaunch_failure = False
        self.cancelled_before_launch = False
        self.last_lines = []

    def __iter__(self):
        for attempt in range(1, MAX_CONNECT_ATTEMPTS + 1):
            if self.job.get("cancel_requested"):
                self.cancelled_before_launch = True
                self.returncode = 255
                return
            self.job["connection_attempt"] = attempt
            self.job["max_connection_attempts"] = MAX_CONNECT_ATTEMPTS
            self.update(f"Connecting to FPGA PC (attempt {attempt}/{MAX_CONNECT_ATTEMPTS})…")
            self.log.write(f"API_SSH_ATTEMPT {attempt}/{MAX_CONNECT_ATTEMPTS}\n")
            self.log.flush()
            self.last_lines = []
            self.process = subprocess.Popen(
                self.command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            for line in self.process.stdout:
                self.log.write(line)
                self.log.flush()
                self.last_lines.append(line)
                yield line
            self.returncode = self.process.wait()
            self.prelaunch_failure = confirmed_prelaunch_failure(self.returncode, self.last_lines)
            if not self.prelaunch_failure or attempt == MAX_CONNECT_ATTEMPTS:
                return
            self.update(
                f"SSH connection timed out or was unavailable before Vivado started; "
                f"retrying connection ({attempt + 1}/{MAX_CONNECT_ATTEMPTS}). No hardware command was sent.")
            # Short bounded backoff, interruptible by Stop. No programming retry.
            for _ in range(attempt * 20):
                if self.job.get("cancel_requested"):
                    self.cancelled_before_launch = True
                    return
                time.sleep(0.1)

    def failure_message(self):
        if self.cancelled_before_launch:
            return "Cancelled before connecting to the FPGA PC; no hardware command was sent."
        if self.prelaunch_failure:
            return (f"Could not connect to the FPGA PC after {self.job['connection_attempt']} attempts. "
                    "Vivado did not start; no hardware command was sent. "
                    "Check the Ubuntu VM and FPGA PC network, then use Check bench.")
        if self.returncode == 255:
            return ("SSH connection to the FPGA PC was lost or failed (exit 255). "
                    "The run was not retried because remote execution may have started. "
                    "Inspect the run log and confirm hardware cleanup before another operation.")
        return f"Hardware process exited {self.returncode}"
