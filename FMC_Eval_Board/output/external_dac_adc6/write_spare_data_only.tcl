# User declined SDO and requires all other DAC settings preserved.
# Therefore send ONLY the two channel-data writes, no shared-register writes.
# Codes assume the evaluation project's range map: DAC8 0..10 V, DAC14 0..5 V.
set here [file dirname [file normalize [info script]]]
source [file join $here spi_host.tcl]
spi 0x182CCD
spi 0x1E4000
puts "EXTERNAL_DAC8_DAC14_DATA_ONLY_TRANSMITTED"
puts "DAC8 code=0x2CCD, nominal 1.75 V on existing evaluation 0..10 V span."
puts "DAC14 code=0x4000, nominal 1.25 V on existing evaluation 0..5 V span."
puts "No power, range, reference, sync, toggle, or other channel registers written."
puts "Power state and ranges are not readable without SDO. Outputs may remain off. Measure before connecting."
close_spi
exit
