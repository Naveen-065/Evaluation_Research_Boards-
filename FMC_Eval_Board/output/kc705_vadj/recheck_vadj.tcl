# Read operating settings and telemetry only; PAGE selection is the only write.
source [file join [file dirname [file normalize [info script]]] pmbus_host.tcl]
puts "LIVE_RECHECK_NO_VOLTAGE_OR_FLASH_WRITES"
foreach pg {0 1 2 3} {
    page $pg
    puts [format "LIVE PAGE=%d SET_RAW=0x%04x SET=%.6f READ=%.6f CML=0x%02x STATUS=0x%04x" $pg [rw_pec 0x21] [expr {[rw_pec 0x21]/4096.0}] [expr {[rw_pec 0x8b]/4096.0}] [rb 0x7e] [rw_pec 0x79]]
}
page 3
close_bridge
