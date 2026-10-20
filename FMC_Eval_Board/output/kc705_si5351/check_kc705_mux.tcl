set here [file dirname [file normalize [info script]]]
source [file join $here i2c_host.tcl]
set s [read_status]
set scl [expr {($s >> 88) & 1}]
set sda [expr {($s >> 89) & 1}]
puts "I2C_IDLE_LEVELS SCL=$scl SDA=$sda"
if {!$scl || !$sda} { error "I2C bus is not idle high" }
mux_select_fmc
set control [mux_read]
puts [format "KC705_U49_OK address=0x74 control=0x%02X" $control]
if {$control != 0x04} { error "U49 channel readback mismatch" }
close_i2c_bridge
exit
