"""Exercise sector boundaries/readback failure without opening any USB device."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from caravel_d2xx import program

class FakeHK:
    def __init__(self, corrupt=False, jedec=b'\xef\x40\x16'):
        self.memory = bytearray([0x5A])*8192
        self.regs = {11: 0, 9: 0, 8: 1}
        self.corrupt, self.jedec = corrupt, jedec
        self.erased = False
        self.wel = False
    def identify(self): pass
    def read_reg(self, r): return self.regs[r]
    def write_reg(self, r, v): self.regs[r] = v
    def wait_ready(self, seconds=5): pass
    def write_enable(self): self.wel = True
    def flash(self, cmd, nr=0):
        if cmd == [0x9F]: return self.jedec
        if cmd == [5]: return bytes([2 if self.wel else 0])
        assert self.regs[11] == 1 and self.wel
        addr = (cmd[1]<<16) | (cmd[2]<<8) | cmd[3]
        if cmd[0] == 0x20:
            assert addr % 4096 == 0
            self.memory[addr:addr+4096] = b'\xff'*4096
            self.erased = True
        elif cmd[0] == 2:
            payload = bytes(cmd[4:])
            assert len(payload) <= 256 and addr//256 == (addr+len(payload)-1)//256
            self.memory[addr:addr+len(payload)] = payload
        else: raise AssertionError(f'Unexpected flash command {cmd[0]:02x}')
        self.wel = False
    def read_flash(self, addr, count):
        data = bytes(self.memory[addr:addr+count])
        return bytes([data[0]^1])+data[1:] if self.corrupt and self.erased else data

class FlashTests(unittest.TestCase):
    def run_case(self, hk):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = bytes(range(256))*12
            fw = root/'blink.bin'
            fw.write_bytes(data)
            with contextlib.redirect_stdout(io.StringIO()):
                program(hk, fw, root/'evidence')
            self.assertEqual(hk.memory[:3072], data)
            self.assertEqual(hk.memory[3072:4096], b'\xff'*1024)
            self.assertEqual(hk.memory[4096:], bytes([0x5A])*4096)
            self.assertEqual(next((root/'evidence').glob('flash_before*')).read_bytes(), bytes([0x5A])*4096)
    def test_verified_program_preserves_next_sector(self):
        hk = FakeHK()
        self.run_case(hk)
        self.assertEqual(hk.regs, {11: 0, 9: 1, 8: 0})
    def test_bad_jedec_does_not_erase(self):
        hk = FakeHK(jedec=b'\xff\xff\xff')
        with self.assertRaisesRegex(RuntimeError, 'erase refused'): self.run_case(hk)
        self.assertFalse(hk.erased)
        self.assertEqual(hk.regs[11], 0)
    def test_readback_error_keeps_cpu_reset(self):
        hk = FakeHK(corrupt=True)
        with self.assertRaisesRegex(RuntimeError, 'readback differs'): self.run_case(hk)
        self.assertEqual(hk.regs[11], 1)

if __name__ == '__main__': unittest.main()
