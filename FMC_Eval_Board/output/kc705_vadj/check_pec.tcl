source [file join [file dirname [file normalize [info script]]] pmbus_host.tcl]
page 3
puts [format "BEFORE_CML=0x%02x STATUS=0x%04x" [rb 0x7e] [rw 0x79]]
# Initial short DEVICE_ID block read may latch OTHER_COMMUNICATION_ERROR.
# Baseline has been saved. No VOUT/IOUT/input/temperature faults were present.
foreach pg {0 1 2 3} {
    page $pg
    foreach reg {0x7a 0x7b 0x7c 0x7d 0x80} {
        if {[rb $reg] != 0} {error "Non-communication fault present; do not clear"}
    }
}
if {[rb 0x7e] != 2} {error "Expected only the recorded OTHER_COMMUNICATION_ERROR"}
transfer {3} 0
after 100
puts [format "AFTER_CLEAR_CML=0x%02x STATUS=0x%04x" [rb 0x7e] [rw 0x79]]
foreach pg {0 1 2 3} {
    page $pg
    puts [format "PEC_OK PAGE=%d SET=%.6f READ=%.6f CML=0x%02x STATUS=0x%04x" $pg [expr {[rw_pec 0x21]/4096.0}] [expr {[rw_pec 0x8b]/4096.0}] [rb 0x7e] [rw_pec 0x79]]
    if {[rb 0x7e] != 0} {error "Communication error recurred with complete PEC reads"}
}
page 3
puts "VADJ_PEC_CHECK_OK_NO_VOLTAGE_CHANGED"
close_bridge
