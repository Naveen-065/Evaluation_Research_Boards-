# One Vivado session per GUI/API job. No FMC voltage or PMBus writes.
set here [file dirname [file normalize [info script]]]
if {$argc!=10} { error "action row col setV setWL resetV resetWL hold cycles jobID" }
lassign $argv action row col setv setwl resetv resetwl hold cycles jobid
if {$action ni {check hold read set reset cycle column array wb_read wb_set wb_reset wb_cycle wb_column wb_array}} { error "Unknown operation" }
foreach v [list $row $col] { if {![string is integer -strict $v] || $v<0 || $v>31} { error "Cell outside 32x32" } }
foreach v [list $setv $setwl $resetv $resetwl] {
 if {![string is double -strict $v] || $v<0 || $v>3.0} { error "Analog setting outside 0..3.0 V" }
}
if {![string is integer -strict $hold] || $hold<20 || $hold>12000 ||
    ![string is integer -strict $cycles] || $cycles<1 || $cycles>10 ||
    ![regexp {^[a-f0-9]{32}$} $jobid]} { error "Invalid pulse, cycle count or job ID" }
set stopfile [file join $here runs "$jobid.stop"]
source [file join $here i2c_host.tcl]
set sv [get_hw_vios -quiet -of_objects $dev -filter {CELL_NAME == "u_scan_vio"}]
set cp [get_hw_probes -quiet scan_command -of_objects $sv -filter {TYPE == vio_output}]
set rp0 [get_hw_probes -quiet scan_result0 -of_objects $sv -filter {TYPE == vio_input}]
set rp1 [get_hw_probes -quiet scan_result1 -of_objects $sv -filter {TYPE == vio_input}]
if {[llength $sv]!=1 || [llength $cp]!=1 || [llength $rp0]!=1 || [llength $rp1]!=1} { error "Control image/VIO missing" }
proc status_read {} {
 global sv rp0 rp1
 refresh_hw_vio $sv
 return [list [get_property INPUT_VALUE $rp0] [get_property INPUT_VALUE $rp1]]
}
proc cancel_check {} {
 global stopfile restoring
 if {!$restoring && [file exists $stopfile]} { error "CANCELLED" }
}
set restoring 0
proc command {op payload {timeout 6000}} {
 global cp
 set old [expr 0x[get_property OUTPUT_VALUE $cp]]
 set toggle [expr {1-(($old>>63)&1)}]
 set value [expr {($toggle<<63)|(1<<62)|($op<<58)|$payload}]
 set_property OUTPUT_VALUE [format %016llX $value] $cp
 commit_hw_vio $cp
 set deadline [expr {[clock milliseconds]+$timeout}]
 while {1} {
  if {$op!=4} { cancel_check }
  lassign [status_read] h0 h1
  set s [expr 0x$h0]
  if {(($s>>15)&1)==$toggle && ($s&512) && !($s&256)} { break }
  if {[clock milliseconds]>$deadline} { error "Controller timeout op=$op state=[expr {$s&255}] status=$h0/$h1" }
  after 10
 }
 if {$s&1024} { error "Controller fault [expr {($s>>11)&15}]: $h0 / $h1" }
 return [list $h0 $h1]
}
proc hold_cpu {{wb 0}} { command 4 [expr {$wb<<57}] }
proc dac {ch voltage} {
 if {$ch ni {2 3 4 5 9 10 11 12 13} || $voltage<0 || $voltage>3} { error "Protected DAC channel/value" }
 command 2 [expr {(0x10+$ch)<<16 | round($voltage*65536.0/5.0)}]
}
proc power_mask {wb} {
 # The reference disables DAC6, its physical VCC_SET output. This PCB uses
 # DAC2 for VCC_SET, so disable bit2 as well as WL_SET/unused outputs in WB.
 command 2 [expr {$wb ? 0x0901CC : 0x0901D0}]
}
proc scan_profile {} {
 hold_cpu
 dac 2 0.5; dac 3 2.5; dac 4 0; dac 5 2.3
 dac 9 0.9; dac 10 0.9; dac 11 0.6; dac 12 1.6; dac 13 1.0
 power_mask 0
}
proc wb_profile {} {
 hold_cpu 1
 dac 2 0.5; dac 3 0; dac 4 0.5; dac 5 2.5
 # Evaluation-board WB bias profile, encoded for this PCB's 0..5 V ranges.
 dac 9 1.0; dac 10 0.9; dac 11 0.6; dac 12 1.6; dac 13 1.5
 power_mask 1
}
proc write_verify {reg value} {
 si5351_write $reg $value
 if {[si5351_read $reg]!=$value} { error "Si5351 readback mismatch register $reg" }
}
proc clock_profile {mhz} {
 # CPU must already be held. PLLA stays 900 MHz; CLK0/1 match.
 mux_select_fmc
 if {[mux_read]!=4} { error "FMC I2C mux mismatch" }
 set old [si5351_read 3]
 set bytes [expr {$mhz==2 ? {0 1 0 223 0 0 0 0} : {0 1 0 43 0 0 0 0}}]
 write_verify 3 255
 for {set i 0} {$i<8} {incr i} {
  write_verify [expr {42+$i}] [lindex $bytes $i]
  write_verify [expr {50+$i}] [lindex $bytes $i]
 }
 write_verify 165 0; write_verify 166 0
 write_verify 16 79; write_verify 17 79
 si5351_write 177 32
 after 20
 if {[si5351_read 0]&0xA8} { error "Si5351 PLL/crystal fault" }
 write_verify 3 252
 puts "EVENT clock_mhz=$mhz"; flush stdout
}
proc scan_capture {r c op clocks label} {
 cancel_check
 lassign [command 1 [expr {($op<<57)|($clocks<<10)|($c<<5)|$r}]] h0 h1
 puts "CELL_RESULT $r $c $label $clocks $h0 $h1"; flush stdout
 # The scan frame is returned before flagging clipping, so evidence is retained.
 if {([expr 0x$h0]>>37)&1} { error "ADC clipping on a current-sense channel; stopped before another pulse" }
}
proc scan_program {r c op} {
 global setv setwl resetv resetwl hold
 scan_capture $r $c 0 2400 "before_$op"
 hold_cpu
 if {$op eq "set"} { dac 2 $setv; dac 3 $setwl } else { dac 2 $resetv; dac 3 $resetwl }
 scan_capture $r $c [expr {$op eq "set"}] $hold "${op}_pulse"
 hold_cpu; dac 2 0.5; dac 3 2.5
 scan_capture $r $c 0 2400 "after_$op"
}
proc wb_capture {r c op} {
 cancel_check
 # Use the reference project's permanent runtime firmware programming path
 # documented in api_v1/prerequisites/HARDWARE_RUNTIME_BACKUP.md.
 set mode [expr {$op eq "read" ? 1 : ($op eq "set" ? 3 : 0)}]
 # Match evaluation-board memory_controller_packet(), including READ PWM.
 set pwm 0xFF
 set value [expr {($mode<<30)|($r<<25)|($c<<20)|(2<<16)|(0xAA<<8)|$pwm}]
 # gui_wb_mode.c's write branch calls issue_program_setup for SET/RESET.
 # It sends the program packet twice without an intervening chip reset.
 # Repeating the read-transport command instead resets between packets and
 # returned zero banks on this PCB. READ uses issue_read_setup_once.
 set programming [expr {$op ne "read"}]
 set payload [expr {($programming<<57)|(0x80<<32)|$value}]
 cancel_check
 lassign [command 3 $payload 65000] h0 h1
 set b [expr 0x$h1]
 if {(($b>>40)&0x7FFF)!=0x7FFF || !(($b>>55)&1) || (($b>>64)&0xFFFFFFFF)!=$value} {
  error "Wishbone command echo or readback mask mismatch"
 }
 puts "EVENT WB $op r$r/c$c firmware transaction completed"; flush stdout
 for {set i 0} {$i<15} {incr i} {
  lassign [command 5 $i] h0 h1
  puts "WB_WORD $r $c $op $i [format %08X $value] $h0 $h1"; flush stdout
 }
 puts "WB_COMPLETE $r $c $op"; flush stdout
}
proc collect_trace {} {
 # The last scan operation remains in FPGA trace RAM. Three measured samples
 # per VIO read; their time stamps count 10-MSPS snapshots from baseline start.
 for {set i 0} {$i<256} {incr i 3} {
  cancel_check
  lassign [command 6 $i] h0 h1
  set b [expr 0x$h1]
  if {($b>>224)!=0x54524332 || (($b>>201)&255)!=$i} { error "ADC trace signature/index mismatch" }
  set n [expr {($b>>192)&511}]
  if {$n<3 || $n>256} { error "ADC trace length invalid: $n" }
  puts "TRACE_CHUNK $i $h1"; flush stdout
  if {$i+3>=$n} { break }
 }
}
lassign [status_read] h0 h1
if {([expr 0x$h1]>>224)!=0x53435232} { error "Full-control FPGA signature mismatch" }
puts "CONTROL_STATUS $h0 $h1"; flush stdout
if {$action eq "check"} { close_i2c_bridge; exit }
set iswb [string match wb_* $action]
set outcome [catch {
 hold_cpu $iswb
 if {$action eq "hold"} { puts "HELD"; flush stdout } else {
  if {(([expr 0x$h0]>>36)&1)!=1} { error "ADC not healthy; initialize the bench first" }
  if {$iswb} { clock_profile 10; wb_profile } else { clock_profile 2; scan_profile }
  switch $action {
   read { scan_capture $row $col 0 2400 read }
   set - reset { scan_program $row $col $action }
   cycle {
    for {set n 0} {$n<$cycles} {incr n} { scan_program $row $col set; scan_program $row $col reset }
   }
   column { for {set r 0} {$r<32} {incr r} { scan_capture $r $col 0 2400 read } }
   array {
    for {set r 0} {$r<32} {incr r} { for {set c 0} {$c<32} {incr c} { scan_capture $r $c 0 2400 read } }
   }
   wb_read - wb_set - wb_reset { wb_capture $row $col [string range $action 3 end] }
   wb_cycle {
    for {set n 0} {$n<$cycles} {incr n} {
     wb_capture $row $col read; wb_capture $row $col set; wb_capture $row $col read
     wb_capture $row $col reset; wb_capture $row $col read
    }
   }
   wb_column { for {set r 0} {$r<32} {incr r} { wb_capture $r $col read } }
   wb_array { for {set r 0} {$r<32} {incr r} { for {set c 0} {$c<32} {incr c} { wb_capture $r $c read } } }
  }
  if {!$iswb} { collect_trace }
 }
} message options]
# Leave CPU held and restore the scan read rails even after cancellation/fault.
set restoring 1
set cleanup [catch {
 hold_cpu
 if {$action ne "hold"} { clock_profile 2; scan_profile }
} cleanup_message]
if {$cleanup} { puts "RESTORE_FAILED $cleanup_message"; flush stdout }
close_i2c_bridge
if {$outcome} { error $message }
if {$cleanup} { error "Read-profile restoration failed: $cleanup_message" }
puts "JOB_COMPLETE $action"; flush stdout
exit
