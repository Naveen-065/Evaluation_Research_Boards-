set here [file dirname [file normalize [info script]]]
set bit [file join $here build kc705_j2_safe_io.bit]
if {![file exists $bit]} { error "Bitstream missing; run build_safe_io.tcl first" }

open_hw_manager
connect_hw_server -allow_non_jtag
set target [get_hw_targets -quiet localhost:3121/xilinx_tcf/Xilinx/00001f14c98801]
if {[llength $target] != 1} { error "Known KC705 JTAG cable not found" }
current_hw_target $target
open_hw_target
set dev [get_hw_devices -quiet -filter {PART == "xc7k325t"}]
if {[llength $dev] != 1} { error "Expected exactly one Kintex-7 xc7k325t" }
current_hw_device $dev
set_property PROGRAM.FILE $bit $dev
set_property PROBES.FILE {} $dev
program_hw_devices $dev
refresh_hw_device -update_hw_probes false $dev
if {[get_property REGISTER.CONFIG_STATUS.BIT13_DONE_INTERNAL_SIGNAL_STATUS $dev] != 1} { error "Internal DONE is low" }
if {[get_property REGISTER.CONFIG_STATUS.BIT14_DONE_PIN $dev] != 1} { error "DONE pin is low" }
if {[get_property REGISTER.CONFIG_STATUS.BIT04_END_OF_STARTUP_(EOS)_STATUS $dev] != 1} { error "EOS is low" }
puts "KC705_J2_PCB_SAFE_STATIC_PROGRAMMED"
puts "HIGH: C15 H13 H14 H16"
puts "LOW: C19 D17 D18 G12 G13 G15 G16 G18 G19 H17 H20"
puts "INPUT_HIGH_Z: C10 C11 C14 C18 D8 D9 D11 D12 D14 D15 G6 G7 G9 G10 H4 H5 H7 H8 H10 H11 H19"
close_hw_target
disconnect_hw_server
close_hw_manager
