"""Offline tests of STORE_DEFAULT_ALL guards; no network or hardware access."""
from pathlib import Path
import re
import shutil
import tempfile
import tkinter

BASE = Path(__file__).resolve().parent
BASELINE = (BASE / "controller_before.txt").read_text()
CHANGED = (BASE / "change_1p8.txt").read_text()
BYTE_REGS = {0, 1, 2, 0x20, 0x41, 0x45, 0x7a, 0x7b, 0x7c, 0x7d, 0x7e, 0x80}


def crc8(data):
    result = 0
    for value in data:
        result ^= value
        for _ in range(8):
            result = ((result << 1) ^ (7 if result & 128 else 0)) & 255
    return result


class Mock:
    def __init__(self):
        self.tcl = tkinter.Tcl()
        self.regs = {}
        for pg, kind, reg, value in re.findall(r"VERIFIED PAGE=([0-3]) (BYTE|WORD) (0x[0-9a-f]+)=(0x[0-9a-f]+)", CHANGED):
            self.regs[int(pg), int(reg, 16)] = int(value, 16)
        for pg in range(4):
            self.regs[pg, 0x8b] = self.regs[pg, 0x21]
            for reg in [0x79, 0x7a, 0x7b, 0x7c, 0x7d, 0x7e, 0x80]:
                self.regs[pg, reg] = 0
        self.page = 0
        self.status = 0
        self.output = "0" * 32
        self.events = []
        self.store_count = 0
        self.post_mismatch = False
        self.post_fault = False
        self.store_nack = False
        self.bad_pec = False
        self.bad_phase = False
        self.connected = False
        self.log = ""
        for name in ("connect_hw_server", "current_hw_target", "open_hw_target", "current_hw_device",
                     "refresh_hw_device", "refresh_hw_vio", "close_hw_target", "disconnect_hw_server", "close_hw_manager"):
            self.tcl.createcommand(name, lambda *args: "")
        self.tcl.createcommand("open_hw_manager", self.open_manager)
        self.tcl.createcommand("get_hw_targets", lambda *args: "target")
        self.tcl.createcommand("get_hw_devices", lambda *args: "device")
        self.tcl.createcommand("get_hw_vios", lambda *args: "vio")
        self.tcl.createcommand("get_hw_probes", lambda *args: "cmd" if "vio_output" in args[-1] else "stat")
        self.tcl.createcommand("set_property", self.set_property)
        self.tcl.createcommand("get_property", lambda *args: f"{self.status:032x}")
        self.tcl.createcommand("commit_hw_vio", self.commit)
        self.tcl.createcommand("after", self.after)
        self.tcl.eval("rename puts original_puts; proc puts {args} {if {[llength $args] != 1} {original_puts {*}$args}}")

    def open_manager(self):
        self.connected = True
        return ""

    def after(self, delay):
        self.events.append(("wait", int(delay)))
        return ""

    def set_property(self, name, value, obj):
        if name == "OUTPUT_VALUE":
            self.output = value
        return ""

    def commit(self, *args):
        packed = int(self.output, 16)
        token = packed & 255
        assert (packed >> 8) & 127 == 0x34
        nw, nr = (packed >> 15) & 15, (packed >> 19) & 15
        data = [(packed >> (23 + 8*i)) & 255 for i in range(nw)]
        self.events.append(("bus", self.page, data, nr))
        result = []
        if nr:
            reg = data[0]
            if reg == 0xd2:
                result = [4, 1, 4, 16, 64 ^ self.bad_phase]
                if nr == 6:
                    result.append(crc8([0x68, reg, 0x69, *result]))
            else:
                value = self.page if reg == 0 else self.regs[self.page, reg]
                if self.store_count and self.post_mismatch and self.page == 2 and reg == 0x25:
                    value += 1
                if self.store_count and self.post_fault and reg == 0x7e:
                    value = 2
                result = [value & 255] if reg in BYTE_REGS else [value & 255, value >> 8]
                if nr > len(result):
                    result.append(crc8([0x68, reg, 0x69, *result]) ^ self.bad_pec)
                result = result[:nr]
        elif data[0] == 0:
            assert len(data) == 2
            self.page = data[1]
        else:
            assert data == [0x11, 0x2a], f"Unexpected mutation: {data}"
            self.store_count += 1
        self.status = token | (nw << 80)
        if not nr and data[0] == 0x11 and self.store_nack:
            self.status |= 512 | (5 << 10)
        for i, value in enumerate(result):
            self.status |= value << (16 + 8*i)
        return ""

    def run(self, baseline=BASELINE, changed=CHANGED, existing_log=False):
        with tempfile.TemporaryDirectory(prefix="store_offline_", dir=BASE) as folder:
            folder = Path(folder).resolve()
            assert folder.parent == BASE, "Test cleanup must remain within workspace"
            for name in ["pmbus_host.tcl", "store_vadj_1p8.tcl"]:
                shutil.copyfile(BASE / name, folder / name)
            (folder / "controller_before.txt").write_text(baseline)
            (folder / "change_1p8.txt").write_text(changed)
            if existing_log:
                (folder / "store_1p8.txt").write_text("Previous uncertain attempt\n")
            error = None
            try:
                self.tcl.call("source", str(folder / "store_vadj_1p8.tcl"))
            except tkinter.TclError as exc:
                error = str(exc)
            log_path = folder / "store_1p8.txt"
            self.log = log_path.read_text() if log_path.exists() else ""
            return error


checks = 0


def check(condition, message):
    global checks
    assert condition, message
    checks += 1
    print("PASS", message)


mock = Mock()
error = mock.run()
check(error is None, f"actual manifest passes complete store script ({error})")
check(mock.store_count == 1, "exactly one STORE_DEFAULT_ALL with PEC0x2a")
store_index = next(i for i, e in enumerate(mock.events) if e[0] == "bus" and e[2][0] == 0x11 and e[3] == 0)
check(mock.events[store_index+1] == ("wait", 2000), "controller sees2s quiet interval immediately after store")
check(len(re.findall(r"^PRE_STORE VERIFIED", mock.log, re.M)) == 104, "104 exact settings verified before store")
check(len(re.findall(r"^POST_STORE VERIFIED", mock.log, re.M)) == 104, "104 exact settings verified after store")
check("STORE_COMMAND_ACKNOWLEDGED" in mock.log and "POWER_CYCLE_PERSISTENCE_NOT_YET_VERIFIED" in mock.log,
      "log distinguishes ACK/postcheck from power-cycle persistence")
check(not any(e[0] == "bus" and e[3] == 0 and e[2][0] not in (0, 0x11) for e in mock.events),
      "no restore, voltage, operation, faultclear, or reset command")
check(not any(e[0] == "bus" and e[2][0] == 0xfd for e in mock.events), "no truncated identity read")

cases = [
    ("missing completion marker", CHANGED.replace("VADJ_VOLATILE_CHANGE_OK_NOT_STORED_TO_FLASH", "")),
    ("duplicate completion marker", CHANGED + "VADJ_VOLATILE_CHANGE_OK_NOT_STORED_TO_FLASH\n"),
    ("duplicate verified entry", CHANGED.replace("BEGIN_VOLATILE_VADJ_CHANGE", "BEGIN_VOLATILE_VADJ_CHANGE\nVERIFIED PAGE=0 WORD 0x21=0x1000")),
    ("missing verified entry", CHANGED.replace("VERIFIED PAGE=0 WORD 0x21=0x1000", "")),
    ("changed other rail manifest", CHANGED.replace("VERIFIED PAGE=0 WORD 0x21=0x1000", "VERIFIED PAGE=0 WORD 0x21=0x1001")),
    ("wrong target voltage", CHANGED.replace("VERIFIED PAGE=3 WORD 0x21=0x1ccd", "VERIFIED PAGE=3 WORD 0x21=0x2800")),
    ("wrong verified register type", CHANGED.replace("VERIFIED PAGE=0 WORD 0x21=0x1000", "VERIFIED PAGE=0 BYTE 0x21=0x1000")),
]
for name, changed in cases:
    mock = Mock()
    check(mock.run(changed=changed) is not None and not mock.connected and mock.store_count == 0, name + " rejected before connection")
for name, baseline in [
    ("wrong baseline identity", BASELINE.replace("30 85 67 68 57 50 52 56", "30 0 0 0 0 0 0 0")),
    ("wrong baseline phase", BASELINE.replace("PHASE_INFO=4 1 4 16 64", "PHASE_INFO=4 1 4 16 32")),
    ("wrong baseline address", BASELINE.replace("U55_ADDRESS=0x34", "U55_ADDRESS=0x35")),
]:
    mock = Mock()
    check(mock.run(baseline=baseline) is not None and not mock.connected, name + " rejected before connection")
mock = Mock()
check(mock.run(existing_log=True) is not None and not mock.connected, "existing attempt log blocks blind rerun before connection")
for attribute in ["bad_pec", "bad_phase"]:
    mock = Mock()
    setattr(mock, attribute, True)
    check(mock.run() is not None and mock.store_count == 0, attribute + " blocks store")
for reg in [0x79, 0x7a, 0x7b, 0x7c, 0x7d, 0x7e, 0x80]:
    mock = Mock()
    mock.regs[2, reg] = 1
    check(mock.run() is not None and mock.store_count == 0, f"nonzero status0x{reg:02x} on other rail blocks store")
mock = Mock()
mock.regs[1, 0x25] += 1
check(mock.run() is not None and mock.store_count == 0, "one-LSB setting mismatch on other rail blocks store")
mock = Mock()
mock.regs[3, 0x8b] = round(2.5*4096)
check(mock.run() is not None and mock.store_count == 0, "bad VADJ telemetry blocks store")
for attribute in ["store_nack", "post_mismatch", "post_fault"]:
    mock = Mock()
    setattr(mock, attribute, True)
    check(mock.run() is not None and mock.store_count == 1, attribute + " fails without store retry")
    check("FAILED_OR_UNCERTAIN" in mock.log and "STORE_COMMAND_ACK_AND_POSTCHECK_OK" not in mock.log,
          attribute + " retained in attempt log without false success")
print(f"ALL {checks} OFFLINE STORE TESTS PASSED")
