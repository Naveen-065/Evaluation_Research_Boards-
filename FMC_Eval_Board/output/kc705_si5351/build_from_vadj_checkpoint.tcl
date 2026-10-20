# Reuses the already implemented generic VIO I2C bridge and moves only its
# open-drain SCL/SDA I/O cells from the KC705 PMBus pins to IIC_MAIN.
set here [file dirname [file normalize [info script]]]
set out [file join $here build]
file mkdir $out
open_checkpoint {C:/Users/fpga.DESKTOP-CVDV1JP/kc705_vadj/build/kc705_vadj_bridge.dcp}
set_property PACKAGE_PIN K21 [get_ports pmbus_scl]
set_property PACKAGE_PIN L21 [get_ports pmbus_sda]
set_property IOSTANDARD LVCMOS25 [get_ports {pmbus_scl pmbus_sda}]
set_property DRIVE 4 [get_ports {pmbus_scl pmbus_sda}]
set_property SLEW SLOW [get_ports {pmbus_scl pmbus_sda}]

# R307 on the KC705 pulls U49 RESET_B to 2.5 V, so P23 can remain unused.
# Route again so the two relocated I/O cells receive valid routes.
route_design
report_route_status -file [file join $out route_status.rpt]
report_timing_summary -file [file join $out timing_summary.rpt]
report_drc -file [file join $out drc.rpt]
report_io -file [file join $out io.rpt]

set bad [get_drc_violations -quiet -filter {SEVERITY == "Error" || SEVERITY == "Critical Warning"}]
if {[llength $bad]} { error "Critical DRC: $bad" }
set unrouted [get_nets -hier -filter {ROUTE_STATUS != "ROUTED" && ROUTE_STATUS != "INTRASITE" && ROUTE_STATUS != "NOLOADS"}]
if {[llength $unrouted]} { error "Unrouted nets remain: $unrouted" }
set paths [get_timing_paths -max_paths 1 -nworst 1 -setup]
if {[llength $paths] == 0 || [get_property SLACK [lindex $paths 0]] < 0} { error "Setup timing failed" }
set holds [get_timing_paths -max_paths 1 -nworst 1 -hold]
if {[llength $holds] == 0 || [get_property SLACK [lindex $holds 0]] < 0} { error "Hold timing failed" }

write_debug_probes -force [file join $out kc705_si5351_bridge.ltx]
write_checkpoint -force [file join $out kc705_si5351_bridge.dcp]
write_bitstream -force [file join $out kc705_si5351_bridge.bit]
puts "SI5351_BRIDGE_CHECKPOINT_BUILD_OK"
exit
