set here [file dirname [file normalize [info script]]]
set out [file join $here build]
file mkdir $out

create_project -force kc705_adc_test [file join $here vivado_project] -part xc7k325tffg900-2
set_property target_language Verilog [current_project]

# Two fixed-purpose enables.  Both INIT values are zero, so every FPGA
# configuration holds the ADC and DAC in reset with their serial ports idle.
create_ip -name vio -vendor xilinx.com -library ip -module_name adc_run_vio
set_property -dict [list \
    CONFIG.C_NUM_PROBE_IN {1} \
    CONFIG.C_NUM_PROBE_OUT {2} \
    CONFIG.C_PROBE_IN0_WIDTH {32} \
    CONFIG.C_PROBE_OUT0_WIDTH {1} \
    CONFIG.C_PROBE_OUT0_INIT_VAL {0x0} \
    CONFIG.C_PROBE_OUT1_WIDTH {1} \
    CONFIG.C_PROBE_OUT1_INIT_VAL {0x0}] [get_ips adc_run_vio]
generate_target all [get_ips adc_run_vio]
synth_ip [get_ips adc_run_vio]

# LCLK-domain diagnostic capture.  Five completed words, five live shift
# registers, raw IDDR bits, controller status and the 0..5 pair counter.
create_ip -name ila -vendor xilinx.com -library ip -module_name adc_capture_ila
set_property -dict [list \
    CONFIG.C_DATA_DEPTH {4096} \
    CONFIG.C_NUM_OF_PROBES {5} \
    CONFIG.C_PROBE0_WIDTH {60} \
    CONFIG.C_PROBE1_WIDTH {60} \
    CONFIG.C_PROBE2_WIDTH {12} \
    CONFIG.C_PROBE3_WIDTH {32} \
    CONFIG.C_PROBE4_WIDTH {4}] [get_ips adc_capture_ila]
generate_target all [get_ips adc_capture_ila]
synth_ip [get_ips adc_capture_ila]

add_files [file join $here kc705_adc_test.v]
read_xdc [file join $here kc705_adc_test.xdc]
synth_design -top kc705_adc_test -part xc7k325tffg900-2

# The debug transport must remain live while the ADC/LCLK domain is stopped,
# otherwise VIO could not release the fixed run interlock.  Bind dbg_hub to the
# always-running 200 MHz KC705 system clock explicitly.
if {[llength [get_debug_cores -quiet dbg_hub]] == 0} {
    create_debug_core dbg_hub dbg_hub
}
set_property C_CLK_INPUT_FREQ_HZ 200000000 [get_debug_cores dbg_hub]
set_property C_ENABLE_CLK_DIVIDER false [get_debug_cores dbg_hub]
set_property C_USER_SCAN_CHAIN 1 [get_debug_cores dbg_hub]
connect_debug_port dbg_hub/clk [get_nets sysclk]

# Fail early if the safety VIO was regenerated with a nonzero initial value.
set vio_init [get_property CONFIG.C_PROBE_OUT0_INIT_VAL [get_ips adc_run_vio]]
if {![regexp -nocase {^(0x)?0+$} $vio_init]} {
    error "adc_run_vio must have INIT=0"
}
set dac_vio_init [get_property CONFIG.C_PROBE_OUT1_INIT_VAL [get_ips adc_run_vio]]
if {![regexp -nocase {^(0x)?0+$} $dac_vio_init]} {
    error "adc_run_vio DAC enable must have INIT=0"
}

opt_design
place_design
phys_opt_design
route_design

report_timing_summary -file [file join $out timing_summary.rpt]
report_drc -file [file join $out drc.rpt]
report_methodology -file [file join $out methodology.rpt]
report_route_status -file [file join $out route_status.rpt]
report_io -file [file join $out io.rpt]
report_clock_utilization -file [file join $out clock_utilization.rpt]
report_bus_skew -file [file join $out bus_skew.rpt]

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

write_debug_probes -force [file join $out kc705_adc_test.ltx]
write_checkpoint -force [file join $out kc705_adc_test.dcp]
write_bitstream -force [file join $out kc705_adc_test.bit]
puts "KC705_ADC_TEST_BUILD_OK"
puts "SAFE_STARTUP: ADC and DAC VIO enables INIT=0; both devices held in reset"
exit
