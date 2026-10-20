# This drops the DAC-driven VCCD2 and VDDA2 supplies as well as all biases.
set here [file dirname [file normalize [info script]]]
source [file join $here i2c_host.tcl]
set control_vio [get_hw_vios -quiet -of_objects $dev -filter {CELL_NAME == "u_run_vio"}]
if {[llength $control_vio] != 1} { error "ADC/DAC VIO missing" }
set run_probe [get_hw_probes -quiet run_enable -of_objects $control_vio -filter {TYPE == vio_output}]
set dac_probe [get_hw_probes -quiet dac_enable -of_objects $control_vio -filter {TYPE == vio_output}]
if {[llength $run_probe] != 1 || [llength $dac_probe] != 1} { error "Control probes missing" }
refresh_hw_vio $control_vio
if {[get_property OUTPUT_VALUE $run_probe] != 0} { error "Disable ADC before DAC supply rails" }
set_property OUTPUT_VALUE 0 $dac_probe
commit_hw_vio $dac_probe
after 10
refresh_hw_vio $control_vio
foreach {name expected} {dac_enable_2 0 dac_reset_n 0 dac_ready 0 dac_ncs 1 dac_sclk 0} {
    set p [get_hw_probes -quiet $name -of_objects $control_vio]
    if {[llength $p] != 1 || [expr 0x[get_property INPUT_VALUE $p]] != $expected} { error "Disable verification failed: $name" }
}
puts "DAC_DISABLED_RESET_ASSERTED"
close_i2c_bridge
exit
