# The loaded image is identified by its scan VIO signature. Never auto-program.
set here [file dirname [file normalize [info script]]]
if {$argc != 3} { error "Usage: status|enable|read row col" }
set action [lindex $argv 0]
set row [lindex $argv 1]
set col [lindex $argv 2]
if {$action ni {status enable read} || ![string is integer -strict $row] || ![string is integer -strict $col] || $row<0 || $row>31 || $col<0 || $col>31} { error "Invalid read request" }
source [file join $here i2c_host.tcl]
set sv [get_hw_vios -quiet -of_objects $dev -filter {CELL_NAME == "u_scan_vio"}]
if {[llength $sv]!=1} { error "Scan-read image is not loaded" }
set cp [get_hw_probes -quiet scan_command -of_objects $sv -filter {TYPE == vio_output}]
set rp0 [get_hw_probes -quiet scan_result0 -of_objects $sv -filter {TYPE == vio_input}]
set rp1 [get_hw_probes -quiet scan_result1 -of_objects $sv -filter {TYPE == vio_input}]
if {[llength $cp]!=1 || [llength $rp0]!=1 || [llength $rp1]!=1} { error "Scan VIO layout mismatch" }
proc status_read {} {
    global sv rp0 rp1
    refresh_hw_vio $sv
    return [list [get_property INPUT_VALUE $rp0] [get_property INPUT_VALUE $rp1]]
}
lassign [status_read] h0 h1
if {([expr 0x$h1] >>224)!=0x53435231} { error "Scan-read image signature mismatch" }
if {$action ne "status"} {
    source [file join $here assert_clock.tcl]
    assert_caravel_clock
    if {([expr 0x$h0] & 256)!=0} { error "Scan controller already busy" }
    set old [expr 0x[get_property OUTPUT_VALUE $cp]]
    set toggle [expr {1-(($old>>63)&1)}]
    set value [expr {($toggle<<63) | (1<<62) | ($col<<5) | $row}]
    if {$action eq "read"} {
        if {(([expr 0x$h0]>>36)&1)!=1 || (([expr 0x$h0]>>32)&1)!=1} { error "ADC healthy / scan interface enabled required" }
        set value [expr {$value | (1<<61)}]
    }
    set_property OUTPUT_VALUE [format %016llX $value] $cp
    commit_hw_vio $cp
    set deadline [expr {[clock milliseconds]+5000}]
    while {1} {
        after 10
        lassign [status_read] h0 h1
        set s [expr 0x$h0]
        if {$action eq "enable" && (($s>>32)&1)} { break }
        if {$action eq "read" && (($s>>15)&1)==$toggle && ($s&512) && !($s&256)} { break }
        if {[clock milliseconds]>$deadline} { error "Read/enable timeout; inspect controller" }
    }
    if {$s&1024} { error "Scan fault code [expr {($s>>11)&15}]; result=$h0" }
}
puts "SCAN_RESULT0=$h0"
puts "SCAN_RESULT1=$h1"
puts "SCAN_ACTION=$action"
close_i2c_bridge
exit
