set expected_target "localhost:3121/xilinx_tcf/Xilinx/00001f14c98801"

open_hw_manager
connect_hw_server -allow_non_jtag
set target [get_hw_targets -quiet $expected_target]
if {[llength $target] != 1} {
    error "Expected KC705 JTAG target not found: $expected_target"
}
current_hw_target [lindex $target 0]
open_hw_target

set candidates [get_hw_devices -quiet -filter {PART == "xc7k325t"}]
if {[llength $candidates] != 1} {
    error "Expected exactly one xc7k325t on KC705 target; found [llength $candidates]"
}
set dev [lindex $candidates 0]
current_hw_device $dev
refresh_hw_device -update_hw_probes false $dev

puts "CODEX_STATUS_TARGET=$expected_target"
puts "CODEX_STATUS_DEVICE=$dev PART=[get_property PART $dev]"
foreach property [lsort [list_property $dev]] {
    if {[regexp -nocase {(done|program|config|status)} $property]} {
        set value ""
        if {![catch {set value [get_property $property $dev]}]} {
            puts "CODEX_PROPERTY=$property VALUE=$value"
        }
    }
}
puts "CODEX_STATUS_QUERY_OK"

close_hw_target
disconnect_hw_server
close_hw_manager
