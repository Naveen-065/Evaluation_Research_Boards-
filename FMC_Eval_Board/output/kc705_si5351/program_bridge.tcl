set here [file dirname [file normalize [info script]]]
set bit [file join $here build kc705_si5351_bridge.bit]
set ltx [file join $here build kc705_si5351_bridge.ltx]
if {![file exists $bit] || ![file exists $ltx]} {error "Bridge build files missing"}
open_hw_manager
connect_hw_server -allow_non_jtag
set target [get_hw_targets -quiet localhost:3121/xilinx_tcf/Xilinx/00001f14c98801]
if {[llength $target] != 1} {error "Known KC705 JTAG cable not found"}
current_hw_target $target
open_hw_target
set dev [get_hw_devices -quiet -filter {PART == "xc7k325t"}]
if {[llength $dev] != 1} {error "Expected one xc7k325t"}
current_hw_device $dev
set_property PROGRAM.FILE $bit $dev
set_property PROBES.FILE $ltx $dev
program_hw_devices $dev
refresh_hw_device $dev
if {[get_property REGISTER.CONFIG_STATUS.BIT14_DONE_PIN $dev] != 1} {error "DONE low"}
if {[llength [get_hw_vios -quiet -of_objects $dev]] != 1} {error "VIO not found"}
puts "SI5351_I2C_BRIDGE_PROGRAMMED_NO_I2C_COMMANDS_SENT"
close_hw_target
disconnect_hw_server
close_hw_manager
