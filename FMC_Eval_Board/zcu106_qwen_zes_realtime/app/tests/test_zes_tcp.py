import hashlib
import socket
import struct
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faults import ZesTcpClient


HEADER = struct.Struct("!4sBBHII")


def receive_exact(connection, size):
    output = bytearray()
    while len(output) < size:
        output.extend(connection.recv(size - len(output)))
    return bytes(output)


class RelayFixture:
    def __init__(self):
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.port = self.listener.getsockname()[1]
        self.accepts = 0
        self.original = None
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        connection, _ = self.listener.accept()
        self.accepts += 1
        with connection:
            while True:
                try:
                    header = receive_exact(connection, 16)
                except Exception:
                    return
                magic, version, opcode, flags, length, request_id = HEADER.unpack(header)
                payload = receive_exact(connection, length)
                status = 0
                if opcode == 1:
                    body = struct.pack("!II", 1024, 72) + b"fixture-v1"
                elif opcode == 2:
                    self.original = payload
                    body = hashlib.shake_256(payload).digest(72)
                elif opcode == 3:
                    damaged = payload[4:1028]
                    difference = sum((a ^ b).bit_count() for a, b in zip(damaged, self.original))
                    decoder = 0 if difference == 0 else (1 if difference == 1 else 2)
                    repaired = self.original if decoder == 1 else damaged
                    body = struct.pack("!I", decoder) + repaired
                else:
                    status, body = 3, b""
                response = HEADER.pack(magic, version, opcode | 0x80, flags,
                                       4 + len(body), request_id) + struct.pack("!I", status) + body
                # Deliberately fragment every response.
                connection.sendall(response[:7]); connection.sendall(response[7:])

    def close(self):
        self.listener.close()


class ExpiringRelayFixture:
    """Serve one INFO per connection, like the relay after its idle timeout."""

    def __init__(self):
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(2)
        self.port = self.listener.getsockname()[1]
        self.accepts = 0
        self.first_closed = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        for index in range(2):
            connection, _ = self.listener.accept()
            self.accepts += 1
            with connection:
                header = receive_exact(connection, 16)
                magic, version, opcode, flags, length, request_id = HEADER.unpack(header)
                receive_exact(connection, length)
                body = struct.pack("!II", 1024, 72) + b"fixture-v1"
                response = HEADER.pack(magic, version, opcode | 0x80, flags,
                                       4 + len(body), request_id) + struct.pack("!I", 0) + body
                connection.sendall(response)
            if index == 0:
                self.first_closed.set()

    def close(self):
        self.listener.close()


class ZesTcpTests(unittest.TestCase):
    def test_persistent_info_encode_check_repair(self):
        relay = RelayFixture()
        client = ZesTcpClient("127.0.0.1", relay.port, timeout=2)
        try:
            info = client.info()
            self.assertEqual(info["vendor_version"], "fixture-v1")
            original = bytes(index & 0xFF for index in range(1024))
            parity = client.encode(original)
            damaged = bytearray(original); damaged[77] ^= 4
            decoder, repaired = client.check_repair(bytes(damaged), parity, 3)
            self.assertEqual(decoder, 1)
            self.assertEqual(repaired, original)
            self.assertEqual(relay.accepts, 1)
        finally:
            client.close(); relay.close()

    def test_threshold_policy_rejects_out_of_range_without_network(self):
        client = ZesTcpClient("127.0.0.1", 1)
        for invalid in (0, 8193, False):
            with self.assertRaisesRegex(ValueError, "1 to 8192"):
                client.check_repair(bytes(1024), bytes(72), invalid)

    def test_reconnects_once_when_idle_persistent_socket_was_closed(self):
        relay = ExpiringRelayFixture()
        client = ZesTcpClient("127.0.0.1", relay.port, timeout=2)
        try:
            self.assertEqual(client.info()["vendor_version"], "fixture-v1")
            self.assertTrue(relay.first_closed.wait(1))
            self.assertEqual(client.info()["vendor_version"], "fixture-v1")
            self.assertEqual(relay.accepts, 2)
        finally:
            client.close(); relay.close()


if __name__ == "__main__":
    unittest.main()
