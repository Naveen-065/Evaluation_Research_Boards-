set here [file dirname [file normalize [info script]]]
open_hw_manager
connect_hw_server -allow_non_jtag
set t [get_hw_targets -quiet localhost:3121/xilinx_tcf/Digilent/210512180081]
if {[llength $t] != 1} { error "Known external AX7020 cable not found" }
current_hw_target $t
open_hw_target
set d [get_hw_devices -quiet -filter {PART == "xc7z020"}]
if {[llength $d] != 1} { error "Expected external XC7Z020, never the KC705" }
current_hw_device $d
set_property PROGRAM.FILE [file join $here build external_dac_adc6.bit] $d
set_property PROBES.FILE [file join $here build external_dac_adc6.ltx] $d
set_property FULL_PROBES.FILE [file join $here build external_dac_adc6.ltx] $d
program_hw_devices $d
refresh_hw_device $d
if {[get_property REGISTER.CONFIG_STATUS.BIT13_DONE_INTERNAL_SIGNAL_STATUS $d] != 1} {error "Zynq DONE low"}
foreach v [get_hw_vios -quiet -of_objects $d] {
    refresh_hw_vio $v
    foreach p [get_hw_probes -of_objects $v] {
        puts "PROBE $p type=[get_property TYPE $p]"
    }
}
puts "EXTERNAL_ZYNQ_SERVICE_PROGRAMMED_NO_DAC_WRITES"
if {$argv eq {DATA_ONLY}} {
    set external_dac_device_open 1
    source [file join $here write_spare_data_only.tcl]
}
close_hw_target
disconnect_hw_server
close_hw_manager
exit
