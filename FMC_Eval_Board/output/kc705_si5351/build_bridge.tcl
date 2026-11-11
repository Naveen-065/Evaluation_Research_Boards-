set here [file dirname [file normalize [info script]]]
set out [file join $here build]
file mkdir $out
create_project -force si5351_bridge [file join $here vivado_project] -part xc7k325tffg900-2
set_property target_language Verilog [current_project]
create_ip -name vio -vendor xilinx.com -library ip -module_name si5351_vio
set_property -dict [list CONFIG.C_NUM_PROBE_IN {1} CONFIG.C_NUM_PROBE_OUT {1} CONFIG.C_PROBE_IN0_WIDTH {128} CONFIG.C_PROBE_OUT0_WIDTH {128} CONFIG.C_PROBE_OUT0_INIT_VAL {0x0}] [get_ips si5351_vio]
generate_target all [get_ips si5351_vio]
synth_ip [get_ips si5351_vio]
add_files [file join $here kc705_si5351_bridge.v]
read_xdc [file join $here kc705_si5351_bridge.xdc]
synth_design -top kc705_si5351_bridge -part xc7k325tffg900-2
opt_design
place_design
phys_opt_design
route_design
report_timing_summary -file [file join $out timing_summary.rpt]
report_drc -file [file join $out drc.rpt]
report_io -file [file join $out io.rpt]
set bad [get_drc_violations -quiet -filter {SEVERITY == "Error" || SEVERITY == "Critical Warning"}]
if {[llength $bad]} { error "Critical DRC: $bad" }
set paths [get_timing_paths -max_paths 1 -nworst 1 -setup]
if {[llength $paths] == 0 || [get_property SLACK [lindex $paths 0]] < 0} { error "Setup timing failed" }
set holds [get_timing_paths -max_paths 1 -nworst 1 -hold]
if {[llength $holds] == 0 || [get_property SLACK [lindex $holds 0]] < 0} { error "Hold timing failed" }
write_debug_probes -force [file join $out kc705_si5351_bridge.ltx]
write_checkpoint -force [file join $out kc705_si5351_bridge.dcp]
write_bitstream -force [file join $out kc705_si5351_bridge.bit]
puts "SI5351_BRIDGE_BUILD_OK"
exit
