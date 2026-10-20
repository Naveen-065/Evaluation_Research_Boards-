# Deliberate interlock: this exact acknowledgement is required on the command
# line after receiver-end termination has been physically fitted to OUT1-5,
# LCLK and ADCLK.
if {[llength $argv] != 1 || [lindex $argv 0] ne "TERMINATIONS_INSTALLED"} {
    error "Usage: vivado -mode batch -source enable_adc_10msps.tcl -tclargs TERMINATIONS_INSTALLED"
}

set here [file dirname [file normalize [info script]]]
set ltx [file join $here build kc705_dac_pcb.ltx]
if {![file exists $ltx]} { error "Missing build/kc705_dac_pcb.ltx" }

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
refresh_hw_vio $vio
if {[get_property OUTPUT_VALUE $dac_probe] != 1 ||
    [vio_input_value $vio_probes dac_ready] != 1} {
    error "DAC shunt rails are not ready; run enable_dac_scan.tcl and measure the three rails first"
}
set_property OUTPUT_VALUE 1 $run_probe
commit_hw_vio $run_probe

# The hardware sequence takes about 11.2 ms.  Verify its exact final status;
# on any timeout, return immediately to the clock-off/reset-low safe state.
set deadline [expr {[clock milliseconds] + 1000}]
while {1} {
    refresh_hw_vio $vio
    if {
        [vio_input_value $vio_probes run_enable_2] == 1 &&
        [vio_input_value $vio_probes adc_clock_running] == 1 &&
        [vio_input_value $vio_probes adc_reset_n] == 1 &&
        [vio_input_value $vio_probes config_done] == 1 &&
        [vio_input_value $vio_probes sequence_index] == 6 &&
        [vio_input_value $vio_probes control_state] == 11 &&
        [vio_input_value $vio_probes spi_ncs] == 1 &&
        [vio_input_value $vio_probes spi_sclk] == 0 &&
        [vio_input_value $vio_probes pll_locked] == 1
    } { break }
    if {[clock milliseconds] > $deadline} {
        set_property OUTPUT_VALUE 0 $run_probe
        commit_hw_vio $run_probe
        error "ADS5282 startup status timeout; returned to safe state"
    }
    after 10
}
puts "ADS5282_TEST_ENABLED"
puts "STATUS: 10 MHz clock running, reset released, normal analog-data mode active."
close_hw_target
disconnect_hw_server
close_hw_manager
exit
