set here [file dirname [file normalize [info script]]]
set source_dir [file normalize [file join $here .. kc705_cell_control]]
set out [file join $here build]
set project_dir [file join $here vivado_project]
file mkdir $out
create_project -force zcu106_cell_control $project_dir -part xczu7ev-ffvc1156-2-e
set_property target_language Verilog [current_project]
set_property verilog_define {ZCU106} [current_fileset]

# Recreate debug IP for the target family instead of reusing the Kintex-7 XCI.
create_ip -name vio -vendor xilinx.com -library ip -version 3.0 -module_name adc_run_vio
set_property -dict [list \
    CONFIG.C_NUM_PROBE_IN {1} CONFIG.C_NUM_PROBE_OUT {2} \
    CONFIG.C_PROBE_IN0_WIDTH {32} \
    CONFIG.C_PROBE_OUT0_WIDTH {1} CONFIG.C_PROBE_OUT1_WIDTH {1} \
    CONFIG.C_PROBE_OUT0_INIT_VAL {0x0} CONFIG.C_PROBE_OUT1_INIT_VAL {0x0}] [get_ips adc_run_vio]

create_ip -name ila -vendor xilinx.com -library ip -version 6.2 -module_name adc_capture_ila
set_property -dict [list \
    CONFIG.C_NUM_OF_PROBES {5} CONFIG.C_DATA_DEPTH {4096} \
    CONFIG.C_ADV_TRIGGER {false} CONFIG.C_EN_STRG_QUAL {0} \
    CONFIG.C_PROBE0_WIDTH {60} CONFIG.C_PROBE1_WIDTH {60} \
    CONFIG.C_PROBE2_WIDTH {12} CONFIG.C_PROBE3_WIDTH {32} \
    CONFIG.C_PROBE4_WIDTH {4}] [get_ips adc_capture_ila]

create_ip -name vio -vendor xilinx.com -library ip -version 3.0 -module_name vadj_vio
set_property -dict [list \
    CONFIG.C_NUM_PROBE_IN {1} CONFIG.C_NUM_PROBE_OUT {1} \
    CONFIG.C_PROBE_IN0_WIDTH {128} CONFIG.C_PROBE_OUT0_WIDTH {128} \
    CONFIG.C_PROBE_OUT0_INIT_VAL {0x00000000000000000000000000000000}] [get_ips vadj_vio]

create_ip -name vio -vendor xilinx.com -library ip -version 3.0 -module_name scan_read_vio
set_property -dict [list \
    CONFIG.C_NUM_PROBE_IN {2} CONFIG.C_NUM_PROBE_OUT {1} \
    CONFIG.C_PROBE_IN0_WIDTH {256} CONFIG.C_PROBE_IN1_WIDTH {256} \
    CONFIG.C_PROBE_OUT0_WIDTH {64} CONFIG.C_PROBE_OUT0_INIT_VAL {0x0000000000000000}] [get_ips scan_read_vio]

generate_target all [get_ips]
foreach ip [get_ips] { create_ip_run $ip }
set ip_runs [get_runs -filter {IS_SYNTHESIS && NAME != synth_1}]
launch_runs $ip_runs -jobs 4
foreach run $ip_runs { wait_on_run $run }

add_files [list \
    [file join $source_dir cell_control_engine.v] \
    [file join $source_dir cell_control_ramp_wrapper.v] \
    [file join $source_dir runtime_dac_spi.v] \
    [file join $source_dir uart_rx_8n1.v] \
    [file join $source_dir kc705_adc_test.v] \
    [file join $source_dir i2c_transaction_bridge.v] \
    [file join $source_dir adc_return_clock_monitor.v] \
    [file join $source_dir adc_word_snapshot.v]]
read_xdc [file join $here zcu106_adc_test.xdc]
read_xdc [file join $here zcu106_management_i2c.xdc]
read_xdc [file join $source_dir snapshot_timing.xdc]

synth_design -top kc705_adc_test -part xczu7ev-ffvc1156-2-e -verilog_define ZCU106
if {[llength [get_debug_cores -quiet dbg_hub]] == 0} { create_debug_core dbg_hub dbg_hub }
set_property C_CLK_INPUT_FREQ_HZ 200000000 [get_debug_cores dbg_hub]
set_property C_ENABLE_CLK_DIVIDER false [get_debug_cores dbg_hub]
set_property C_USER_SCAN_CHAIN 1 [get_debug_cores dbg_hub]
connect_debug_port dbg_hub/clk [get_nets sysclk]

opt_design
place_design
phys_opt_design
route_design
report_timing_summary -file [file join $out timing_summary.rpt]
report_drc -file [file join $out drc.rpt]
report_route_status -file [file join $out route_status.rpt]
report_io -file [file join $out io.rpt]

set bad [get_drc_violations -quiet -filter {SEVERITY == "Error" || SEVERITY == "Critical Warning"}]
if {[llength $bad]} { error "Critical DRC: $bad" }
foreach type {setup hold} {
    set paths [get_timing_paths -max_paths 1 -nworst 1 -$type]
    if {[llength $paths] == 0 || [get_property SLACK [lindex $paths 0]] < 0} {
        error "$type timing failed"
    }
}

set f [open [file join $out port_properties.tsv] w]
puts $f "PORT\tPACKAGE_PIN\tIOSTANDARD\tDIRECTION\tDRIVE\tSLEW\tDIFF_TERM\tPULLTYPE"
foreach p [lsort [get_ports]] {
    set row [list $p]
    foreach property {PACKAGE_PIN IOSTANDARD DIRECTION DRIVE SLEW DIFF_TERM PULLTYPE} {
        lappend row [get_property $property $p]
    }
    puts $f [join $row "\t"]
}
close $f
write_debug_probes -force [file join $out zcu106_adc_capture.ltx]
write_checkpoint -force [file join $out zcu106_adc_capture.dcp]
write_bitstream -force [file join $out zcu106_adc_capture.bit]
puts "ZCU106_HPC0_BUILD_PASS_ADC_DAC_INIT_ZERO"
exit

