from caravel_vm import VmSpi
from caravel_d2xx import Caravel
spi=VmSpi(100000)
try:
    hk=Caravel(spi)
    hk.identify()
    if hk.read_reg(11)!=1:
        raise RuntimeError('CPU is not held in reset; passive flash check skipped')
    print('FLASH_JEDEC_READ_ONLY',hk.flash([0x9f],3).hex())
finally:
    spi.close()
