set here [file dirname [file normalize [info script]]]
if {![info exists external_dac_device_open] || !$external_dac_device_open} {
open_hw_manager
connect_hw_server -allow_non_jtag
set t [get_hw_targets -quiet localhost:3121/xilinx_tcf/Digilent/210512180081]
if {[llength $t] != 1} {error "Known external Zynq cable missing"}
current_hw_target $t
open_hw_target
set d [get_hw_devices -quiet -filter {PART == "xc7z020"}]
if {[llength $d] != 1} {error "External Zynq device missing"}
current_hw_device $d
set_property PROBES.FILE [file join $here build external_dac_adc6.ltx] $d
refresh_hw_device $d
}
set v [get_hw_vios -quiet -of_objects $d -filter {CELL_NAME == "runtime_vio"}]
if {[llength $v] != 1} {error "Service VIO missing"}
set cp [get_hw_probes -quiet -of_objects $v -filter {TYPE == vio_output}]
set sp [get_hw_probes -quiet -of_objects $v -filter {TYPE == vio_input}]
if {[llength $cp] != 1 || [llength $sp] != 1} {error "Unexpected probe layout"}
proc get_status {} {
    global v sp
    refresh_hw_vio $v
    return [expr 0x[get_property INPUT_VALUE $sp]]
}
set s [get_status]
if {($s >> 48) != 0xDAC8} {error "Wrong service signature"}
set token [expr {($s >> 32) & 255}]
proc spi {frame} {
    global token cp
    if {[get_status] & (1 << 40)} {error "SPI already busy"}
    set token [expr {($token % 255) + 1}]
    set cmd [format %02X00000000%06X $token $frame]
    set_property OUTPUT_VALUE $cmd $cp
    commit_hw_vio $cp
    set deadline [expr {[clock milliseconds] + 3000}]
    while {1} {
        set s [get_status]
        if {!($s & (1 << 40)) && (($s >> 32) & 255) == $token} {break}
        if {[clock milliseconds] > $deadline} {error "External DAC SPI timeout"}
        after 5
    }
    puts "SPI_TX=[format %06X $frame] SPI_RX=[format %06X [expr {$s & 0xFFFFFF}]]"
    return [expr {$s & 0xFFFFFF}]
}
proc rd {address} {
    spi [expr {(0x80 | $address) << 16}]
    return [expr {[spi 0] & 0xFFFF}]
}
proc wr {address value} { spi [expr {($address << 16) | $value}] }
proc close_spi {} { close_hw_target; disconnect_hw_server; close_hw_manager }
