# ZCU106 J5/HPC0 wrapper for the shared full bench initialization.
set zcu_here [file dirname [file normalize [info script]]]
set source_dir [file normalize [file join $zcu_here .. kc705_cell_control]]
set hw_target_pattern localhost:3121/xilinx_tcf/Xilinx/*
set hw_part xczu7
set probes_file [file join $zcu_here build zcu106_adc_capture.ltx]
set bitfile [file join $zcu_here build zcu106_adc_capture.bit]
set fmc_mux_address 0x75
set fmc_mux_value 0x01
source [file join $source_dir initialize.tcl]
