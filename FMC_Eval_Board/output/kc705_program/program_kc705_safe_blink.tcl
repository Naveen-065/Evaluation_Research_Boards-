set here [file dirname [file normalize [info script]]]
set bit_file [file join $here build kc705_safe_blink.bit]
set expected_target "localhost:3121/xilinx_tcf/Xilinx/00001f14c98801"

if {![file exists $bit_file]} {
    error "Bitstream not found: $bit_file"
}

open_hw_manager
connect_hw_server -allow_non_jtag
set target [get_hw_targets -quiet $expected_target]
if {[llength $target] != 1} {
    error "Expected KC705 JTAG target not found: $expected_target"
}
current_hw_target [lindex $target 0]
open_hw_target

set candidates [get_hw_devices -quiet -filter {PART == "xc7k325t"}]
if {[llength $candidates] != 1} {
    error "Expected exactly one xc7k325t on KC705 target; found [llength $candidates]"
}
set dev [lindex $candidates 0]
current_hw_device $dev
refresh_hw_device -update_hw_probes false $dev

puts "CODEX_PROGRAM_TARGET=$expected_target"
puts "CODEX_PROGRAM_DEVICE=$dev PART=[get_property PART $dev]"
puts "CODEX_PROGRAM_FILE=$bit_file"
set_property PROGRAM.FILE $bit_file $dev
set_property PROBES.FILE {} $dev
program_hw_devices $dev
refresh_hw_device -update_hw_probes false $dev

set done_internal [get_property REGISTER.CONFIG_STATUS.BIT13_DONE_INTERNAL_SIGNAL_STATUS $dev]
set done_pin [get_property REGISTER.CONFIG_STATUS.BIT14_DONE_PIN $dev]
set eos [get_property REGISTER.CONFIG_STATUS.BIT04_END_OF_STARTUP_\(EOS\)_STATUS $dev]
puts "CODEX_CONFIG_DONE_INTERNAL=$done_internal"
puts "CODEX_CONFIG_DONE_PIN=$done_pin"
puts "CODEX_CONFIG_EOS=$eos"
if {$done_internal ne "1" || $done_pin ne "1" || $eos ne "1"} {
    error "KC705 did not report DONE and end-of-startup after programming"
}
puts "CODEX_PROGRAM_OK"

close_hw_target
disconnect_hw_server
close_hw_manager
