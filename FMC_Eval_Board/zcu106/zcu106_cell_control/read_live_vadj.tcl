# Programs a carrier-only image and reads INA226 U65, which monitors VADJ_FMC.
set here [file dirname [file normalize [info script]]]
set source_dir [file normalize [file join $here .. kc705_cell_control]]
set hw_target_pattern localhost:3121/xilinx_tcf/Xilinx/*
set hw_part xczu7
set probes_file [file join $here build_vadj_check zcu106_vadj_check.ltx]
set program_before_vio [file join $here build_vadj_check zcu106_vadj_check.bit]
source [file join $source_dir i2c_host.tcl]

# U60 is a PCA9544A. Enable and select channel 1 (PL_PMBUS), then read the
# big-endian INA226 bus-voltage register from U65 at address 0x45.
i2c_transfer 0x75 [list 0x05] 0
set mux [lindex [i2c_transfer 0x75 [list] 1] 0]
if {$mux != 0x05} { error [format "U60 PL_PMBUS selection failed: 0x%02X" $mux] }
set bytes [i2c_transfer 0x45 [list 0x02] 2]
set raw [expr {([lindex $bytes 0] << 8) | [lindex $bytes 1]}]
set millivolts [expr {$raw * 1.25}]
puts [format "ZCU106_LIVE_VADJ_MV=%.2f raw=0x%04X" $millivolts $raw]
if {$millivolts < 1700.0 || $millivolts > 1900.0} {
    error [format "Unsafe VADJ for LVCMOS18/LVDS image: %.2f mV" $millivolts]
}
puts "ZCU106_LIVE_VADJ_1V8_PASS"
close_i2c_bridge
exit

