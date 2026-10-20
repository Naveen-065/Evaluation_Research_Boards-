# Host-side VIO access for the KC705 IIC_MAIN bus.
# Sourcing this file opens the known board but does not issue I2C traffic.
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
set_property PROBES.FILE [file join $here build kc705_dac_pcb.ltx] $dev
refresh_hw_device $dev
set vio [get_hw_vios -quiet -of_objects $dev -filter {CELL_NAME == "u_i2c_vio"}]
if {[llength $vio] != 1} { error "Expected one VIO in the I2C bridge" }
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

# One transaction. Address is seven bit; bytes and returned bytes are in bus order.
# An empty byte list with nr>0 performs an address-write ACK followed by a
# repeated-start read. This safely reads U49 without changing its control byte.
proc i2c_transfer {addr bytes nr} {
    global token cmdprobe
    if {$addr < 0 || $addr > 0x7f} { error "Bad 7-bit I2C address" }
    if {[llength $bytes] > 8 || $nr < 0 || $nr > 8 || ([llength $bytes] == 0 && $nr == 0)} {
        error "Bad transaction length"
    }
    set s [read_status]
    if {$s & 256} { error "I2C bridge is already busy" }
    set token [expr {($token % 255) + 1}]
    set cmd [expr {$token | ($addr << 8) | ([llength $bytes] << 15) | ($nr << 19)}]
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
        if {[clock milliseconds] > $deadline} { error "I2C bridge completion timeout" }
        after 10
    }
    if {$s & 512} {
        error "I2C transaction failed: address=0x[format %02X $addr], code=[expr {($s >> 10) & 63}], status=[to_hex128 $s]"
    }
    set acked [expr {($s >> 80) & 255}]
    if {$acked != [llength $bytes]} { error "Incomplete write ACK count $acked" }
    set result {}
    for {set i 0} {$i < $nr} {incr i} {
        lappend result [expr {($s >> (16+8*$i)) & 255}]
    }
    return $result
}
proc mux_select_fmc {} { i2c_transfer 0x74 [list 0x04] 0 }
proc mux_read {} { return [lindex [i2c_transfer 0x74 [list] 1] 0] }
proc si5351_read {reg} { return [lindex [i2c_transfer 0x60 [list $reg] 1] 0] }
proc si5351_write {reg value} { i2c_transfer 0x60 [list $reg $value] 0 }
proc close_i2c_bridge {} {
    close_hw_target
    disconnect_hw_server
    close_hw_manager
}

