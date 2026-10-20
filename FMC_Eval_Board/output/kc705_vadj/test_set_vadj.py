"""Offline end-to-end tests of the exact VADJ Tcl script; never accesses hardware."""
from pathlib import Path
import shutil
import tempfile
import tkinter
import re

BASE = Path(__file__).parent
BYTE_REGS = [0x01, 0x02, 0x20, 0x41, 0x45, 0x7a, 0x7b, 0x7c, 0x7d, 0x7e, 0x80]
WORD_REGS = [0x21, 0x23, 0x24, 0x25, 0x26, 0x27, 0x29, 0x2a, 0x40, 0x42, 0x43, 0x44,
             0x48, 0x5e, 0x5f, 0x60, 0x61, 0x62, 0x64, 0x65, 0x66, 0x79, 0x8b]


def crc8(data):
    value = 0
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = ((value << 1) ^ (7 if value & 128 else 0)) & 255
    return value


class Controller:
    def __init__(self, low_pg=False):
        self.page = 0
        self.regs = {}
        self.writes = []
        self.transactions = []
        self.status = 0
        self.output = "0" * 32
        self.fail_telemetry = False
        self.bad_pec = False
        self.bad_id = False
        self.printed = []
        self.tcl = tkinter.Tcl()
        for pg, volts in enumerate([1.0, 1.8, 1.5, 2.5]):
            for reg in BYTE_REGS + WORD_REGS:
                self.regs[pg, reg] = 0
            self.regs[pg, 1] = 0x80
            self.regs[pg, 2] = 0x18
            self.regs[pg, 0x20] = 0x14
            self.regs[pg, 0x21] = round(volts * 4096)
            self.regs[pg, 0x8b] = round(volts * 4096)
            self.regs[pg, 0x24] = 13107
            for reg, ratio in {0x25: 1.05, 0x26: .95, 0x40: 1.15, 0x42: 1.10,
                               0x43: .90, 0x44: .85, 0x48: .87, 0x5e: .90, 0x5f: .85}.items():
                self.regs[pg, reg] = round(volts * ratio * 4096)
        if low_pg:
            self.regs[3, 0x5e] = round(1.5 * 4096)
            self.regs[3, 0x5f] = round(1.4 * 4096)
        for command in ("open_hw_manager", "connect_hw_server", "current_hw_target",
                        "open_hw_target", "current_hw_device", "refresh_hw_device",
                        "refresh_hw_vio", "close_hw_target", "disconnect_hw_server",
                        "close_hw_manager"):
            self.tcl.createcommand(command, lambda *args: "")
        self.tcl.createcommand("get_hw_targets", lambda *args: "target")
        self.tcl.createcommand("get_hw_devices", lambda *args: "device")
        self.tcl.createcommand("get_hw_vios", lambda *args: "vio")
        self.tcl.createcommand("get_hw_probes", lambda *args: "cmd" if "vio_output" in args[-1] else "stat")
        self.tcl.createcommand("set_property", self.set_property)
        self.tcl.createcommand("get_property", lambda *args: f"{self.status:032x}")
        self.tcl.createcommand("commit_hw_vio", self.commit)
        self.tcl.createcommand("after", lambda *args: "")
        self.tcl.eval("rename puts original_puts")
        self.tcl.createcommand("capture_stdout", lambda text: self.printed.append(text) or "")
        self.tcl.eval("proc puts {args} {if {[llength $args] == 1} {capture_stdout [lindex $args 0]} else {original_puts {*}$args}}")

    def set_property(self, name, value, obj):
        if name == "OUTPUT_VALUE":
            self.output = value
        return ""

    def commit(self, *args):
        raw = int(self.output, 16)
        token = raw & 255
        address = (raw >> 8) & 127
        assert address == 0x34
        nw, nr = (raw >> 15) & 15, (raw >> 19) & 15
        data = [(raw >> (23 + i*8)) & 255 for i in range(nw)]
        self.transactions.append((self.page, data, nr))
        result = []
        if nr:
            reg = data[0]
            if reg == 253:
                result = [7, *b"UCD9248"]
                if self.bad_id:
                    result[1] = 0
            elif reg == 210:
                result = [4, 1, 4, 16, 64]
            else:
                value = self.page if reg == 0 else self.regs[self.page, reg]
                result = [value & 255, value >> 8]
                if nr == 3:
                    result.append(crc8([0x68, reg, 0x69, *result]) ^ self.bad_pec)
                result = result[:nr]
        elif len(data) == 2 and data[0] == 0:
            self.page = data[1]
        else:
            assert len(data) == 4 and data[-1] == crc8([0x68, *data[:-1]])
            reg, value = data[0], data[1] | data[2] << 8
            self.writes.append((self.page, reg, value))
            self.regs[self.page, reg] = value
            if reg == 0x21 and not self.fail_telemetry:
                self.regs[self.page, 0x8b] = value
        self.status = token | (nw << 80)
        for index, value in enumerate(result):
            self.status |= value << (16 + index*8)
        return ""

    def baseline(self):
        return "DEVICE_ID_FIRST_BYTES=30 85 67 68 57 50 52 56\nPHASE_INFO=4 1 4 16 64\n" + "\n".join(
            f"PAGE={pg} {kind} 0x{reg:02x}=0x{self.regs[pg, reg]:04x}"
            for pg in range(4) for kind, registers in [("BYTE", BYTE_REGS), ("WORD", WORD_REGS)]
            for reg in registers
        )

    def run(self, baseline=None):
        with tempfile.TemporaryDirectory(prefix="kc705_vadj_offline_", dir=BASE.resolve()) as directory:
            folder = Path(directory).resolve()
            assert folder.parent == BASE.resolve(), "Temporary cleanup must remain inside the test workspace"
            for filename in ("pmbus_host.tcl", "set_vadj_1p8.tcl"):
                shutil.copyfile(BASE / filename, folder / filename)
            (folder / "controller_before.txt").write_text(self.baseline() if baseline is None else baseline)
            error = None
            try:
                self.tcl.call("source", str(folder / "set_vadj_1p8.tcl"))
            except tkinter.TclError as exc:
                error = str(exc)
            finally:
                self.tcl.eval("catch {close $log}")
            return error


def check(condition, message):
    assert condition, message
    print("PASS", message)


for low_pg in [False, True]:
    ctrl = Controller(low_pg)
    original = ctrl.regs.copy()
    check(ctrl.run() is None, f"exact Tcl script completes with low_pg={low_pg}")
    order = [0x44, 0x43, 0x48] + ([] if low_pg else [0x5f, 0x5e]) + [0x21, 0x26, 0x25, 0x42, 0x40]
    check([reg for pg, reg, val in ctrl.writes] == order, "UV/PG precede VOUT, then margin and OV writes")
    check(all(pg == 3 for pg, reg, value in ctrl.writes), "voltage-setting mutations confined to PAGE3")
    check(ctrl.regs[3, 0x21] == 7373, "VOUT_COMMAND is exactly7373")
    check(all(ctrl.regs[key] == value for key, value in original.items() if key[0] != 3), "all other pages remain identical")
    check(ctrl.printed[-1] == "VADJ_VOLATILE_CHANGE_OK_NOT_STORED_TO_FLASH", "final validation succeeds with success marker")
    check(len([line for line in ctrl.printed if line.startswith("VERIFIED")]) == 104, "verifies all26 saved settings on all4 pages")

ctrl = Controller()
baseline = ctrl.baseline()
ctrl.regs[1, 0x27] = 1
check("changed since baseline" in ctrl.run(baseline) and not ctrl.writes, "changed baseline setting aborts before voltage writes")
ctrl = Controller()
ctrl.bad_pec = True
check("PEC mismatch" in ctrl.run() and not ctrl.writes, "bad PEC aborts before voltage writes")
ctrl = Controller()
baseline = ctrl.baseline().replace("DEVICE_ID_FIRST_BYTES=30 85", "DEVICE_ID_FIRST_BYTES=30 00")
check("identify UCD9248" in ctrl.run(baseline) and not ctrl.writes, "incorrect baseline controller ID aborts before voltage writes")
ctrl = Controller()
ctrl.regs[3, 0x7a] = 1
check("Existing voltage" in ctrl.run() and not ctrl.writes, "existing voltage fault aborts before voltage writes")
ctrl = Controller()
check("Incomplete baseline" in ctrl.run("\n".join(ctrl.baseline().splitlines()[:-1])) and not ctrl.writes,
      "incomplete136-entry baseline rejected")
ctrl = Controller()
ctrl.regs[3, 0x42] = 1
check("OV/UV ordering" in ctrl.run() and not ctrl.writes, "invalid threshold ordering rejected before voltage writes")
ctrl = Controller()
ctrl.fail_telemetry = True
check("notwithin3" in ctrl.run().replace(" ", "") and [reg for pg, reg, val in ctrl.writes] == [0x44, 0x43, 0x48, 0x5f, 0x5e, 0x21],
      "failed post-change telemetry prevents all margin/OV writes")

for operation in [0xa4, 0x94]:
    ctrl = Controller()
    ctrl.regs[3, 1] = operation
    check("margin mode" in ctrl.run() and not ctrl.writes, f"margin mode0x{operation:02x} rejected before voltage writes")
for operation in [0, 0x40]:
    ctrl = Controller()
    ctrl.regs[3, 1] = operation
    check(ctrl.run() is None, f"non-margin OPERATION0x{operation:02x} accepted when telemetry verifies rail is on")

# Exercise captured hardware settings without contacting hardware. Preserve saved
# CML=0x02 in the baseline; live mock status is cleared as in the diagnostic run.
actual_baseline = (BASE / "controller_before.txt").read_text()
ctrl = Controller()
for pg, kind, reg, value in re.findall(r"PAGE=([0-3]) (BYTE|WORD) (0x[0-9a-f]+)=(0x[0-9a-f]+)", actual_baseline):
    ctrl.regs[int(pg), int(reg, 16)] = int(value, 16)
for pg in range(4):
    ctrl.regs[pg, 0x7e] = 0
check(ctrl.run(actual_baseline) is None, "captured actual136-entry baseline completes with cleared live CML")
check([reg for pg, reg, value in ctrl.writes] == [0x44, 0x43, 0x48, 0x21, 0x26, 0x25, 0x42, 0x40],
      "actual baseline preserves compatible PG thresholds and lowers0x48 before VOUT")
check(abs(ctrl.regs[3, 0x48]/4096 - 1.566) < .001, "actual foldback voltage scales to1.566V")
check(not any(data[0] == 253 for page, data, nr in ctrl.transactions), "change script never truncates another controller ID read")
print("ALL OFFLINE VADJ SCRIPT TESTS PASSED")
