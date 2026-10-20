set here [file dirname [file normalize [info script]]]
set properties {PACKAGE_PIN IOSTANDARD DIRECTION DRIVE SLEW DIFF_TERM PULLTYPE}
set baseline {C:/Users/fpga.DESKTOP-CVDV1JP/kc705_adc_test/build/kc705_adc_test.dcp}
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
open_checkpoint [file join $here build kc705_caravel_bringup.dcp]
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
close_design
exit
