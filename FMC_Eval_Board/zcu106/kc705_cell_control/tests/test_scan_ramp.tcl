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
 global inputs mutations frames pulse_count rails rail_mask cancelled invalid
 set inputs {};set mutations {};set frames {};set pulse_count 0
 set rails [dict create 2 0.5 3 2.5 4 0 5 2.3];set rail_mask scan
 set cancelled 0;set invalid 0
}
proc cancel_check {} { global cancelled; if {$cancelled} { error CANCELLED } }
proc hold_cpu {} {}
proc dac {ch voltage} {
 global mutations rails
 assert {$ch in {2 3 4 5}} "Unexpected DAC channel modified"
 assert {$voltage>=0 && $voltage<=3.0} "Rail exceeded hard limit"
 dict set rails $ch $voltage
 lappend mutations [list $ch $voltage]
}
proc power_mask {reset} {
 global rail_mask mutations
 set rail_mask [expr {$reset ? "reset" : "scan"}]
 lappend mutations [list mask $rail_mask]
}
proc scan_profile {} {
 hold_cpu
 dac 2 0.5; dac 3 2.5; dac 4 0; dac 5 2.3
 power_mask 0
}
proc emit_scan {r c label clocks pair} {
 global frames
 lappend frames $label
}
proc command {op payload args} {
 global inputs pulse_count
 assert {$op==8} "Programming did not use compound FPGA PROGRAM_STEP"
 set setop [expr {($payload>>57)&1}]
 set vcc_code [expr {($payload>>41)&65535}]
 set wl_code [expr {($payload>>25)&65535}]
 set clocks [expr {($payload>>10)&32767}]
 set c [expr {($payload>>5)&31}]; set r [expr {$payload&31}]
 assert {$vcc_code<=39321 && $wl_code<=39321 && $clocks==2400} "Unsafe PROGRAM_STEP payload"
 incr pulse_count
 set value [expr {[llength $inputs] ? [lindex $inputs 0] : 40}]
 if {[llength $inputs]} { set inputs [lrange $inputs 1 end] }
 return [fixture $value $r $c]
}
# Offline behavioral stand-in for the fabric ramp scheduler.  RTL simulation
# separately verifies operation 11 command sequencing and trace paging.
proc program_ramp {r c op maxv maxwl} {
 global inputs pulse_count
 set grid [ramp_grid $op $maxv $maxwl]
 set currents {}; set met 0; set final 40; set pulses 0
 foreach rails $grid {
  incr pulse_count; incr pulses
  set value [expr {[llength $inputs] ? [lindex $inputs 0] : 40}]
  if {[llength $inputs]} { set inputs [lrange $inputs 1 end] }
  set final $value; lappend currents $value
  if {[ramp_passes $op $value]} {
   set stable 1
   for {set k 0} {$k<10} {incr k} {
    set value [expr {[llength $inputs] ? [lindex $inputs 0] : 40}]
    if {[llength $inputs]} { set inputs [lrange $inputs 1 end] }
    set final $value
    if {![ramp_passes $op $value]} { set stable 0; break }
   }
   if {$stable} { set met 1; break }
  }
 }
 return [dict create pair [fixture $final $r $c] pulses $pulses target_met $met \
   pulse_clipped 0 last_index [expr {$pulses-1}] currents $currents]
}
proc scan_capture {r c op clocks label {emit 1} {allow_program_clip 0} {mac_input {}}} {
 global inputs pulse_count rails rail_mask invalid
 cancel_check
 if {[string match *_pulse $label]} {
  incr pulse_count
  assert {$allow_program_clip} "Programming-pulse clipping policy was not enabled"
  assert {$op==[string match set_* $label]} "Wrong programming polarity"
  if {$op} {
   assert {$rail_mask eq "scan" && [dict get $rails 2]>0 && [dict get $rails 3]>0} "SET did not use DAC2/DAC3"
  } else {
   assert {$rail_mask eq "scan" && [dict get $rails 2]>0 && [dict get $rails 3]>0} "RESET did not use the proven DAC2/DAC3 path"
  }
  set value 80
 } else {
  assert {!$allow_program_clip} "Readback clipping policy was relaxed"
  assert {$rail_mask eq "scan" && [dict get $rails 2]==0.5 && [dict get $rails 3]==2.5 && [dict get $rails 4]==0 && [dict get $rails 5]==2.3} "Read outside read profile"
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
assert {![dict get $result target_met] && $pulse_count==96} "Reliable RESET ramp exhaustion must be bounded"
assert {[llength [lsearch -all -inline $frames before_reset*]]==1} "RESET must perform only one host-side pre-read before the FPGA ramp"
assert {[string match after_reset_limit__s96_v3000_wl2880 [lindex $frames end]]} "Wrong reliable RESET ramp endpoint"
reset_test
set cancelled 1
assert {[catch {scan_program 0 0 reset}] && !$pulse_count && ![llength $mutations]} "Cancellation must stop before programming"
reset_test
set invalid 1
assert {[catch {scan_program 0 0 set}] && !$pulse_count} "Invalid feedback must not cause a pulse"
assert {[catch {ramp_grid reset 3.001 2.88}]} "RESET VCC over-limit accepted"
assert {[catch {ramp_grid reset 1.7 0.93}]} "RESET WL below the ramp floor accepted"
assert {[catch {ramp_grid set 2.5 3.001}]} "WL over-limit accepted"
assert {[catch {ramp_grid set 2.2 0.4}]} "Empty sweep accepted"
foreach op {set reset} {
 set limits {3 3}
 foreach pair [ramp_grid $op {*}$limits] {
  assert {[lindex $pair 0]<=3000 && [lindex $pair 1]<=3000} "Grid exceeds hard limit"
 }
}
puts "PASS: target skip, ten stable reads, one initial pre-read, FPGA SET fast ramp, full RESET ramp, bounded exhaustion, invalid feedback and cancellation"
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
set begin [string first "proc scan_capture " $source]
set end [string first "source \[file join \$here scan_ramp.tcl\]" $source]
eval [string range $source $begin [expr {$end-1}]]
proc clipped_fixture {current r c} {
 lassign [fixture $current $r $c] ah bh
 set a [expr {[expr 0x$ah] | (1<<37)}]
 set clipped {}
 for {set i 7} {$i>=0} {incr i -1} {
  append clipped [format %08X [expr {($a>>($i*32))&0xffffffff}]]
 }
 return [list $clipped $bh]
}
proc command {op payload args} { global command_pair; return $command_pair }
set command_pair [clipped_fixture 80 0 0]
set frames {}
assert {![catch {scan_capture 0 0 0 2400 reset_pulse 1 1}]} "Clipped programming pulse must continue to readback"
assert {[llength $frames]==1} "Clipped programming-pulse evidence was not retained"
set frames {}
assert {[catch {scan_capture 0 0 0 2400 read} message] && [string match "ADC clipping*" $message]} "Clipped readback must stop programming"
assert {[llength $frames]==1} "Clipped readback evidence was not retained"
puts "PASS: clipped programming pulses continue, while clipped readback remains fatal"
