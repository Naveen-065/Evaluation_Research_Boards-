set here [file dirname [file normalize [info script]]]
set out [file join $here build_portable]
file mkdir $out
create_project -force kc705_cell_control_portable [file join $here vivado_project_portable] -part xc7k325tffg900-2
set_property target_language Verilog [current_project]
# Regenerate the packaged Xilinx IP; preserve both ADC/DAC INIT=0 interlocks.
# This new portable build path has not been run through hardware validation.
foreach name {adc_run_vio adc_capture_ila vadj_vio scan_read_vio} {
    read_ip [file join $here ip $name "$name.xci"]
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
generate_target all [get_ips]
synth_ip [get_ips]
add_files [list [file join $here cell_control_engine.v] [file join $here runtime_dac_spi.v] [file join $here uart_rx_8n1.v]]
add_files [list [file join $here kc705_adc_test.v] [file join $here i2c_transaction_bridge.v] [file join $here adc_return_clock_monitor.v] [file join $here adc_word_snapshot.v]]
read_xdc [file join $here kc705_adc_test.xdc]
read_xdc [file join $here management_i2c.xdc]
read_xdc [file join $here snapshot_timing.xdc]
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
write_debug_probes -force [file join $out kc705_adc_capture.ltx]
write_checkpoint -force [file join $out kc705_adc_capture.dcp]
write_bitstream -force [file join $out kc705_adc_capture.bit]
puts "KC705_CARAVEL_BRINGUP_BUILD_PASS_ADC_DAC_INIT_ZERO"
exit
