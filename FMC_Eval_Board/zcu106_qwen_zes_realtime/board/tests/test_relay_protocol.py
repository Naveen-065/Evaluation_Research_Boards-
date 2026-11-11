#!/usr/bin/env python3
"""End-to-end protocol test using the native stub relay binary."""

from __future__ import annotations

import argparse
import socket
import struct
import subprocess
import time
from pathlib import Path

MAGIC = b"ZES1"
VERSION = 1
INFO = 0x01
ENCODE = 0x02
CHECK_REPAIR = 0x03


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def receive_exact(connection: socket.socket, size: int) -> bytes:
    output = bytearray()
    while len(output) < size:
        chunk = connection.recv(size - len(output))
        if not chunk:
            raise RuntimeError("relay closed the socket mid-frame")
        output.extend(chunk)
    return bytes(output)


def transact(connection: socket.socket, opcode: int, request_id: int, payload: bytes) -> tuple[int, bytes]:
    header = struct.pack("!4sBBHII", MAGIC, VERSION, opcode, 0, len(payload), request_id)
    # Deliberately fragment the TCP write so the relay's read_exact loop is
    # exercised across header and payload boundaries.
    packet = header + payload
    sizes = (1, 2, 5, 13, 31, 127)
    offset = 0
    fragment = 0
    while offset < len(packet):
        end = min(len(packet), offset + sizes[fragment % len(sizes)])
        connection.sendall(packet[offset:end])
        offset = end
        fragment += 1
    response_header = receive_exact(connection, 16)
    magic, version, response_opcode, flags, length, response_id = struct.unpack(
        "!4sBBHII", response_header
    )
    assert magic == MAGIC
    assert version == VERSION
    assert response_opcode == opcode | 0x80
    assert flags == 0
    assert response_id == request_id
    response = receive_exact(connection, length)
    status = struct.unpack("!I", response[:4])[0]
    return status, response[4:]


def run_test(binary: Path) -> None:
    port = free_port()
    process = subprocess.Popen(
        [str(binary), "--bind", "127.0.0.1", "--port", str(port), "--once"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 5.0
        while True:
            try:
                connection = socket.create_connection(("127.0.0.1", port), timeout=1.0)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)

        with connection:
            status, info = transact(connection, INFO, 1, b"")
            assert status == 0
            data_bytes, parity_bytes = struct.unpack("!II", info[:8])
            assert (data_bytes, parity_bytes) == (1024, 72)
            assert info[8:] == b"protocol-test-stub-1"

            original = bytes((index * 37 + 11) & 0xFF for index in range(1024))
            status, parity = transact(connection, ENCODE, 2, original)
            assert status == 0
            assert len(parity) == 72

            damaged = bytearray(original)
            damaged[617] ^= 0x20
            repair_request = struct.pack("!I", 3) + bytes(damaged) + parity
            status, repair = transact(connection, CHECK_REPAIR, 3, repair_request)
            assert status == 0
            decoder_result = struct.unpack("!I", repair[:4])[0]
            assert decoder_result == 1
            assert repair[4:] == original

            status, _ = transact(connection, ENCODE, 4, b"too short")
            assert status == 4
    finally:
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5.0)

    if process.returncode != 0:
        stderr = process.stderr.read() if process.stderr else ""
        raise RuntimeError(f"relay exited with {process.returncode}: {stderr}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    arguments = parser.parse_args()
    run_test(arguments.binary.resolve())
    print("relay protocol test: PASS")


if __name__ == "__main__":
    main()
