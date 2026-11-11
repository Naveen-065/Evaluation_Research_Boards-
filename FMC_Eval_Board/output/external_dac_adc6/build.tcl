set here [file dirname [file normalize [info script]]]
set out [file join $here build]
file mkdir $out
create_project -force external_dac_adc6 [file join $here vivado_project] -part xc7z020clg400-2
read_ip {C:/Users/fpga.DESKTOP-CVDV1JP/zynq_scan_debug/vivado_project_scan_debug_runtime/vivado_project_scan_debug_runtime.srcs/sources_1/ip/vio_runtime_command/vio_runtime_command.xci}
if {![regexp -nocase {^(0x)?0+$} [get_property CONFIG.C_PROBE_OUT0_INIT_VAL [get_ips vio_runtime_command]]]} {error "VIO command must initialize to zero"}
read_verilog [file join $here external_dac_spi.v]
synth_design -top external_dac_spi -part xc7z020clg400-2
foreach {port pin} {sys_clk_50m_i U18 dac_sclk_o V12 dac_sdi_o U12 dac_cs_n_o T12 dac_ldac_n_o T10 dac_sdo_i T11} {
    set_property PACKAGE_PIN $pin [get_ports $port]
    set_property IOSTANDARD LVCMOS33 [get_ports $port]
}
# Same external-board SPI output strength and slew as the evaluation project.
set_property DRIVE 8 [get_ports {dac_sclk_o dac_sdi_o dac_cs_n_o dac_ldac_n_o}]
set_property SLEW SLOW [get_ports {dac_sclk_o dac_sdi_o dac_cs_n_o dac_ldac_n_o}]
set_property PULLTYPE NONE [get_ports *]
set_property BITSTREAM.CONFIG.UNUSEDPIN Pullnone [current_design]
set_property CFGBVS VCCO [current_design]
set_property CONFIG_VOLTAGE 3.3 [current_design]
create_clock -period 20.000 -name sys_clk_50m_i [get_ports sys_clk_50m_i]
set_input_delay -clock sys_clk_50m_i -max 100.0 [get_ports dac_sdo_i]
set_input_delay -clock sys_clk_50m_i -min 0.0 [get_ports dac_sdo_i]
# SPI is sampled 1 us after the transmit/SDO launch edge. The register's
# clock-enable provides this multicycle; 40 cycles leaves 200 ns margin.
set_multicycle_path 40 -setup -from [get_ports dac_sdo_i]
set_multicycle_path 39 -hold -from [get_ports dac_sdo_i]
set_output_delay -clock sys_clk_50m_i -max 5.0 [get_ports {dac_sclk_o dac_sdi_o dac_cs_n_o dac_ldac_n_o}]
set_output_delay -clock sys_clk_50m_i -min 0.0 [get_ports {dac_sclk_o dac_sdi_o dac_cs_n_o dac_ldac_n_o}]
if {![llength [get_debug_cores -quiet dbg_hub]]} { create_debug_core dbg_hub dbg_hub }
set_property C_CLK_INPUT_FREQ_HZ 50000000 [get_debug_cores dbg_hub]
connect_debug_port dbg_hub/clk [get_nets sys_clk_50m_i]
opt_design
place_design
route_design
report_timing_summary -file [file join $out timing.rpt]
report_drc -file [file join $out drc.rpt]
report_route_status -file [file join $out route.rpt]
report_io -file [file join $out io.rpt]
report_bus_skew -file [file join $out bus_skew.rpt]
if {[llength [get_drc_violations -quiet -filter {SEVERITY == "Error" || SEVERITY == "Critical Warning"}]]} { error "Critical DRC" }
foreach type {setup hold} {
    set p [get_timing_paths -max_paths 1 -$type]
    if {![llength $p] || [get_property SLACK [lindex $p 0]] < 0} {error "$type timing failed"}
}
write_debug_probes -force [file join $out external_dac_adc6.ltx]
write_checkpoint -force [file join $out external_dac_adc6.dcp]
write_bitstream -force [file join $out external_dac_adc6.bit]
puts "EXTERNAL_DAC_SERVICE_BUILD_PASS_NO_AUTOMATIC_WRITES"
exit
