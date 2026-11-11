set here [file dirname [file normalize [info script]]]
set properties {PACKAGE_PIN IOSTANDARD DIRECTION DRIVE SLEW DIFF_TERM PULLTYPE}
set baseline {C:/Users/fpga.DESKTOP-CVDV1JP/kc705_adc_clockdiag/build/kc705_adc_clockdiag.dcp}
open_checkpoint $baseline
set expected [dict create]
foreach p [get_ports] {
    set port_name [get_property NAME $p]
    foreach property $properties { dict set expected $port_name $property [get_property $property $p] }
}
set design_props {BITSTREAM.CONFIG.UNUSEDPIN CFGBVS CONFIG_VOLTAGE}
set baseline_design [dict create]
foreach p $design_props { dict set baseline_design $p [get_property $p [current_design]] }
close_design
open_checkpoint [file join $here build kc705_adc_capture.dcp]
foreach port [dict keys $expected] {
    set object [get_ports -quiet $port]
    if {[llength $object] != 1} { error "Original port missing: $port" }
    foreach property $properties {
        set actual [get_property $property $object]
        set wanted [dict get $expected $port $property]
        if {$actual ne $wanted} { error "$port $property changed: $wanted -> $actual" }
    }
}
foreach p $design_props {
    if {[get_property $p [current_design]] ne [dict get $baseline_design $p]} { error "$p changed" }
}
foreach p [get_ports] {
    if {![dict exists $expected $p] && $p ni {iic_scl_main iic_sda_main}} { error "Unexpected added port $p" }
}
puts "ORIGINAL_PORT_PROPERTIES_IDENTICAL count=[dict size $expected]"
puts "DESIGN_ELECTRICAL_CONFIGURATION_IDENTICAL"
report_bus_skew -file [file join $here build bus_skew.rpt]
# Check the actual routed stable-data bus as well as its bit-to-bit skew.
# The toggle crosses three 5 ns stages before the data is captured; keep
# direct Q-to-D routing below 10 ns, leaving margin for clock-to-Q/setup.
set sources [get_cells -hier -filter {NAME =~ word_snapshot/held_words_reg*}]
set destinations [get_cells -hier -filter {NAME =~ word_snapshot/destination_words_reg*}]
if {[llength $sources] != 60 || [llength $destinations] != 60} {
    error "Expected 60 source and destination packet registers"
}
set endpoints [get_pins -of_objects $destinations -filter {REF_PIN_NAME == D}]
set f [open [file join $here build snapshot_route_delays.tsv] w]
puts $f "PIN\tSLOW_MAX_PS\tFAST_MAX_PS"
set worst_ps 0
foreach pin $endpoints {
    set net [get_nets -of_objects $pin]
    set driver [get_pins -of_objects $net -filter {DIRECTION == OUT}]
    if {[llength $driver] != 1 || ![string match {word_snapshot/held_words_reg*} $driver]} {
        error "Packet bus is not a direct registered connection: $pin <- $driver"
    }
    set delays [get_net_delays -of_objects $net -to $pin]
    if {[llength $delays] != 1} { error "Missing routed delay for $pin" }
    set slow [get_property SLOW_MAX $delays]
    set fast [get_property FAST_MAX $delays]
    set worst_ps [expr {max($worst_ps, $slow, $fast)}]
    puts $f "$pin\t$slow\t$fast"
}
close $f
if {$worst_ps >= 10000} { error "Snapshot route delay exceeds 10 ns: $worst_ps ps" }
puts "SNAPSHOT_ROUTED_60_BIT_BUS_PASS worst_ps=$worst_ps"
close_design
exit
