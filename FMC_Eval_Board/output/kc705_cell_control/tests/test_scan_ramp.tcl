# Offline fixtures; never connect to hardware.
source [file join [file dirname [file dirname [file normalize [info script]]]] scan_ramp.tcl]
proc assert {condition message} {
 if {![uplevel 1 [list expr $condition]]} { error $message }
}
proc fixture {current r c} {
 set base 2048
 set nb 640; set na 12000
 set active [expr {round(($base+$current*2048.0*392/1e6)*$na)}]
 set a [expr {512 | ((($r<<10)|($c<<5)|$r)<<16) | ($nb<<64) | ($na<<80) | (($base*$nb)<<160)}]
 set b [expr {(0x53435232<<224)|($active<<64)}]
 # Tcl format does not reliably format arbitrary-width integers.
 set ah {}; set bh {}
 for {set i 7} {$i>=0} {incr i -1} {
  append ah [format %08X [expr {($a>>($i*32))&0xffffffff}]]
  append bh [format %08X [expr {($b>>($i*32))&0xffffffff}]]
 }
 return [list $ah $bh]
}
proc reset_test {} {
 global inputs mutations frames pulse_count rails cancelled invalid
 set inputs {};set mutations {};set frames {};set pulse_count 0
 set rails [dict create 2 0.5 3 2.5];set cancelled 0;set invalid 0
}
proc cancel_check {} { global cancelled; if {$cancelled} { error CANCELLED } }
proc hold_cpu {} {}
proc dac {ch voltage} {
 global mutations rails
 assert {$ch in {2 3}} "Supply/bias channel modified"
 assert {$voltage>=0 && $voltage<=3.0} "Rail exceeded hard limit"
 dict set rails $ch $voltage
 lappend mutations [list $ch $voltage]
}
proc emit_scan {r c label clocks pair} {
 global frames
 lappend frames $label
}
proc scan_capture {r c op clocks label {emit 1}} {
 global inputs pulse_count rails invalid
 cancel_check
 if {[string match *_pulse $label]} {
  incr pulse_count
  assert {$op==[string match set_* $label]} "Wrong programming polarity"
  set value 80
 } else {
  assert {[dict get $rails 2]==0.5 && [dict get $rails 3]==2.5} "Read outside read profile"
  set value [expr {[llength $inputs] ? [lindex $inputs 0] : 40}]
  if {[llength $inputs]} { set inputs [lrange $inputs 1 end] }
 }
 set pair [fixture $value $r $c]
 if {$invalid} { set pair {0 0} }
 if {$emit} { emit_scan $r $c $label $clocks $pair }
 return $pair
}
set setv 2.5;set setwl 2.37;set resetv 3.0;set resetwl 2.88;set hold 2400
reset_test
set result [scan_program 0 0 set]
assert {[dict get $result target_met] && $pulse_count==0 && [llength $frames]==11} "Already-SET must confirm ten times without a pulse"
assert {[string match confirm_set_10_met* [lindex $frames end]]} "Missing confirmed target"
reset_test
set inputs [concat {40 40 30 40} [lrepeat 10 40]]
set result [scan_program 0 0 set]
assert {[dict get $result target_met] && $pulse_count==1} "Failed stability read must resume programming"
reset_test
set inputs [concat {40 4} [lrepeat 10 4]]
set result [scan_program 0 0 reset]
assert {[dict get $result target_met] && $pulse_count==1} "RESET must read back and confirm"
reset_test
set result [scan_program 0 0 reset]
assert {![dict get $result target_met] && $pulse_count==96} "Exhaustion must be bounded and unsuccessful"
assert {[string match after_reset_limit__s96_v3000_wl2880 [lindex $frames end]]} "Wrong capped final step"
reset_test
set cancelled 1
assert {[catch {scan_program 0 0 reset}] && !$pulse_count && ![llength $mutations]} "Cancellation must stop before programming"
reset_test
set invalid 1
assert {[catch {scan_program 0 0 set}] && !$pulse_count} "Invalid feedback must not cause a pulse"
assert {[catch {ramp_grid reset 3.001 2.88}]} "VCC over-limit accepted"
assert {[catch {ramp_grid set 2.5 3.001}]} "WL over-limit accepted"
assert {[catch {ramp_grid set 2.2 0.4}]} "Empty sweep accepted"
foreach op {set reset} {
 foreach pair [ramp_grid $op 3 3] {
  assert {[lindex $pair 0]<=3000 && [lindex $pair 1]<=3000} "Grid exceeds hard limit"
 }
}
puts "PASS: target skip, ten stable reads, failed confirmation, SET/RESET polarity, capped exhaustion, read rails, invalid feedback and cancellation"
set f [open [file join [file dirname [file dirname [file normalize [info script]]]] control.tcl]]
set source [read $f]; close $f
set begin [string first "proc dac " $source]
set end [string first "proc power_mask " $source]
eval [string range $source $begin [expr {$end-1}]]
proc command {op payload} { global dac_payload; set dac_payload $payload }
dac 2 3.0
assert {($dac_payload&65535)==39321} "DAC rounding exceeds 3.0 V"
assert {[catch {dac 2 3.0001}]} "Over-limit DAC accepted"
assert {[catch {dac 14 2.0}]} "Protected supply channel accepted"
puts "PASS: actual runner DAC encoder hard cap and protected supply rejection"
