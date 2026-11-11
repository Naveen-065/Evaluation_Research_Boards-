set here [file dirname [file normalize [info script]]]
source [file join $here i2c_host.tcl]
mux_select_fmc
if {[mux_read] != 0x04} { error "U49 did not retain FMC channel 2" }
after 20
set status0 [si5351_read 0]
puts [format "SI5351_ACK address=0x60 status_reg0=0x%02X" $status0]
set deadline [expr {[clock milliseconds] + 1000}]
while {$status0 & 0x80} {
    if {[clock milliseconds] > $deadline} { error "Si5351 SYS_INIT stayed high" }
    after 10
    set status0 [si5351_read 0]
}
# Register 2 is only an interrupt-status mask. Rewriting the same byte provides
# a safe write/readback check without changing any clock setting or output.
set original_mask [si5351_read 2]
si5351_write 2 $original_mask
set mask_readback [si5351_read 2]
if {$mask_readback != $original_mask} { error "Si5351 register-2 readback mismatch" }
puts [format "SI5351_SAFE_RW_OK status=0x%02X reg2=0x%02X" $status0 $mask_readback]
close_i2c_bridge
exit
