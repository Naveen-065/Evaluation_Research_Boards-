# Programs the same 25 MHz -> 900 MHz PLL -> 2 MHz output configuration used
# in Evaluation_Research_Boards-/si5351_mode_controller.v.
set here [file dirname [file normalize [info script]]]
source [file join $here i2c_host.tcl]
mux_select_fmc
if {[mux_read] != 0x04} { error "U49 did not retain FMC channel 2" }
after 20
set status0 [si5351_read 0]
set deadline [expr {[clock milliseconds] + 1000}]
while {$status0 & 0x80} {
    if {[clock milliseconds] > $deadline} { error "Si5351 SYS_INIT stayed high" }
    after 10
    set status0 [si5351_read 0]
}
if {$status0 & 0x08} { error "Si5351 crystal-loss flag is set" }

set sequence [list [list 3 0xFF]]
for {set reg 16} {$reg <= 23} {incr reg} { lappend sequence [list $reg 0x80] }
lappend sequence [list 183 0xD2] [list 149 0x00]
set pll_bytes [list 0x00 0x01 0x00 0x10 0x00 0x00 0x00 0x00]
for {set i 0} {$i < 8} {incr i} { lappend sequence [list [expr {26+$i}] [lindex $pll_bytes $i]] }
set ms_bytes [list 0x00 0x01 0x00 0xDF 0x00 0x00 0x00 0x00]
for {set output 0} {$output < 3} {incr output} {
    for {set i 0} {$i < 8} {incr i} {
        lappend sequence [list [expr {42+8*$output+$i}] [lindex $ms_bytes $i]]
    }
}
lappend sequence [list 16 0x4F] [list 17 0x4F] [list 18 0x4F]
lappend sequence [list 177 0xAC] [list 3 0xF8]

foreach pair $sequence {
    lassign $pair reg value
    si5351_write $reg $value
    # Register 177 contains reset strobes and is not a stable readback value.
    if {$reg != 177} {
        set actual [si5351_read $reg]
        if {$actual != $value} {
            error [format "Si5351 verify failed reg=%d wanted=0x%02X actual=0x%02X" $reg $value $actual]
        }
    }
}
set deadline [expr {[clock milliseconds] + 1000}]
after 10
set status0 [si5351_read 0]
while {$status0 & 0x68} {
    if {[clock milliseconds] > $deadline} {
        error [format "Si5351 did not lock; status_reg0=0x%02X" $status0]
    }
    after 10
    set status0 [si5351_read 0]
}
puts [format "SI5351_PROGRAMMED_2MHZ status_reg0=0x%02X writes=%d" $status0 [llength $sequence]]
close_i2c_bridge
exit
