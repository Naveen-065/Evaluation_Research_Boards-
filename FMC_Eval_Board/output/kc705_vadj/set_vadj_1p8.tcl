# Run only after inspect_controller.tcl has produced a reviewed baseline.
# This changes operating RAM only. It never stores flash or restores defaults.
source [file join [file dirname [file normalize [info script]]] pmbus_host.tcl]
set f [open [file join $here controller_before.txt] r]
set baseline [read $f]
close $f
array set before {}
foreach line [split $baseline "\n"] {
    if {[regexp {^PAGE=([0-3]) (BYTE|WORD) (0x[0-9a-f]+)=(0x[0-9a-f]+)} $line -> pg kind reg val]} {
        set before($pg,[expr {$reg}]) [list $kind [expr {$val}]]
    }
}
if {[array size before] != 136} {error "Incomplete baseline; expected 34 registers for each of four pages"}
set log [open [file join $here change_1p8.txt] {WRONLY CREAT EXCL}]
proc record {line} {global log; puts $line; puts $log $line; flush $log}
proc old {pg reg} {global before; return [lindex $before($pg,[expr {$reg}]) 1]}
record "BEGIN_VOLATILE_VADJ_CHANGE"
if {![regexp {DEVICE_ID_FIRST_BYTES=30 85 67 68 57 50 52 56} $baseline]} {error "Baseline did not identify UCD9248"}
# Do not repeat the deliberately shortened 30-byte ID block read: that latches CML.
if {[transfer {210} 5] ne {4 1 4 16 64}} {error "Unexpected U55 phase mapping"}
foreach pg {0 1 2 3} {
    page $pg
    foreach reg {0x01 0x02 0x20 0x41 0x45} {
        if {[rb $reg] != [old $pg $reg]} {error "Controller byte setting changed since baseline"}
    }
    foreach reg {0x21 0x23 0x24 0x25 0x26 0x27 0x29 0x2a 0x40 0x42 0x43 0x44 0x48 0x5e 0x5f 0x60 0x61 0x62 0x64 0x65 0x66} {
        if {[rw_pec $reg] != [old $pg $reg]} {error "Controller word setting changed since baseline"}
    }
    if {[rb 0x7a] != 0 || [rb 0x7e] != 0} {error "Existing voltage or communication fault; stop before writing"}
}
page 3
if {[old 3 0x01] ni {0 64 128}} {error "VADJ is in margin mode; stop before changing voltage"}
if {[rb 0x20] != 0x14 || abs([old 3 0x21]/4096.0 - 2.5) > 0.005} {error "Expected 2.5 V VADJ in LINEAR16 mode"}
if {abs([rw_pec 0x8b]/4096.0 - 2.5) > 0.075} {error "VADJ telemetry does not match the measured 2.5 V"}
set ratio [expr {1.8 / ([old 3 0x21]/4096.0)}]
array set targets {}
# Preserve margin and OV/UV ratios. Calibration, loop scaling, rates and VOUT_MAX are unchanged.
foreach reg {0x25 0x26 0x40 0x42 0x43 0x44 0x48} {set targets([expr {$reg}]) [expr {round([old 3 $reg] * $ratio)}]}
set targets(33) 7373
# PG values already below nominal 1.8 V are retained; adjust only incompatible old thresholds.
if {[old 3 0x5e] > round(1.71*4096) || [old 3 0x5f] > round(1.65*4096)} {
    set targets(94) [expr {round(1.62*4096)}]
    set targets(95) [expr {round(1.53*4096)}]
}
foreach reg [lsort -integer [array names targets]] {
    record [format "PLAN reg=0x%02x old=%.6f target=%.6f" $reg [expr {[old 3 $reg]/4096.0}] [expr {$targets($reg)/4096.0}]]
}
if {$targets(64) <= $targets(66) || $targets(66) <= 7373 || $targets(67) >= 7373 || $targets(68) > $targets(67)} {error "Invalid OV/UV ordering"}
# Lower fault and warning thresholds before decreasing the rail.
foreach reg {68 67 72 95 94} {
    if {[info exists targets($reg)]} {
        record [format "WRITE reg=0x%02x readback=0x%04x" $reg [write_vadj_word $reg $targets($reg)]]
    }
}
record [format "WRITE reg=0x21 readback=0x%04x" [write_vadj_word 33 7373]]
after 300
for {set n 0} {$n < 5} {incr n} {
    set v [expr {[rw_pec 0x8b]/4096.0}]
    record [format "VADJ_SAMPLE=%d VOLTS=%.6f" $n $v]
    if {$v < 1.746 || $v > 1.854} {error "VADJ not within 3 percent of 1.8 V; no further writes"}
    if {[rb 0x7a] != 0 || [rb 0x7e] != 0} {error "Voltage or communication fault after lowering; no further writes"}
    after 100
}
foreach reg {38 37 66 64} {
    record [format "WRITE reg=0x%02x readback=0x%04x" $reg [write_vadj_word $reg $targets($reg)]]
}
# Confirm every saved setting is unchanged except the explicit PAGE3 targets.
foreach pg {0 1 2 3} {
    page $pg
    foreach key [array names before "$pg,*"] {
        set reg [lindex [split $key ,] 1]
        if {$reg >= 0x79 && $reg <= 0x8b} {continue}
        lassign $before($key) kind wanted
        if {$pg == 3 && [info exists targets($reg)]} {set wanted $targets($reg)}
        if {$kind eq "BYTE"} {set got [rb $reg]; set tol 0} else {set got [rw_pec $reg]; set tol 0}
        if {$pg == 3 && [info exists targets($reg)]} {set tol 5}
        if {abs($got-$wanted) > $tol} {error "Post-change verification failed PAGE=$pg register=$reg"}
        record [format "VERIFIED PAGE=%d %s 0x%02x=0x%04x" $pg $kind $reg $got]
    }
    set v [expr {[rw_pec 0x8b]/4096.0}]
    set ref [expr {$pg == 3 ? 1.8 : [old $pg 0x21]/4096.0}]
    record [format "FINAL PAGE=%d VOLTS=%.6f STATUS_WORD=0x%04x STATUS_VOUT=0x%02x STATUS_CML=0x%02x" $pg $v [rw_pec 0x79] [rb 0x7a] [rb 0x7e]]
    if {abs($v-$ref) > 0.03*$ref} {error "Rail telemetry outside tolerance after change"}
    if {[rb 0x7a] != 0 || [rb 0x7e] != 0} {error "Post-change fault; do not persist"}
}
page 3
record "VADJ_VOLATILE_CHANGE_OK_NOT_STORED_TO_FLASH"
close $log
close_bridge
