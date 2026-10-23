"""Caravel blink programming through the existing Ubuntu VM's PyFTDI stack."""
import argparse
from pathlib import Path
import usb.core
import usb.util
from pyftdi.spi import SpiController
from caravel_d2xx import Caravel, program

class VmSpi:
    def __init__(self, hz):
        found = list(usb.core.find(find_all=True, idVendor=0x0403, idProduct=0x6014))
        if len(found) != 1:
            raise RuntimeError(f'Expected exactly one FT232H in this VM, found {len(found)}')
        dev = found[0]
        product = usb.util.get_string(dev, dev.iProduct)
        if product != 'Single RS232-HS' or dev.iSerialNumber != 0:
            raise RuntimeError('USB identity is not the un-serialized daughtercard FT232H')
        print(f'SELECTED_VM_FT232H bus={dev.bus} address={dev.address} product={product}', flush=True)
        self.controller = SpiController(cs_count=1)
        self.controller.configure('ftdi://ftdi:232h/1')
        self.gpio = self.controller.get_gpio()
        # ACBUS0 disables the PCB U3/U4 UART buffers during housekeeping SPI.
        # ACBUS1 (external reset) and all other GPIO remain inputs.
        self.gpio.set_direction(0xFF00, 0x0100)
        self.gpio.write(0x0100)
        self.port = self.controller.get_port(cs=0, freq=hz, mode=0)
    def exchange(self, output, nr=0):
        return bytes(self.port.exchange(bytes(output), nr))
    def pins(self):
        return int(self.gpio.read()).to_bytes(2, 'little')
    def close(self):
        self.controller.terminate()

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--hz', type=int, default=100000)
    ap.add_argument('--flash', type=Path)
    ap.add_argument('--hold-after', action='store_true')
    ap.add_argument('--release', action='store_true')
    args = ap.parse_args()
    spi = VmSpi(args.hz)
    try:
        hk = Caravel(spi)
        if args.flash:
            program(hk, args.flash, Path(__file__).parent/'evidence', hold_after=args.hold_after)
        else:
            hk.identify()
            if args.release:
                hk.write_reg(9, 1)
                hk.write_reg(8, 0)
                hk.write_reg(11, 0)
                assert hk.read_reg(11) == 0
                print('SCAN_FIRMWARE_CPU_RELEASED')
    finally:
        spi.close()

