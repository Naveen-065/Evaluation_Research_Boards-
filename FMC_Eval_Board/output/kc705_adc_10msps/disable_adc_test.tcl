set here [file dirname [file normalize [info script]]]
set ltx [file join $here build kc705_adc_10msps.ltx]
if {![file exists $ltx]} { error "Missing build/kc705_adc_10msps.ltx" }

open_hw_manager
connect_hw_server -allow_non_jtag
set target [get_hw_targets -quiet localhost:3121/xilinx_tcf/Xilinx/00001f14c98801]
if {[llength $target] != 1} { error "Known KC705 JTAG cable 00001f14c98801 not found" }
current_hw_target $target
open_hw_target
set dev [get_hw_devices -quiet -filter {PART == "xc7k325t"}]
if {[llength $dev] != 1} { error "Expected exactly one Kintex-7 xc7k325t" }
current_hw_device $dev
set_property PROBES.FILE $ltx $dev
set_property FULL_PROBES.FILE $ltx $dev
refresh_hw_device $dev
set vios [get_hw_vios -quiet -of_objects $dev -filter {CELL_NAME == "u_run_vio"}]
if {[llength $vios] != 1} { error "Expected exactly one run-control VIO" }
set run_probe [get_hw_probes -quiet -of_objects [lindex $vios 0] -filter {TYPE == vio_output && NAME == run_enable}]
if {[llength $run_probe] != 1} { error "Expected one VIO output named run_enable" }
set_property OUTPUT_VALUE 0 $run_probe
commit_hw_vio $run_probe
puts "ADS5282_TEST_DISABLED: sample clock low, nRESET low, SPI idle"
close_hw_target
disconnect_hw_server
close_hw_manager
exit

