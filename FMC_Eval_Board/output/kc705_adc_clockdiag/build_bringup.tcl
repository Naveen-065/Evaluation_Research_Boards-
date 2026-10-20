set here [file dirname [file normalize [info script]]]
set out [file join $here build]
file mkdir $out
set base {C:/Users/fpga.DESKTOP-CVDV1JP}
create_project -force kc705_adc_clockdiag [file join $here vivado_project] -part xc7k325tffg900-2
set_property target_language Verilog [current_project]
# Reuse already-generated OOC IP, preserving both ADC/DAC INIT=0 interlocks.
foreach xci [list \
    $base/kc705_adc_test/vivado_project/kc705_adc_test.srcs/sources_1/ip/adc_run_vio/adc_run_vio.xci \
    $base/kc705_adc_test/vivado_project/kc705_adc_test.srcs/sources_1/ip/adc_capture_ila/adc_capture_ila.xci \
    $base/kc705_vadj/vivado_project/vadj_bridge.srcs/sources_1/ip/vadj_vio/vadj_vio.xci] {
    read_ip $xci
}
foreach {ip prop} {
    adc_run_vio CONFIG.C_PROBE_OUT0_INIT_VAL
    adc_run_vio CONFIG.C_PROBE_OUT1_INIT_VAL
    vadj_vio CONFIG.C_PROBE_OUT0_INIT_VAL
} {
    if {![regexp -nocase {^(0x)?0+$} [get_property $prop [get_ips $ip]]]} {
        error "$ip $prop must remain zero"
    }
}
add_files [list [file join $here kc705_adc_test.v] [file join $here i2c_transaction_bridge.v] [file join $here adc_return_clock_monitor.v]]
read_xdc [file join $here kc705_adc_test.xdc]
read_xdc [file join $here management_i2c.xdc]
synth_design -top kc705_adc_test -part xc7k325tffg900-2
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
    if {[llength $paths] == 0 || [get_property SLACK [lindex $paths 0]] < 0} { error "$type timing failed" }
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
write_debug_probes -force [file join $out kc705_adc_clockdiag.ltx]
write_checkpoint -force [file join $out kc705_adc_clockdiag.dcp]
write_bitstream -force [file join $out kc705_adc_clockdiag.bit]
puts "KC705_CARAVEL_BRINGUP_BUILD_PASS_ADC_DAC_INIT_ZERO"
exit
