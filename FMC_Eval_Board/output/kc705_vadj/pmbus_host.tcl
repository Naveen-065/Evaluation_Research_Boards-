# Host access only. Sourcing this file opens the known board but issues no PMBus traffic.
set here [file dirname [file normalize [info script]]]
open_hw_manager
connect_hw_server -allow_non_jtag
set target [get_hw_targets -quiet localhost:3121/xilinx_tcf/Xilinx/00001f14c98801]
if {[llength $target] != 1} { error "Known KC705 JTAG cable not found" }
current_hw_target $target
open_hw_target
set dev [get_hw_devices -quiet -filter {PART == "xc7k325t"}]
if {[llength $dev] != 1} { error "Expected exactly one Kintex-7 xc7k325t" }
current_hw_device $dev
set_property PROBES.FILE [file join $here build kc705_vadj_bridge.ltx] $dev
refresh_hw_device $dev
set vio [get_hw_vios -quiet -of_objects $dev]
if {[llength $vio] != 1} { error "Expected one VIO in the voltage-control bridge" }
set cmdprobe [get_hw_probes -quiet -of_objects $vio -filter {TYPE == vio_output}]
set statprobe [get_hw_probes -quiet -of_objects $vio -filter {TYPE == vio_input}]
if {[llength $cmdprobe] != 1 || [llength $statprobe] != 1} { error "Unexpected VIO probes" }
proc read_status {} {
    global vio statprobe
    refresh_hw_vio $vio
    set hex [get_property INPUT_VALUE $statprobe]
    return [expr 0x$hex]
}
proc to_hex128 {value} {
    set result ""
    for {set n 0} {$n < 32} {incr n} {
        set result "[string index 0123456789abcdef [expr {$value & 15}]]$result"
        set value [expr {$value >> 4}]
    }
    if {$value != 0} { error "Command overflow" }
    return $result
}
set token [expr {[read_status] & 255}]
proc transfer {bytes nr} {
    global token cmdprobe
    if {[llength $bytes] < 1 || [llength $bytes] > 8 || $nr < 0 || $nr > 8} { error "Bad transaction length" }
    set s [read_status]
    if {$s & 256} { error "Bridge is already busy" }
    set token [expr {($token % 255) + 1}]
    set cmd [expr {$token | (0x34 << 8) | ([llength $bytes] << 15) | ($nr << 19)}]
    set shift 23
    foreach b $bytes {
        if {$b < 0 || $b > 255} { error "Bad byte" }
        set cmd [expr {$cmd | ($b << $shift)}]
        incr shift 8
    }
    set_property OUTPUT_VALUE [to_hex128 $cmd] $cmdprobe
    commit_hw_vio $cmdprobe
    set deadline [expr {[clock milliseconds] + 10000}]
    while {1} {
        set s [read_status]
        if {($s & 255) == $token && !($s & 256)} { break }
        if {[clock milliseconds] > $deadline} { error "Bridge completion timeout" }
        after 10
    }
    if {$s & 512} { error "PMBus transaction failed: code=[expr {($s >> 10) & 63}], status=[to_hex128 $s]" }
    set acked [expr {($s >> 80) & 255}]
    if {$acked != [llength $bytes]} { error "Incomplete write ACK count $acked" }
    set result {}
    for {set i 0} {$i < $nr} {incr i} { lappend result [expr {($s >> (16+8*$i)) & 255}] }
    return $result
}
proc rb {reg} { return [lindex [transfer [list $reg] 1] 0] }
proc rw {reg} {
    set b [transfer [list $reg] 2]
    return [expr {[lindex $b 0] | ([lindex $b 1] << 8)}]
}
# SMBus CRC-8; optional PEC catches transport corruption before any voltage write.
proc crc8 {bytes} {
    set crc 0
    foreach b $bytes {
        set crc [expr {$crc ^ $b}]
        for {set i 0} {$i < 8} {incr i} {
            if {$crc & 128} {set crc [expr {(($crc << 1) ^ 7) & 255}]} else {set crc [expr {($crc << 1) & 255}]}
        }
    }
    return $crc
}
proc rw_pec {reg} {
    set b [transfer [list $reg] 3]
    set expected [crc8 [list 0x68 $reg 0x69 [lindex $b 0] [lindex $b 1]]]
    if {[lindex $b 2] != $expected} {error "PMBus read PEC mismatch at command $reg"}
    return [expr {[lindex $b 0] | ([lindex $b 1] << 8)}]
}
proc write_vadj_word {reg value} {
    # Only voltage-dependent settings on U55 PAGE3 are permitted.
    set reg [expr {$reg}]
    if {$reg ni {33 36 37 38 64 66 67 68 72 94 95}} {error "Register is not permitted for VADJ adjustment"}
    if {[rb 0] != 3 || [rb 0x20] != 0x14} {error "VADJ page/mode guard failed"}
    if {$value < 0 || $value > 13108} {error "Voltage write outside guarded range"}
    if {$reg == 33 && $value != 7373} {error "Only 1.8 V VOUT_COMMAND is permitted"}
    set bytes [list $reg [expr {$value & 255}] [expr {($value >> 8) & 255}]]
    lappend bytes [crc8 [linsert $bytes 0 0x68]]
    transfer $bytes 0
    set readback [rw_pec $reg]
    if {abs($readback - $value) > 5} {error "Voltage register readback mismatch: register=$reg wanted=$value actual=$readback"}
    return $readback
}
proc page {n} {
    if {$n < 0 || $n > 3} { error "Invalid U55 page" }
    transfer [list 0 $n] 0
    if {[rb 0] != $n} { error "PAGE verification failed" }
}
proc close_bridge {} {
    close_hw_target
    disconnect_hw_server
    close_hw_manager
}
