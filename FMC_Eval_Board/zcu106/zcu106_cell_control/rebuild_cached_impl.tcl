set here [file dirname [file normalize [info script]]]
set out [file join $here build]
set_param general.maxThreads 8
open_project [file join $here vivado_project zcu106_cell_control.xpr]
update_compile_order -fileset sources_1

synth_design -top kc705_adc_test -part xczu7ev-ffvc1156-2-e -verilog_define ZCU106
if {[llength [get_debug_cores -quiet dbg_hub]] == 0} { create_debug_core dbg_hub dbg_hub }
set_property C_CLK_INPUT_FREQ_HZ 200000000 [get_debug_cores dbg_hub]
set_property C_ENABLE_CLK_DIVIDER false [get_debug_cores dbg_hub]
set_property C_USER_SCAN_CHAIN 1 [get_debug_cores dbg_hub]
connect_debug_port dbg_hub/clk [get_nets sysclk]

opt_design
if {[catch {place_design -directive Explore} place_message place_options]} {
    puts stderr "PLACE_ERROR=$place_message"
    puts stderr "PLACE_ERRORINFO=[dict get $place_options -errorinfo]"
    error $place_message
}
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

write_debug_probes -force [file join $out zcu106_adc_capture.ltx]
write_checkpoint -force [file join $out zcu106_adc_capture.dcp]
write_bitstream -force [file join $out zcu106_adc_capture.bit]
puts "ZCU106_HPC0_CACHED_REBUILD_PASS"
exit
