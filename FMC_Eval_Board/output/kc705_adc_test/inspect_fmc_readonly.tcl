# Read-only pre-connection inspection: never program or commit a VIO output.
set here [file dirname [file normalize [info script]]]
open_hw_manager
connect_hw_server -allow_non_jtag
set target [get_hw_targets -quiet localhost:3121/xilinx_tcf/Xilinx/00001f14c98801]
if {[llength $target] != 1} { error "Known KC705 JTAG cable not found" }
current_hw_target $target
open_hw_target
set dev [get_hw_devices -quiet -filter {PART == "xc7k325t"}]
if {[llength $dev] != 1} { error "Expected one xc7k325t" }
current_hw_device $dev
set ltx [file join $here build kc705_adc_test.ltx]
set_property PROBES.FILE $ltx $dev
set_property FULL_PROBES.FILE $ltx $dev
refresh_hw_device $dev
foreach property [lsort [list_property $dev]] {
    if {[string match "REGISTER.CONFIG_STATUS.*" $property] ||
        [string match "REGISTER.USR_ACCESS*" $property]} {
        puts "DEVICE_STATUS $property=[get_property $property $dev]"
    }
}
foreach property {
    REGISTER.CONFIG_STATUS.BIT13_DONE_INTERNAL_SIGNAL_STATUS
    REGISTER.CONFIG_STATUS.BIT14_DONE_PIN
    REGISTER.CONFIG_STATUS.BIT04_END_OF_STARTUP_(EOS)_STATUS
} {
    if {[get_property $property $dev] != 1} { error "$property is not asserted" }
}
set vios [get_hw_vios -quiet -of_objects $dev]
if {[llength $vios] != 1} { error "Expected one control VIO in ADC/DAC image" }
set vio [lindex $vios 0]
refresh_hw_vio $vio
set probes [get_hw_probes -quiet -of_objects $vio]
proc named_value {probes name type property} {
    set matches {}
    foreach probe $probes {
        if {$probe eq $name && [get_property TYPE $probe] eq $type} {
            lappend matches $probe
        }
    }
    if {[llength $matches] != 1} { error "Missing/ambiguous $type probe $name" }
    set raw [get_property $property [lindex $matches 0]]
    if {![regexp {^[0-9a-fA-F]+$} $raw]} { error "Invalid $name readback: $raw" }
    return [expr "0x$raw"]
}
foreach name {run_enable dac_enable} {
    set actual [named_value $probes $name vio_output OUTPUT_VALUE]
    puts "LIVE_OUTPUT $name=$actual"
    if {$actual != 0} { error "$name is enabled; no output was changed by this inspection" }
}
foreach {name expected} {
    run_enable_2 0 adc_clock_running 0 adc_reset_n 0 config_done 0
    sequence_index 0 control_state 0 spi_ncs 1 spi_sclk 0
    dac_enable_2 0 dac_reset_n 0 dac_ready 0 dac_frame_index 0
    dac_state 0 dac_ncs 1 dac_sclk 0 pll_locked 1
} {
    set actual [named_value $probes $name vio_input INPUT_VALUE]
    puts "LIVE_INPUT $name=$actual"
    if {$actual != $expected} { error "$name=$actual, expected $expected; no output was changed" }
}
puts "KC705_FMC_READONLY_SAFE_STATUS_OK"
puts "This verifies internal logic only; physical connector voltages require a meter."
close_hw_target
disconnect_hw_server
close_hw_manager
exit
