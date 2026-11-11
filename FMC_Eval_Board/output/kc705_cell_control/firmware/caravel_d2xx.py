"""Bounded Caravel housekeeping access using installed Windows D2XX driver.

Only the explicitly selected un-serialized daughtercard FT232H is opened.
Protocol matches efabless/caravel_board firmware/chipignite/util/caravel/hk.py.
FTDI commands follow AN_108. No EEPROM or driver changes are performed.
"""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import time
from ftdi_inventory import devices

class Mpsse:
    def __init__(self, location, hz=100000):
        matches = [d for d in devices() if d['location'] == location
                   and d['usb_id'] == '04036014' and d['kind'] == 8
                   and d['description'] == 'Single RS232-HS' and not d['serial']]
        if len(matches) != 1:
            raise RuntimeError('Daughtercard identity/location does not match; no device opened')
        print('SELECTED_FT232H', json.dumps(matches[0]), flush=True)
        self.dll = C.WinDLL('ftd2xx.dll')
        self.h = C.c_void_p()
        self.dll.FT_Open.argtypes = [C.c_int, C.POINTER(C.c_void_p)]
        self.dll.FT_Close.argtypes = [C.c_void_p]
        self.dll.FT_Write.argtypes = [C.c_void_p, C.c_void_p, C.c_ulong, C.POINTER(C.c_ulong)]
        self.dll.FT_Read.argtypes = [C.c_void_p, C.c_void_p, C.c_ulong, C.POINTER(C.c_ulong)]
        self.dll.FT_GetQueueStatus.argtypes = [C.c_void_p, C.POINTER(C.c_ulong)]
        self.dll.FT_SetBitMode.argtypes = [C.c_void_p, C.c_ubyte, C.c_ubyte]
        self.dll.FT_SetLatencyTimer.argtypes = [C.c_void_p, C.c_ubyte]
        self.dll.FT_SetTimeouts.argtypes = [C.c_void_p, C.c_ulong, C.c_ulong]
        self.dll.FT_SetUSBParameters.argtypes = [C.c_void_p, C.c_ulong, C.c_ulong]
        self.dll.FT_Purge.argtypes = [C.c_void_p, C.c_ulong]
        self.ok(self.dll.FT_Open(matches[0]['index'], C.byref(self.h)), 'open')
        self.ok(self.dll.FT_SetTimeouts(self.h, 2000, 2000), 'timeouts')
        self.ok(self.dll.FT_SetUSBParameters(self.h, 65536, 65536), 'USB buffers')
        self.ok(self.dll.FT_SetLatencyTimer(self.h, 2), 'latency')
        self.ok(self.dll.FT_SetBitMode(self.h, 0, 0), 'reset MPSSE')
        self.ok(self.dll.FT_SetBitMode(self.h, 0, 2), 'enable MPSSE')
        time.sleep(0.05)
        self.ok(self.dll.FT_Purge(self.h, 3), 'purge')
        self.write(bytes([0xAA, 0x87]))
        if self.read(2) != b'\xfa\xaa':
            raise RuntimeError('MPSSE synchronization failed')
        divisor = round(30000000 / hz) - 1
        # UART buffers U3/U4 disabled by ACBUS0=1; all other ACBUS pins inputs.
        # ADBUS0=SCK out low, 1=MOSI out low, 2=MISO input, 3=nCS out high.
        self.write(bytes([0x8A, 0x97, 0x8D, 0x85,
                          0x82, 0x01, 0x01, 0x80, 0x08, 0x0B,
                          0x86, divisor & 255, divisor >> 8, 0x87]))
        time.sleep(0.02)

    @staticmethod
    def ok(status, action):
        if status:
            raise RuntimeError(f'D2XX {action}: status {status}')

    def write(self, data):
        buf = C.create_string_buffer(data)
        count = C.c_ulong()
        self.ok(self.dll.FT_Write(self.h, buf, len(data), C.byref(count)), 'write')
        if count.value != len(data):
            raise RuntimeError(f'Short USB write {count.value}/{len(data)}')

    def read(self, length):
        result = bytearray()
        deadline = time.monotonic() + 3
        while len(result) < length:
            queued = C.c_ulong()
            self.ok(self.dll.FT_GetQueueStatus(self.h, C.byref(queued)), 'queue')
            if queued.value:
                size = min(length - len(result), queued.value)
                buf, count = C.create_string_buffer(size), C.c_ulong()
                self.ok(self.dll.FT_Read(self.h, buf, size, C.byref(count)), 'read')
                result.extend(buf.raw[:count.value])
            elif time.monotonic() > deadline:
                raise TimeoutError(f'USB read timed out {len(result)}/{length}')
            else:
                time.sleep(0.001)
        return bytes(result)

    def exchange(self, output, nr=0):
        output = bytes(output)
        if not output or len(output) > 65536 or nr > 65536:
            raise ValueError('SPI transfer length')
        packet = bytearray([0x80, 0x00, 0x0B])
        n = len(output)-1
        packet.extend([0x11, n & 255, n >> 8])  # output falling edge, MSB first
        packet.extend(output)
        if nr:
            n = nr-1
            packet.extend([0x20, n & 255, n >> 8])  # input rising edge, MSB first
        packet.extend([0x80, 0x08, 0x0B, 0x87])
        self.write(bytes(packet))
        return self.read(nr) if nr else b''

    def pins(self):
        self.write(bytes([0x81, 0x83, 0x87]))
        return self.read(2)

    def close(self):
        if self.h.value:
            # CS inactive; leave reset undriven and UART isolation asserted.
            self.write(bytes([0x80, 0x08, 0x0B, 0x82, 0x01, 0x01, 0x87]))
            self.ok(self.dll.FT_Close(self.h), 'close')
            self.h = C.c_void_p()

class Caravel:
    def __init__(self, spi): self.spi = spi
    def read_reg(self, reg): return self.spi.exchange([0x48, reg], 1)[0]
    def write_reg(self, reg, value): self.spi.exchange([0x88, reg, value])
    def identify(self):
        mfg = self.spi.exchange([0x40, 0x01], 2)
        product = self.read_reg(3)
        project = self.spi.exchange([0x40, 4], 4)
        result = dict(mfg=mfg.hex(), product=f'{product:02x}', project_raw=project.hex(),
                      pins=self.spi.pins().hex())
        print('CARAVEL_IDENTIFICATION', json.dumps(result), flush=True)
        if mfg != b'\x04\x56':
            raise RuntimeError('Caravel manufacturer != 0456; no flash/reset writes performed')
        print('HK_REGISTERS', json.dumps({f'{r:02x}': f'{self.read_reg(r):02x}'
            for r in [8, 9, 10, 11, 12, 13, 14, 15, 16]}), flush=True)
        return result
    def flash(self, cmd, nr=0): return self.spi.exchange([0xC4]+list(cmd), nr)
    def wait_ready(self, seconds=5):
        deadline = time.monotonic()+seconds
        while self.flash([5], 1)[0] & 1:
            if time.monotonic() > deadline: raise TimeoutError('Flash WIP remained set')
            time.sleep(0.01)
    def write_enable(self):
        self.flash([6])
        if not self.flash([5], 1)[0] & 2: raise RuntimeError('Flash WEL not set')
    def read_flash(self, addr, count):
        result = bytearray()
        while len(result) < count:
            a = addr + len(result)
            n = min(256, count-len(result))
            result.extend(self.flash([3, a>>16, (a>>8)&255, a&255], n))
        return bytes(result)

def program(hk, firmware, evidence, hold_after=False):
    data = firmware.read_bytes()
    if not 0 < len(data) <= 65536: raise ValueError('Unexpected blink image size')
    hk.identify()
    original_reset = hk.read_reg(11)
    hk.write_reg(11, 1)
    if hk.read_reg(11) != 1: raise RuntimeError('CPU reset hold did not read back')
    destructive = False
    try:
        jedec = hk.flash([0x9F], 3)
        print('FLASH_JEDEC', jedec.hex(), flush=True)
        if jedec != b'\xef\x40\x16':
            raise RuntimeError('Expected PCB U8 W25Q32 JEDEC ef4016; erase refused')
        hk.wait_ready()
        if hk.flash([5], 1)[0] & 0x7C: raise RuntimeError('Flash protection bits set')
        size = ((len(data)+4095)//4096)*4096
        before = hk.read_flash(0, size)
        stamp = time.strftime('%Y%m%d_%H%M%S')
        evidence.mkdir(exist_ok=True)
        backup = evidence/f'flash_before_blink_{stamp}.bin'
        backup.write_bytes(before)
        if backup.read_bytes() != before: raise RuntimeError('Backup file verification failed')
        expected = data + b'\xff'*(size-len(data))
        print('FLASH_BACKUP', str(backup), 'sha256='+hashlib.sha256(before).hexdigest(), flush=True)
        if before != expected:
            for addr in range(0, size, 4096):
                hk.write_enable()
                destructive = True
                hk.flash([0x20, addr>>16, (addr>>8)&255, addr&255])
                hk.wait_ready(5)
            for addr in range(0, len(data), 256):
                hk.write_enable()
                hk.flash([2, addr>>16, (addr>>8)&255, addr&255]+list(data[addr:addr+256]))
                hk.wait_ready(3)
        after = hk.read_flash(0, size)
        (evidence/f'flash_after_blink_{stamp}.bin').write_bytes(after)
        if after != expected: raise RuntimeError('Flash readback differs; CPU remains held in reset')
        # As in the reference disengage_dll(): use the supplied 10 MHz external clock.
        hk.write_reg(9, 1)
        hk.write_reg(8, 0)
        if hk.read_reg(9) != 1 or hk.read_reg(8) != 0:
            raise RuntimeError('External clock bypass readback failed')
        hk.write_reg(11, 1 if hold_after else 0)
        if hk.read_reg(11) != (1 if hold_after else 0): raise RuntimeError('CPU reset state readback failed')
        result = dict(firmware=str(firmware), bytes=len(data), erased_bytes=size,
            sha256=hashlib.sha256(data).hexdigest(), verified=True,
            external_clock_bypass=True, cpu_reset_released=not hold_after, backup=str(backup))
        (evidence/f'flash_result_{stamp}.json').write_text(json.dumps(result, indent=2))
        print('CARAVEL_SCAN_FLASH_VERIFIED', json.dumps(result), flush=True)
    except Exception:
        if not destructive: hk.write_reg(11, original_reset)
        raise

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--location', type=int, required=True)
    ap.add_argument('--hz', type=int, default=100000)
    ap.add_argument('--flash', type=Path)
    args = ap.parse_args()
    if args.hz not in [10000, 100000, 1000000]: raise ValueError('Unsupported SPI rate')
    spi = Mpsse(args.location, args.hz)
    try:
        hk = Caravel(spi)
        if args.flash:
            program(hk, args.flash, Path(__file__).parent/'evidence')
        else:
            hk.identify()
    finally:
        spi.close()

