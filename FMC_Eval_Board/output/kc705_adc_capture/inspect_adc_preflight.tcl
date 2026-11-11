set here [file dirname [file normalize [info script]]]
source [file join $here i2c_host.tcl]
source [file join $here assert_clock.tcl]
assert_caravel_clock
set control_vio [get_hw_vios -quiet -of_objects $dev -filter {CELL_NAME == "u_run_vio"}]
if {[llength $control_vio] != 1} { error "ADC/DAC control VIO missing" }
refresh_hw_vio $control_vio
foreach {name expected} {
    run_enable_2 0 pll_locked 1 adc_clock_running 0 adc_reset_n 0 config_done 0
    sequence_index 0 control_state 0 spi_ncs 1 spi_sclk 0
    dac_enable_2 1 dac_ready 1 dac_frame_index 20 dac_reset_n 1 dac_ncs 1 dac_sclk 0
} {
    set p [get_hw_probes -quiet $name -of_objects $control_vio -filter {TYPE == vio_input}]
    if {[llength $p] != 1} { error "Missing status probe $name" }
    set actual [expr 0x[get_property INPUT_VALUE $p]]
    puts "PREFLIGHT $name=$actual"
    if {$actual != $expected} { error "Unexpected live state: $name=$actual (expected $expected)" }
}
puts "ADC_PREFLIGHT_PASS_DAC_RUNNING_ADC_DISABLED"
close_i2c_bridge
exit
