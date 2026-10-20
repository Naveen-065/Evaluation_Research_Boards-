source [file join [file dirname [file normalize [info script]]] pmbus_host.tcl]
set log [open [file join $here controller_before.txt] w]
proc record {line} {global log; puts $line; puts $log $line; flush $log}
record "PC_TIME=[clock format [clock seconds] -format {%Y-%m-%dT%H:%M:%S%z}]"
record "U55_ADDRESS=0x34"
record "DEVICE_ID_FIRST_BYTES=[transfer {253} 8]"
record "PHASE_INFO=[transfer {210} 5]"
set original_page [rb 0]
record "ORIGINAL_PAGE=$original_page"
foreach pg {0 1 2 3} {
    page $pg
    foreach reg {0x01 0x02 0x20 0x41 0x45 0x7a 0x7b 0x7c 0x7d 0x7e 0x80} {
        record [format "PAGE=%d BYTE 0x%02x=0x%02x" $pg $reg [rb $reg]]
    }
    foreach reg {0x21 0x23 0x24 0x25 0x26 0x27 0x29 0x2a 0x40 0x42 0x43 0x44 0x48 0x5e 0x5f 0x60 0x61 0x62 0x64 0x65 0x66 0x79 0x8b} {
        record [format "PAGE=%d WORD 0x%02x=0x%04x" $pg $reg [rw $reg]]
    }
}
if {$original_page < 4} {page $original_page}
close $log
puts "VADJ_INSPECT_OK"
close_bridge
