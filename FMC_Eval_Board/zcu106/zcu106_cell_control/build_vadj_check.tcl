set here [file dirname [file normalize [info script]]]
set source_dir [file normalize [file join $here .. kc705_cell_control]]
set out [file join $here build_vadj_check]
file mkdir $out
create_project -force zcu106_vadj_check [file join $here vivado_project_vadj_check] -part xczu7ev-ffvc1156-2-e
set_property target_language Verilog [current_project]
create_ip -name vio -vendor xilinx.com -library ip -version 3.0 -module_name vadj_check_vio
set_property -dict [list \
    CONFIG.C_NUM_PROBE_IN {1} CONFIG.C_NUM_PROBE_OUT {1} \
    CONFIG.C_PROBE_IN0_WIDTH {128} CONFIG.C_PROBE_OUT0_WIDTH {128} \
    CONFIG.C_PROBE_OUT0_INIT_VAL {0x00000000000000000000000000000000}] [get_ips vadj_check_vio]
generate_target all [get_ips]
create_ip_run [get_ips]
set ip_runs [get_runs -filter {IS_SYNTHESIS && NAME != synth_1}]
launch_runs $ip_runs -jobs 2
foreach run $ip_runs { wait_on_run $run }
add_files [list [file join $here zcu106_vadj_check.v] [file join $source_dir i2c_transaction_bridge.v]]
read_xdc [file join $here zcu106_vadj_check.xdc]
synth_design -top zcu106_vadj_check -part xczu7ev-ffvc1156-2-e
if {[llength [get_debug_cores -quiet dbg_hub]] == 0} { create_debug_core dbg_hub dbg_hub }
set_property C_CLK_INPUT_FREQ_HZ 200000000 [get_debug_cores dbg_hub]
set_property C_ENABLE_CLK_DIVIDER false [get_debug_cores dbg_hub]
set_property C_USER_SCAN_CHAIN 1 [get_debug_cores dbg_hub]
connect_debug_port dbg_hub/clk [get_nets clk200]
opt_design
place_design
route_design
set bad [get_drc_violations -quiet -filter {SEVERITY == "Error" || SEVERITY == "Critical Warning"}]
if {[llength $bad]} { error "Critical DRC: $bad" }
foreach type {setup hold} {
    set paths [get_timing_paths -max_paths 1 -nworst 1 -$type]
    if {[llength $paths] == 0 || [get_property SLACK [lindex $paths 0]] < 0} { error "$type timing failed" }
}
write_debug_probes -force [file join $out zcu106_vadj_check.ltx]
write_bitstream -force [file join $out zcu106_vadj_check.bit]
puts "ZCU106_CARRIER_ONLY_VADJ_CHECK_BUILD_PASS"
exit

