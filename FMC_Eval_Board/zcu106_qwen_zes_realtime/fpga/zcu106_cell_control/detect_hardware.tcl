open_hw_manager
connect_hw_server -allow_non_jtag
open_hw_target
set devices [get_hw_devices]
if {[llength $devices] == 0} {
    error "No JTAG devices detected"
}
foreach dev $devices {
    set dna "n/a"
    if {![catch {set value [get_property REGISTER.EFUSE.FUSE_DNA $dev]}] && $value ne ""} {
        set dna $value
    }
    puts [format "DETECTED name=%s part=%s dna=%s" $dev [get_property PART $dev] $dna]
}
close_hw_target
close_hw_manager
exit
