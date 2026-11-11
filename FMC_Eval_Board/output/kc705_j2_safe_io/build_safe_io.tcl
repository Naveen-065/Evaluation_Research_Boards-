set here [file dirname [file normalize [info script]]]
set out [file join $here build]
file mkdir $out

create_project -force kc705_j2_safe_io [file join $here vivado_project] -part xc7k325tffg900-2
set_property target_language Verilog [current_project]

add_files [file join $here kc705_j2_safe_io.v]
read_xdc [file join $here kc705_j2_safe_io.xdc]
synth_design -top kc705_j2_safe_io -part xc7k325tffg900-2
opt_design
place_design
phys_opt_design
route_design

report_timing_summary -file [file join $out timing_summary.rpt]
report_drc -file [file join $out drc.rpt]
report_methodology -file [file join $out methodology.rpt]
report_route_status -file [file join $out route_status.rpt]
report_io -file [file join $out io.rpt]

set bad [get_drc_violations -quiet -filter {SEVERITY == "Error" || SEVERITY == "Critical Warning"}]
if {[llength $bad]} { error "Critical DRC: $bad" }
set setup_paths [get_timing_paths -max_paths 1 -nworst 1 -setup]
if {[llength $setup_paths] == 0 || [get_property SLACK [lindex $setup_paths 0]] < 0} {
    error "Setup timing failed"
}
set hold_paths [get_timing_paths -max_paths 1 -nworst 1 -hold]
if {[llength $hold_paths] == 0 || [get_property SLACK [lindex $hold_paths 0]] < 0} {
    error "Hold timing failed"
}

write_checkpoint -force [file join $out kc705_j2_safe_io.dcp]
write_bitstream -force [file join $out kc705_j2_safe_io.bit]
puts "KC705_J2_SAFE_IO_BUILD_OK"
exit
