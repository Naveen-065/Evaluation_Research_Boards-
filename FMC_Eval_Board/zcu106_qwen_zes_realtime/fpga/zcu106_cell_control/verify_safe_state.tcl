set zcu_here [file dirname [file normalize [info script]]]
set hw_target_pattern localhost:3121/xilinx_tcf/Xilinx/*
set hw_part xczu7
set probes_file [file join $zcu_here build zcu106_adc_capture.ltx]
set source_dir [file normalize [file join $zcu_here .. kc705_cell_control]]
source [file join $source_dir i2c_host.tcl]
set control_vio [get_hw_vios -quiet -of_objects $dev -filter {CELL_NAME == "u_run_vio"}]
refresh_hw_vio $control_vio
foreach name {run_enable dac_enable} {
    set p [get_hw_probes -quiet $name -of_objects $control_vio -filter {TYPE == vio_output}]
    set value [get_property OUTPUT_VALUE $p]
    puts "SAFE_OUTPUT $name=$value"
    if {$value != 0} { error "$name is not safely disabled" }
}
foreach name {run_enable_2 dac_enable_2 adc_clock_running adc_reset_n dac_reset_n} {
    set p [get_hw_probes -quiet $name -of_objects $control_vio -filter {TYPE == vio_input}]
    set value [expr 0x[get_property INPUT_VALUE $p]]
    puts "SAFE_STATUS $name=$value"
}
close_i2c_bridge
exit

