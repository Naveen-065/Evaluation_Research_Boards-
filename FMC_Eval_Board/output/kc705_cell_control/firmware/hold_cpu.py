"""Hold the identified Caravel CPU while restoring bench power and clocks."""
from caravel_vm import VmSpi
from caravel_d2xx import Caravel

spi = VmSpi(100000)
try:
    hk = Caravel(spi)
    hk.identify()
    hk.write_reg(11, 1)
    assert hk.read_reg(11) == 1
    hk.write_reg(9, 1)
    hk.write_reg(8, 0)
    assert hk.read_reg(9) == 1 and hk.read_reg(8) == 0
    print("CARAVEL_CPU_HELD_EXTERNAL_CLOCK_SELECTED", flush=True)
finally:
    spi.close()
