set here [file dirname [file normalize [info script]]]
source [file join $here i2c_host.tcl]
set control_vio [get_hw_vios -quiet -of_objects $dev -filter {CELL_NAME == "u_run_vio"}]
if {[llength $control_vio] != 1} { error "ADC/DAC VIO missing" }
refresh_hw_vio $control_vio
foreach p [get_hw_probes -quiet -of_objects $control_vio] {
    if {[get_property TYPE $p] eq "vio_input"} {
        puts "LIVE_INPUT $p=[get_property INPUT_VALUE $p]"
    } else {
        puts "LIVE_OUTPUT $p=[get_property OUTPUT_VALUE $p]"
    }
}
source [file join $here assert_clock.tcl]
assert_caravel_clock
close_i2c_bridge
exit
