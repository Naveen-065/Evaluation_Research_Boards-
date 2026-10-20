# Offline command-spy test. Extract only wb_capture; never source hardware setup.
set root [file dirname [file dirname [file normalize [info script]]]]
set f [open [file join $root control.tcl] r]
set source [read $f]
close $f
set begin [string first "proc wb_capture " $source]
set end [string first "proc collect_trace " $source]
if {$begin<0 || $end<=$begin} { error "WB procedure not found" }
eval [string range $source $begin [expr {$end-1}]]
proc cancel_check {} {}
set calls {}
proc command {op payload args} {
 global calls
 lappend calls [list $op $payload]
 set packet [expr {$payload&0xFFFFFFFF}]
 set response [format %08X%016llX $packet [expr {(1<<55)|(0x7FFF<<40)}]]
 return [list 00000000 $response]
}
foreach {op mode} {read 1 set 3 reset 0} {
 set calls {}
 wb_capture 0 31 $op
 if {[llength $calls]!=16} { error "Expected 1 firmware transaction and 15 bank reads" }
 foreach entry [lrange $calls 0 0] {
  lassign $entry code payload
  set programming [expr {$op ne "read"}]
  set wanted [expr {($programming<<57)|(0x80<<32)|($mode<<30)|(31<<20)|(2<<16)|(0xAA<<8)|255}]
  if {$code!=3 || $payload!=$wanted} {
   error "Reference firmware transport/packet mismatch for $op"
  }
 }
 for {set i 0} {$i<15} {incr i} {
  if {[lindex $calls [expr {$i+1}]] ne [list 5 $i]} { error "Result bank order" }
 }
}
puts "PASS WB read/set/reset packets, firmware programming dispatch and all 15 bank indices"
