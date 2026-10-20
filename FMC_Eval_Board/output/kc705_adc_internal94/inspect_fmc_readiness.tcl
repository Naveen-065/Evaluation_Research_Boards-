# Read the current design and controller state without programming or changing
# VIO outputs. This cannot measure VADJ or certify external PCB wiring.
set here [file dirname [file normalize [info script]]]
set ltx [file join $here build kc705_adc_test.ltx]
if {![file exists $ltx]} { error "Missing matching debug probes" }
open_hw_manager
connect_hw_server -allow_non_jtag
set target [get_hw_targets -quiet localhost:3121/xilinx_tcf/Xilinx/00001f14c98801]
if {[llength $target] != 1} { error "Known KC705 JTAG cable not found" }
current_hw_target $target
open_hw_target
set dev [get_hw_devices -quiet -filter {PART == "xc7k325t"}]
if {[llength $dev] != 1} { error "Expected exactly one xc7k325t" }
current_hw_device $dev
set_property PROBES.FILE $ltx $dev
set_property FULL_PROBES.FILE $ltx $dev
refresh_hw_device $dev
foreach prop [list_property $dev] {
    if {[string match "REGISTER.CONFIG_STATUS.*" $prop] ||
        [string match "REGISTER.BOOT_STATUS.*" $prop]} {
        puts "DEVICE_STATUS $prop=[get_property $prop $dev]"
    }
}
foreach prop {
    REGISTER.CONFIG_STATUS.BIT13_DONE_INTERNAL_SIGNAL_STATUS
    REGISTER.CONFIG_STATUS.BIT14_DONE_PIN
    REGISTER.CONFIG_STATUS.BIT04_END_OF_STARTUP_(EOS)_STATUS
} {
    if {[get_property $prop $dev] != 1} { error "$prop is not asserted" }
}
set vios [get_hw_vios -quiet -of_objects $dev]
if {[llength $vios] != 1} { error "Expected exactly one control VIO" }
set vio [lindex $vios 0]
refresh_hw_vio $vio
set probes [get_hw_probes -quiet -of_objects $vio]
foreach {name expected} {
    run_enable_2 0 adc_clock_running 0 adc_reset_n 0 config_done 0
    sequence_index 0 control_state 0 spi_ncs 1 spi_sclk 0
    dac_enable_2 0 dac_reset_n 0 dac_ready 0 dac_frame_index 0
    dac_ncs 1 dac_sclk 0
} {
    set found {}
    foreach p $probes {
        if {$p eq $name && [get_property TYPE $p] eq "vio_input"} {
            lappend found $p
        }
    }
    if {[llength $found] != 1} { error "Missing unique status probe $name" }
    set actual [expr 0x[get_property INPUT_VALUE [lindex $found 0]]]
    puts "LIVE_STATUS $name=$actual (expected $expected)"
    if {$actual != $expected} { error "Not in safe disabled state: $name=$actual" }
}
puts "KC705_FMC_READINESS_LIVE_STATE_PASS_NO_OUTPUTS_CHANGED"
set mode_bits ""
foreach prop {
    REGISTER.CONFIG_STATUS.BIT10_MODE_PIN_M[2]
    REGISTER.CONFIG_STATUS.BIT09_MODE_PIN_M[1]
    REGISTER.CONFIG_STATUS.BIT08_MODE_PIN_M[0]
} {
    append mode_bits [get_property $prop $dev]
}
puts "SAMPLED_CONFIGURATION_MODE_M2_M1_M0=$mode_bits"
if {$mode_bits ne "101"} {
    puts "BOOT_MODE_CHECK_REQUIRED: with power off, set SW13 positions 3/4/5 to ON/OFF/ON for JTAG mode."
}
puts "PHYSICAL_CHECKS_REQUIRED: rails, rework, and seven receiver terminations are not verified by JTAG."
close_hw_target
disconnect_hw_server
close_hw_manager
exit
