"""Fault injection and EDAC backends for one protected 1 KiB block.

The module intentionally keeps the reference implementation independent of
the FPGA.  A board-backed EDAC service can be selected explicitly, but no
board result is fabricated when that relay is unavailable.
"""

from __future__ import annotations

import random
import socket
import struct
import threading
from dataclasses import asdict, dataclass
from typing import Protocol


PROTECTED_BLOCK_BYTES = 1024
PROTECTED_BLOCK_BITS = PROTECTED_BLOCK_BYTES * 8


@dataclass(frozen=True)
class FaultInjection:
    requested_percent: float
    actual_percent: float
    total_bits: int
    injected_bits: int
    bit_positions: tuple[int, ...]
    corrupted: bytes

    def public(self) -> dict:
        data = asdict(self)
        data.pop("corrupted")
        # Do not make a normal API event enormous at high BER.
        positions = data.pop("bit_positions")
        data["bit_positions_preview"] = list(positions[:64])
        data["bit_positions_truncated"] = len(positions) > 64
        return data


@dataclass(frozen=True)
class EdacResult:
    backend: str
    outcome: str
    detected: bool
    corrected: bool
    injected_bits: int
    residual_bits: int
    output: bytes
    note: str

    def public(self) -> dict:
        data = asdict(self)
        data.pop("output")
        return data


class EdacBackend(Protocol):
    name: str

    def process(self, original: bytes, injection: FaultInjection) -> EdacResult:
        """Return the protected block and an evidence-labelled outcome."""


def _validate_block(block: bytes) -> None:
    if len(block) != PROTECTED_BLOCK_BYTES:
        raise ValueError(f"protected block must contain exactly {PROTECTED_BLOCK_BYTES} bytes")


def bit_error_count(left: bytes, right: bytes) -> int:
    if len(left) != len(right):
        raise ValueError("blocks have different lengths")
    return sum((a ^ b).bit_count() for a, b in zip(left, right))


def inject_faults(block: bytes, error_percent: float, seed: int) -> FaultInjection:
    """Flip an exact deterministic number of unique bits in ``block``.

    ``error_percent`` is BER over all 8192 protected bit positions.  The
    actual percentage is returned because a 1 KiB block has finite
    resolution: one bit is approximately 0.012207 percent.
    """

    _validate_block(block)
    if not isinstance(error_percent, (int, float)) or isinstance(error_percent, bool):
        raise ValueError("error_percent must be numeric")
    error_percent = float(error_percent)
    if not 0.0 <= error_percent <= 100.0:
        raise ValueError("error_percent must be between 0 and 100")
    if not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed <= 0xFFFFFFFF:
        raise ValueError("seed must be an integer from 0 to 4294967295")

    count = int(error_percent * PROTECTED_BLOCK_BITS / 100.0 + 0.5)
    positions = tuple(sorted(random.Random(seed).sample(range(PROTECTED_BLOCK_BITS), count)))
    damaged = bytearray(block)
    for bit in positions:
        damaged[bit >> 3] ^= 1 << (bit & 7)
    actual = count * 100.0 / PROTECTED_BLOCK_BITS
    return FaultInjection(error_percent, actual, PROTECTED_BLOCK_BITS, count, positions, bytes(damaged))


class NoEdacBackend:
    name = "none"

    def process(self, original: bytes, injection: FaultInjection) -> EdacResult:
        _validate_block(original)
        residual = bit_error_count(original, injection.corrupted)
        return EdacResult(self.name, "unprotected" if residual else "clean", bool(residual), False,
                          injection.injected_bits, residual, injection.corrupted,
                          "Faults pass through without correction.")


class ReferenceEdacBackend:
    """Transparent, deliberately bounded software reference.

    This mock models single-bit correction for one protected block.  It is
    useful for UI and orchestration verification, but is not claimed to be
    the proprietary ZES algorithm.
    """

    name = "reference-single-bit"

    def process(self, original: bytes, injection: FaultInjection) -> EdacResult:
        _validate_block(original)
        errors = bit_error_count(original, injection.corrupted)
        if errors == 0:
            return EdacResult(self.name, "clean", False, False, 0, 0, original,
                              "No fault was injected.")
        if errors == 1:
            return EdacResult(self.name, "corrected", True, True, 1, 0, original,
                              "Reference mock corrected one bit in the 1 KiB block.")
        return EdacResult(self.name, "detected-uncorrectable", True, False, errors, errors,
                          injection.corrupted,
                          "Reference mock detects, but does not correct, multiple bits in one block.")


class ZesTcpClient:
    """Persistent client for ``board/PROTOCOL.md`` binary ZES1 framing."""

    MAGIC = b"ZES1"
    VERSION = 1
    INFO = 0x01
    ENCODE = 0x02
    CHECK_REPAIR = 0x03
    HEADER = struct.Struct("!4sBBHII")

    def __init__(self, host: str, port: int = 9106, timeout: float = 10.0):
        if not host:
            raise ValueError("ZES relay host is required")
        self.host, self.port, self.timeout = host, int(port), float(timeout)
        self._socket: socket.socket | None = None
        self._request_id = 0
        self._lock = threading.RLock()

    def close(self) -> None:
        with self._lock:
            if self._socket is not None:
                try:
                    self._socket.close()
                finally:
                    self._socket = None

    @staticmethod
    def _receive_exact(connection: socket.socket, size: int) -> bytes:
        output = bytearray()
        while len(output) < size:
            chunk = connection.recv(size - len(output))
            if not chunk:
                raise RuntimeError("ZES relay closed the connection mid-frame")
            output.extend(chunk)
        return bytes(output)

    def _connect(self) -> socket.socket:
        if self._socket is None:
            self._socket = socket.create_connection((self.host, self.port), timeout=self.timeout)
            self._socket.settimeout(self.timeout)
        return self._socket

    def _transact(self, opcode: int, payload: bytes) -> bytes:
        with self._lock:
            self._request_id = (self._request_id + 1) & 0xFFFFFFFF
            request_id = self._request_id
            frame = self.HEADER.pack(self.MAGIC, self.VERSION, opcode, 0,
                                     len(payload), request_id) + payload
            for attempt in range(2):
                try:
                    connection = self._connect()
                    connection.sendall(frame)
                    header = self._receive_exact(connection, self.HEADER.size)
                    magic, version, response_opcode, flags, length, response_id = self.HEADER.unpack(header)
                    if (magic, version, response_opcode, flags, response_id) != (
                            self.MAGIC, self.VERSION, opcode | 0x80, 0, request_id):
                        raise RuntimeError("ZES relay response header mismatch")
                    if not 4 <= length <= 4096:
                        raise RuntimeError("ZES relay response length is invalid")
                    response = self._receive_exact(connection, length)
                    break
                except (OSError, RuntimeError):
                    # The relay deliberately expires idle client sessions.  A
                    # cached TCP socket can therefore look healthy until the
                    # next request.  All protocol operations are pure, so one
                    # reconnect/retry is safe even if the disconnect happened
                    # after the relay received the frame.
                    self.close()
                    if attempt == 1:
                        raise
            status = struct.unpack("!I", response[:4])[0]
            if status:
                raise RuntimeError(f"ZES relay rejected opcode 0x{opcode:02X} with status {status}")
            return response[4:]

    def info(self) -> dict:
        payload = self._transact(self.INFO, b"")
        if len(payload) < 8:
            raise RuntimeError("ZES INFO response is truncated")
        data_bytes, parity_bytes = struct.unpack("!II", payload[:8])
        if (data_bytes, parity_bytes) != (1024, 72):
            raise RuntimeError(f"unsupported ZES geometry {data_bytes}/{parity_bytes}")
        return {"data_bytes": data_bytes, "parity_bytes": parity_bytes,
                "vendor_version": payload[8:].decode("utf-8", errors="replace"),
                "host": self.host, "port": self.port, "protocol": "ZES1/v1"}

    def encode(self, data: bytes) -> bytes:
        _validate_block(data)
        parity = self._transact(self.ENCODE, data)
        if len(parity) != 72:
            raise RuntimeError(f"ZES ENCODE returned {len(parity)} bytes instead of 72")
        return parity

    def check_repair(self, data: bytes, parity: bytes, threshold: int) -> tuple[int, bytes]:
        _validate_block(data)
        if len(parity) != 72:
            raise ValueError("ZES parity must contain exactly 72 opaque bytes")
        if (not isinstance(threshold, int) or isinstance(threshold, bool) or
                not 1 <= threshold <= PROTECTED_BLOCK_BITS):
            raise ValueError("ZES threshold must be an integer from 1 to 8192")
        payload = self._transact(self.CHECK_REPAIR, struct.pack("!I", threshold) + data + parity)
        if len(payload) != 1028:
            raise RuntimeError("ZES CHECK_REPAIR response has an invalid length")
        decoder_result = struct.unpack("!I", payload[:4])[0]
        if decoder_result not in (0, 1, 2):
            raise RuntimeError(f"ZES decoder returned unknown result {decoder_result}")
        return decoder_result, payload[4:]

    def safe_info(self) -> dict:
        try:
            return {"available": True, **self.info()}
        except Exception as exc:
            return {"available": False, "host": self.host, "port": self.port,
                    "protocol": "ZES1/v1", "error": str(exc)}


class BoardRelayEdacBackend:
    """Compatibility adapter for one-shot injection experiments."""

    name = "board-zes1"

    def __init__(self, client: ZesTcpClient, threshold: int = 3):
        self.client, self.threshold = client, threshold

    def process(self, original: bytes, injection: FaultInjection) -> EdacResult:
        parity = self.client.encode(original)
        decoder, output = self.client.check_repair(injection.corrupted, parity, self.threshold)
        residual = bit_error_count(original, output)
        outcomes = {0: "clean", 1: "corrected", 2: "detected-uncorrectable"}
        return EdacResult(self.name, outcomes[decoder], decoder != 0, decoder == 1,
                          injection.injected_bits, residual, output,
                          "Outcome returned by the ZCU106 AArch64 ZES relay.")


def backend_for(mode: str, board_client: ZesTcpClient | None = None) -> EdacBackend:
    if mode == "none":
        return NoEdacBackend()
    if mode == "reference":
        return ReferenceEdacBackend()
    if mode == "board":
        if not board_client:
            raise ValueError("board EDAC mode is unavailable until ZES_EDAC_HOST is configured")
        return BoardRelayEdacBackend(board_client)
    raise ValueError("edac_mode must be none, reference, or board")
