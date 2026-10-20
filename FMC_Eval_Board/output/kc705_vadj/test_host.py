"""Offline Tcl/Vivado API mocks. This script never contacts the FPGA or network."""
from pathlib import Path
import tkinter


def crc8(data):
    value = 0
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = ((value << 1) ^ (7 if value & 128 else 0)) & 255
    return value


class MockHardware:
    def __init__(self):
        self.tcl = tkinter.Tcl()
        self.status = 0
        self.output = "0" * 32
        self.commits = []
        self.page = 3
        self.mode = 0x14
        self.registers = {0x21: 0x2800}
        self.raw_read = None
        self.bad_pec = False
        self.forced_error = 0
        self.forced_ack = None
        for name in (
            "open_hw_manager", "connect_hw_server", "current_hw_target",
            "open_hw_target", "current_hw_device", "refresh_hw_device",
            "refresh_hw_vio", "close_hw_target", "disconnect_hw_server",
            "close_hw_manager",
        ):
            self.tcl.createcommand(name, lambda *args: "")
        self.tcl.createcommand("get_hw_targets", lambda *args: "mock_target")
        self.tcl.createcommand("get_hw_devices", lambda *args: "mock_device")
        self.tcl.createcommand("get_hw_vios", lambda *args: "mock_vio")
        self.tcl.createcommand("get_hw_probes", self.get_probes)
        self.tcl.createcommand("set_property", self.set_property)
        self.tcl.createcommand("get_property", self.get_property)
        self.tcl.createcommand("commit_hw_vio", self.commit)
        self.tcl.call("source", str(Path(__file__).with_name("pmbus_host.tcl")))

    def get_probes(self, *args):
        return "cmdprobe" if "vio_output" in args[-1] else "statprobe"

    def set_property(self, name, value, obj):
        if name == "OUTPUT_VALUE":
            self.output = value
        return ""

    def get_property(self, name, obj):
        assert name == "INPUT_VALUE" and obj == "statprobe"
        return f"{self.status:032x}"

    def commit(self, obj):
        assert obj == "cmdprobe"
        value = int(self.output, 16)
        token = value & 255
        address = (value >> 8) & 127
        nw, nr = (value >> 15) & 15, (value >> 19) & 15
        written = [(value >> (23 + 8 * i)) & 255 for i in range(nw)]
        self.commits.append((token, address, written, nr, self.output))
        if self.raw_read is not None:
            received = self.raw_read[:nr]
        elif nr:
            register = written[0]
            result = self.page if register == 0 else self.mode if register == 0x20 else self.registers.get(register, 0)
            received = [result & 255, result >> 8]
            if nr == 3:
                pec = crc8([address << 1, register, (address << 1) | 1, *received])
                received.append(pec ^ self.bad_pec)
            received = received[:nr]
        else:
            received = []
            if nw == 2 and written[0] == 0:
                self.page = written[1]
            elif nw == 4:
                assert written[-1] == crc8([address << 1, *written[:-1]])
                self.registers[written[0]] = written[1] | (written[2] << 8)
        ack = nw if self.forced_ack is None else self.forced_ack
        self.status = token | (ack << 80)
        for index, byte in enumerate(received):
            self.status |= byte << (16 + 8 * index)
        if self.forced_error:
            self.status |= 512 | (self.forced_error << 10)
        return ""


count = 0


def check(condition, description):
    global count
    assert condition, description
    count += 1
    print(f"PASS {description}")


def expect_error(mock, command, substring):
    try:
        mock.tcl.eval(command)
    except tkinter.TclError as error:
        check(substring in str(error), f"{command}: rejects with {substring}")
    else:
        raise AssertionError(f"Expected an error: {command}")


mock = MockHardware()
tcl = mock.tcl
check(mock.commits == [], "sourcing host script generates no bus transactions")
for integer in (0, 1, 1 << 64, (1 << 127) + 0x1234, (1 << 128) - 1):
    result = tcl.call("to_hex128", str(integer))
    check(result == f"{integer:032x}", f"128-bit serialization of {integer:x}")
expect_error(mock, f"to_hex128 {1 << 128}", "overflow")
expect_error(mock, "to_hex128 -1", "overflow")

mock.raw_read = [0x00, 0x28, 0x23, 0x45, 0x67, 0x89, 0xab, 0xcd]
tcl.eval("set token 254")
result = tcl.eval("transfer {0x01 0x23 0x45 0x67 0x89 0xab 0xcd 0xef} 8")
check([int(x) for x in result.split()] == mock.raw_read, "all eight status bytes decoded in order")
last = mock.commits[-1]
check(last[:4] == (255, 0x34, [1, 0x23, 0x45, 0x67, 0x89, 0xab, 0xcd, 0xef], 8), "128-bit command layout and upper payload bits")
tcl.eval("transfer {0x21} 2")
check(mock.commits[-1][0] == 1, "token wraps 255 to 1 without zero")
mock.raw_read = None
check(int(tcl.eval("rw 0x21")) == 0x2800, "word decoding little endian")
check(int(tcl.eval("crc8 {49 50 51 52 53 54 55 56 57}")) == 0xf4, "CRC-8 known 123456789 vector")
check(int(tcl.eval("rw_pec 0x21")) == 0x2800, "read PEC includes address W, command, address R and word")
mock.bad_pec = True
expect_error(mock, "rw_pec 0x21", "PEC mismatch")
mock.bad_pec = False

before = len(mock.commits)
expect_error(mock, "write_vadj_word 0x01 7373", "not permitted")
check(len(mock.commits) == before, "forbidden register causes zero bus traffic")
check(int(tcl.eval("write_vadj_word 0x21 7373")) == 7373, "hex register 0x21 normalized and permitted 1.8 V value verified")
word_write = next(item for item in reversed(mock.commits) if item[3] == 0)
check(word_write[2][:3] == [0x21, 0xcd, 0x1c], "write word payload little endian")
check(word_write[2][3] == crc8([0x68, 0x21, 0xcd, 0x1c]), "write PEC covers address and all payload bytes")
expect_error(mock, "write_vadj_word 0x21 10240", "Only 1.8 V")
expect_error(mock, "write_vadj_word 0x24 13109", "outside guarded range")
expect_error(mock, "write_vadj_word 0x24 -1", "outside guarded range")
mock.page = 2
expect_error(mock, "write_vadj_word 0x21 7373", "page/mode guard")
mock.page = 3
mock.mode = 0x13
expect_error(mock, "write_vadj_word 0x21 7373", "page/mode guard")
mock.mode = 0x14
tcl.eval("page 3")
check(mock.page == 3, "PAGE write and readback")
expect_error(mock, "page 4", "Invalid U55 page")
expect_error(mock, "transfer {} 0", "Bad transaction length")
expect_error(mock, "transfer {0 1 2 3 4 5 6 7 8} 0", "Bad transaction length")
expect_error(mock, "transfer {0} 9", "Bad transaction length")
expect_error(mock, "transfer {256} 0", "Bad byte")
before = len(mock.commits)
mock.status |= 256
expect_error(mock, "transfer {0x21} 2", "already busy")
check(len(mock.commits) == before, "busy bridge rejected before commit")
mock.status &= ~256
mock.forced_error = 5
expect_error(mock, "transfer {0x21} 2", "code=5")
mock.forced_error = 0
mock.forced_ack = 0
expect_error(mock, "transfer {0x21} 2", "Incomplete write ACK count")
print(f"ALL {count} HOST TESTS PASSED; offline mocks only")
