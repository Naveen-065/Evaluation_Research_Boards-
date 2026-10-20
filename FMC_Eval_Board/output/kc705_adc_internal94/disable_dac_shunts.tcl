set here [file dirname [file normalize [info script]]]
set ltx [file join $here build kc705_adc_test.ltx]
if {![file exists $ltx]} { error "Missing build/kc705_adc_test.ltx" }

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

set vios [get_hw_vios -quiet -of_objects $dev]
if {[llength $vios] != 1} { error "Expected exactly one control VIO" }
set probes [get_hw_probes -quiet -of_objects [lindex $vios 0]]
set dac_probe {}
set run_probe {}
foreach probe $probes {
    if {$probe eq "dac_enable" && [get_property TYPE $probe] eq "vio_output"} {
        lappend dac_probe $probe
    }
    if {$probe eq "run_enable" && [get_property TYPE $probe] eq "vio_output"} {
        lappend run_probe $probe
    }
}
if {[llength $dac_probe] != 1} { error "Expected one VIO output named dac_enable" }
if {[llength $run_probe] != 1} { error "Expected one VIO output named run_enable" }
if {[get_property OUTPUT_VALUE $run_probe] != 0} {
    error "ADC is running; run disable_adc_test.tcl before disabling the DAC rails"
}
set_property OUTPUT_VALUE 0 $dac_probe
commit_hw_vio $dac_probe
puts "DAC81416_SHUNT_RAILS_DISABLED: reset low, SPI idle; outputs return to reset power-down state"
close_hw_target
disconnect_hw_server
close_hw_manager
exit
