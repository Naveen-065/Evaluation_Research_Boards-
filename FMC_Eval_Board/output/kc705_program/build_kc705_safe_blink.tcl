set here [file dirname [file normalize [info script]]]
set out_dir [file join $here build]
file mkdir $out_dir

read_verilog [file join $here kc705_safe_blink.v]
read_xdc [file join $here kc705_safe_blink.xdc]

synth_design -top kc705_safe_blink -part xc7k325tffg900-2
opt_design
place_design
phys_opt_design
route_design

set timing_paths [get_timing_paths -max_paths 1 -nworst 1 -setup]
if {[llength $timing_paths] == 0} {
    error "No setup timing path was available for verification"
}
set worst_slack [get_property SLACK [lindex $timing_paths 0]]
puts "CODEX_WORST_SETUP_SLACK_NS=$worst_slack"
if {$worst_slack < 0.0} {
    error "Timing failed with setup slack $worst_slack ns"
}

report_timing_summary -file [file join $out_dir timing_summary.rpt]
report_utilization -file [file join $out_dir utilization.rpt]
report_drc -file [file join $out_dir drc.rpt]

set critical_drc [get_drc_violations -quiet -filter {SEVERITY == "Error" || SEVERITY == "Critical Warning"}]
if {[llength $critical_drc] != 0} {
    puts "CODEX_CRITICAL_DRC_COUNT=[llength $critical_drc]"
    foreach violation $critical_drc { puts "CODEX_DRC=$violation" }
    error "Critical DRC violations prevent programming"
}

write_checkpoint -force [file join $out_dir kc705_safe_blink_routed.dcp]
write_bitstream -force [file join $out_dir kc705_safe_blink.bit]
puts "CODEX_BUILD_OK=[file join $out_dir kc705_safe_blink.bit]"
