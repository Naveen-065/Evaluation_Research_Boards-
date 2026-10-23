# Caravel firmware snapshot

This directory is the firmware/tool snapshot used with the ReRAM scan
controller.  The distributable image is `gui_wb_mode.bin`; its verified
SHA-256 is:

```text
E7AD11E318B346EDAAE2FD0FF30736433FB27EF3BC5C39118AB4F1FC0A4107EF
```

`gui_wb_mode.c`, the SDK subset, Makefile, FTDI programming helpers, and the
matching ELF are retained so the image can be rebuilt and reflashed.  The FPGA
bitmap scheduler does not stream scan packets without a reset: each inner
Caravel transaction still follows the reset/READY discipline implemented in
the PL controller.

Do not flash by filename alone.  Verify the binary hash and FTDI target before
using `caravel_d2xx.py`; programming changes the attached Caravel flash.
