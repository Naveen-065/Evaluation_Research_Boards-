# Program only the interlocked ZCU106 image, keep ADC/DAC disabled, then prove
# that ZCU106 I2C1 reaches HPC0 C30/C31 through U135 channel 0.
set zcu_here [file dirname [file normalize [info script]]]
set source_dir [file normalize [file join $zcu_here .. kc705_cell_control]]
set hw_target_pattern localhost:3121/xilinx_tcf/Xilinx/*
set hw_part xczu7
set probes_file [file join $zcu_here build zcu106_adc_capture.ltx]
set fmc_mux_address 0x75
set fmc_mux_value 0x01
source [file join $source_dir i2c_host.tcl]

set bitfile [file join $zcu_here build zcu106_adc_capture.bit]
if {![file exists $bitfile] || ![file exists $probes_file]} {
    error "Build output is missing; run build_zcu106.tcl first"
}
set_property PROGRAM.FILE $bitfile $dev
set_property PROBES.FILE $probes_file $dev
set_property FULL_PROBES.FILE $probes_file $dev
program_hw_devices $dev
refresh_hw_device $dev
if {[get_property REGISTER.CONFIG_STATUS.BIT13_DONE_INTERNAL_SIGNAL_STATUS $dev] != 1} {
    error "FPGA DONE failed"
}

# Explicitly restore both power/control interlocks to zero after programming.
set control_vio [get_hw_vios -quiet -of_objects $dev -filter {CELL_NAME == "u_run_vio"}]
if {[llength $control_vio] != 1} { error "Expected ADC/DAC control VIO" }
set safe_probes {}
foreach name {run_enable dac_enable} {
    set p [get_hw_probes -quiet $name -of_objects $control_vio -filter {TYPE == vio_output}]
    if {[llength $p] != 1} { error "Missing startup interlock $name" }
    set_property OUTPUT_VALUE 0 $p
    lappend safe_probes $p
}
commit_hw_vio $safe_probes

# Reacquire the I2C VIO after device refresh, select HPC0, and perform a
# read-only Si5351 status read. No mezzanine register is modified.
set vio [get_hw_vios -quiet -of_objects $dev -filter {CELL_NAME == "u_i2c_vio"}]
if {[llength $vio] != 1} { error "Expected management-I2C VIO" }
set cmdprobe [get_hw_probes -quiet -of_objects $vio -filter {TYPE == vio_output}]
set statprobe [get_hw_probes -quiet -of_objects $vio -filter {TYPE == vio_input}]
set token [expr {[read_status] & 255}]
mux_select_fmc
set selected [mux_read]
if {$selected != $fmc_mux_value} {
    error [format "ZCU106 U135 HPC0 selection failed: 0x%02X" $selected]
}
set status0 [si5351_read 0]
puts [format "ZCU106_HPC0_SAFE_DEPLOY_PASS mux=0x%02X si5351_status=0x%02X ADC=OFF DAC=OFF" $selected $status0]
close_i2c_bridge
exit

