set here [file dirname [file normalize [info script]]]
source [file join $here i2c_host.tcl]
set control_vio [get_hw_vios -quiet -of_objects $dev -filter {CELL_NAME == "u_run_vio"}]
if {[llength $control_vio] != 1} { error "ADC/DAC VIO missing" }
refresh_hw_vio $control_vio
foreach p [get_hw_probes -quiet -of_objects $control_vio -filter {TYPE == vio_input}] {
    puts "BEFORE_STOP $p=[get_property INPUT_VALUE $p]"
}
set run_probe [get_hw_probes -quiet run_enable -of_objects $control_vio -filter {TYPE == vio_output}]
if {[llength $run_probe] != 1} { error "ADC enable probe missing" }
set_property OUTPUT_VALUE 0 $run_probe
commit_hw_vio $run_probe
after 10
refresh_hw_vio $control_vio
foreach {name expected} {run_enable_2 0 adc_clock_running 0 adc_reset_n 0 config_done 0 spi_sclk 0 spi_ncs 1} {
    set p [get_hw_probes -quiet $name -of_objects $control_vio]
    set actual [expr 0x[get_property INPUT_VALUE $p]]
    puts "AFTER_STOP $name=$actual"
    if {$actual != $expected} { error "ADC stop failed: $name" }
}
puts "ADC_STOPPED_DAC_ENABLE_NOT_CHANGED"
close_i2c_bridge
exit
