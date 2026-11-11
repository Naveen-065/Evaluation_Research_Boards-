# Deliberate interlock: only use this after the unpowered card is seated, the
# board is powered, VADJ is re-measured at 1.8 V, and the three target rails
# have been checked for shorts to ground.  The second acknowledgement exists
# because the released schematic leaves REF open and fits 100 nF at REFCMP;
# these must be corrected/verified before relying on the internal reference.
if {[llength $argv] != 2 ||
    [lindex $argv 0] ne "PCB_CONNECTED_RAILS_CHECKED" ||
    [lindex $argv 1] ne "DAC_REFERENCE_NETWORK_CHECKED"} {
    error "Usage: vivado -mode batch -source enable_dac_shunts.tcl -tclargs PCB_CONNECTED_RAILS_CHECKED DAC_REFERENCE_NETWORK_CHECKED"
}

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
set vio [lindex $vios 0]
set probes [get_hw_probes -quiet -of_objects $vio]
proc require_named_probe {probes name type} {
    set matches {}
    foreach probe $probes {
        if {$probe eq $name && [get_property TYPE $probe] eq $type} { lappend matches $probe }
    }
    if {[llength $matches] != 1} { error "Expected one $type probe named $name" }
    return [lindex $matches 0]
}
proc vio_input_value {probes name} {
    set probe [require_named_probe $probes $name vio_input]
    return [expr 0x[get_property INPUT_VALUE $probe]]
}

set run_probe [require_named_probe $probes run_enable vio_output]
set dac_probe [require_named_probe $probes dac_enable vio_output]

# DAC rails are established before starting the ADC.  Refuse to alter DAC
# state if the ADC is already running, so measurement startup is ordered.
refresh_hw_vio $vio
if {[get_property OUTPUT_VALUE $run_probe] != 0} {
    error "ADC is already enabled; disable it before changing the DAC startup state"
}
set_property OUTPUT_VALUE 1 $dac_probe
commit_hw_vio $dac_probe

set deadline [expr {[clock milliseconds] + 1000}]
while {1} {
    refresh_hw_vio $vio
    if {
        [vio_input_value $probes dac_enable_2] == 1 &&
        [vio_input_value $probes dac_ready] == 1 &&
        [vio_input_value $probes dac_reset_n] == 1 &&
        [vio_input_value $probes dac_frame_index] == 10 &&
        [vio_input_value $probes dac_ncs] == 1 &&
        [vio_input_value $probes dac_sclk] == 0
    } { break }
    if {[clock milliseconds] > $deadline} {
        set_property OUTPUT_VALUE 0 $dac_probe
        commit_hw_vio $dac_probe
        error "DAC81416 startup timeout; DAC returned to reset-low safe state"
    }
    after 10
}

puts "DAC81416_SHUNT_RAILS_ENABLED"
puts "DAC0/R9 VCC_READ=0.5V; DAC2/R10 VCC_SET=0.5V; DAC5/R11 VCC_RESET=2.5V"
puts "Measure all three rails before enabling the ADC."
close_hw_target
disconnect_hw_server
close_hw_manager
exit
