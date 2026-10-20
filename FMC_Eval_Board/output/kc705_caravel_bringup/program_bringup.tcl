set here [file dirname [file normalize [info script]]]
set bit [file join $here build kc705_caravel_bringup.bit]
set ltx [file join $here build kc705_caravel_bringup.ltx]
if {![file exists $bit] || ![file exists $ltx]} {
    error "Missing build/kc705_caravel_bringup.bit or .ltx; run build_adc_test.tcl first"
}

open_hw_manager
connect_hw_server -allow_non_jtag
set target [get_hw_targets -quiet localhost:3121/xilinx_tcf/Xilinx/00001f14c98801]
if {[llength $target] != 1} { error "Known KC705 JTAG cable 00001f14c98801 not found" }
current_hw_target $target
open_hw_target
set dev [get_hw_devices -quiet -filter {PART == "xc7k325t"}]
if {[llength $dev] != 1} { error "Expected exactly one Kintex-7 xc7k325t" }
current_hw_device $dev
set_property PROGRAM.FILE $bit $dev
set_property PROBES.FILE $ltx $dev
set_property FULL_PROBES.FILE $ltx $dev
program_hw_devices $dev
refresh_hw_device $dev

if {[get_property REGISTER.CONFIG_STATUS.BIT13_DONE_INTERNAL_SIGNAL_STATUS $dev] != 1} { error "Internal DONE is low" }
if {[get_property REGISTER.CONFIG_STATUS.BIT14_DONE_PIN $dev] != 1} { error "DONE pin is low" }
if {[get_property REGISTER.CONFIG_STATUS.BIT04_END_OF_STARTUP_(EOS)_STATUS $dev] != 1} { error "EOS is low" }

# Reassert the fixed safe value explicitly as well as relying on VIO INIT=0.
set vios [get_hw_vios -quiet -of_objects $dev -filter {CELL_NAME == "u_run_vio"}]
if {[llength $vios] != 1} { error "Expected exactly one run-control VIO" }
set vio [lindex $vios 0]
set vio_probes [get_hw_probes -quiet -of_objects $vio]
proc require_named_probe {probes name type} {
    set matches {}
    foreach probe $probes {
        if {$probe eq $name && [get_property TYPE $probe] eq $type} {
            lappend matches $probe
        }
    }
    if {[llength $matches] != 1} { error "Expected one $type probe named $name" }
    return [lindex $matches 0]
}
proc vio_input_value {probes name} {
    set probe [require_named_probe $probes $name vio_input]
    return [expr 0x[get_property INPUT_VALUE $probe]]
}
set run_probe [require_named_probe $vio_probes run_enable vio_output]
set dac_probe [require_named_probe $vio_probes dac_enable vio_output]
set_property OUTPUT_VALUE 0 $run_probe
set_property OUTPUT_VALUE 0 $dac_probe
commit_hw_vio [list $run_probe $dac_probe]

# Confirm the live controller status after the safe command.  Vivado exposes
# the optimized status bus as named scalar/field probes rather than one vector.
after 10
refresh_hw_vio $vio
foreach {name expected} {
    run_enable_2 0 adc_clock_running 0 adc_reset_n 0 config_done 0
    sequence_index 0 control_state 0 spi_ncs 1 spi_sclk 0
    dac_enable_2 0 dac_reset_n 0 dac_ready 0 dac_frame_index 0
    dac_ncs 1 dac_sclk 0
} {
    set actual [vio_input_value $vio_probes $name]
    if {$actual != $expected} {
        error "ADC controller did not enter safe state: $name=$actual, expected $expected"
    }
}
puts "KC705_CARAVEL_BRINGUP_PROGRAMMED_ADC_DAC_SAFE"
puts "SAFE_STATUS: ADC and DAC enables=0; clocks low; resets low; chip selects high"
puts "ADC and DAC remain in reset. No daughtercard rail is commanded."
puts "Do not enable the DAC until the U1 REF/REFCMP network has been corrected and checked."
puts "Fit all seven 100-ohm LVDS terminations before powering the connected card; reset does not guarantee high-impedance outputs."
close_hw_target
disconnect_hw_server
close_hw_manager
exit

