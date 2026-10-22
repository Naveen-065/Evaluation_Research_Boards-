# Scan ramp adapted from Evaluation_Research_Boards-/api_v1/cell_api.py
# _ramp_until / confirm_reads. No hardware access occurs when sourcing this file.
# Current uses this PCB's ADC3 / R10: active-minus-idle, 56 ohm, nominal gain 7.
# Read-stage labels carry actual step rails through the existing API protocol.
# Three measured min/mean/max points.  The 96-step reference grid remains in
# the FPGA as command 9; normal programming uses command 11 so a failed cell
# receives at most three pulses before the caller moves on.
proc ramp_grid {op maxv maxwl} {
 if {$op ni {set reset}} { error "Unknown ramp operation" }
 if {$op eq "set"} {
  foreach v [list $maxv $maxwl] {
   if {![string is double -strict $v] || $v<=0 || $v>3.0} { error "SET ramp limit must be >0 and <=3.0 V" }
  }
  set grid {{2300 440} {2300 1090} {2300 1750}}
 } else {
  # Reference RESET ramp, routed on this PCB through dedicated DAC5
  # VCC_RESET/VDDA2 and DAC4 VCC_WL_RESET. The 3.1/3.5-V reference levels are
  # deliberately omitted so neither programmed rail exceeds the 3.0-V cap.
  if {![string is double -strict $maxv] || $maxv<2.3 || $maxv>3.0 ||
      ![string is double -strict $maxwl] || $maxwl<0.94 || $maxwl>3.0} {
   error "RESET ramp limits require VCC 2.3..3.0 V and WL 0.94..3.0 V"
  }
  set grid {{2300 940} {2800 1830} {3000 2880}}
 }
 set bounded {}
 foreach pair $grid {
  lassign $pair v w
  if {$v<=round($maxv*1000) && $w<=round($maxwl*1000)} { lappend bounded $pair }
 }
 if {![llength $bounded]} { error "Ramp limits exclude every fast-ramp step" }
 return $bounded
}
proc ramp_current {pair r c} {
 lassign $pair h0 h1
 set a [expr 0x$h0]; set b [expr 0x$h1]
 set packet [expr {($r<<10)|($c<<5)|$r}]
 if {($b>>224)!=0x53435232 || !($a&512) || ($a&1280) ||
     (($a>>16)&65535)!=$packet || (($a>>37)&1)} { error "Invalid ramp ADC feedback" }
 set nb [expr {($a>>64)&65535}]; set na [expr {($a>>80)&65535}]
 if {$nb<500 || $nb>800 || $na<11960 || $na>12040} { error "Invalid ramp ADC sample count" }
 set base [expr {double(($a>>160)&0xffffffff)/$nb}]
 set active [expr {double(($b>>64)&0xffffffff)/$na}]
 if {$base<0 || $base>4095 || $active<0 || $active>4095} { error "Ramp ADC sum outside range" }
 return [expr {($active-$base)/2048.0/(7*56)*1e6}]
}
proc ramp_passes {op current} {
 return [expr {$op eq "set" ? $current>=35.0 : $current<=5.0}]
}
proc ramp_read {r c label} {
 set pair [scan_capture $r $c 0 2400 $label 0]
 set current [ramp_current $pair $r $c]
 return [list $pair $current]
}
proc program_step {r c op mv mw label} {
 global hold
 set setop [expr {$op eq "set"}]
 set vcc_code [expr {min(39321,round($mv/1000.0*65536.0/5.0))}]
 set wl_code [expr {min(39321,round($mw/1000.0*65536.0/5.0))}]
 set payload [expr {($setop<<57)|($vcc_code<<41)|($wl_code<<25)|
                         ($hold<<10)|($c<<5)|$r}]
 lassign [command 8 $payload] h0 h1
 set pair [list $h0 $h1]
 if {([expr 0x$h0]>>44)&1} {
  puts "EVENT PROGRAM_STEP pulse clipped at r$r/c$c; post-pulse READ is clean"; flush stdout
 }
 return [list $pair [ramp_current $pair $r $c]]
}
proc program_ramp {r c op maxv maxwl} {
 global hold
 set setop [expr {$op eq "set"}]
 set vcc_code [expr {min(39321,round($maxv*65536.0/5.0))}]
 set wl_code [expr {min(39321,round($maxwl*65536.0/5.0))}]
 set payload [expr {($setop<<57)|($vcc_code<<41)|($wl_code<<25)|
                         ($hold<<10)|($c<<5)|$r}]
 # The fabric executes all bounded ramp steps and ten-read confirmation.
 # Thirty seconds is a fault timeout, not an intentional delay.
 # Command 11 is the measured three-point scheduler.  Command 9 intentionally
 # remains the full 96-point fallback for diagnostic use.
 lassign [command 11 $payload 30000] h0 h1
 set a [expr 0x$h0]; set b [expr 0x$h1]
 if {($b>>224)!=0x53435232} { error "Invalid FPGA ramp result" }
 set pulses [expr {($b>>216)&255}]
 set met [expr {($b>>215)&1}]
 set pulse_clipped [expr {($b>>214)&1}]
 set last_index [expr {($b>>207)&127}]
 set confirmations [expr {($b>>203)&15}]
 if {$pulses<1 || $pulses>3 || $last_index>2 || ($met && $confirmations!=10)} {
  error "Invalid FPGA ramp summary: pulses=$pulses met=$met last_index=$last_index confirmations=$confirmations"
 }
 set currents {}
 for {set page 0} {$page*28<$pulses} {incr page} {
  lassign [command 10 $page] p0 p1
  set x [expr 0x$p0]; set y [expr 0x$p1]
  if {($y>>224)!=0x524D5032 || (($x>>16)&255)!=$pulses || (($x>>26)&3)!=$page} {
   error "Invalid FPGA ramp trace page $page"
  }
  for {set k 0} {$k<28 && [llength $currents]<$pulses} {incr k} {
   set raw [expr {$k<14 ? (($x>>(32+16*$k))&65535) : (($y>>(16*($k-14)))&65535)}]
   if {$raw&32768} { set raw [expr {$raw-65536}] }
   # FPGA trace words hold ramp_delta/2^14; ramp_delta is 48000 times
   # the average ADC-code difference.  The ramp pass/fail comparison in
   # fabric still uses the full-precision ramp_delta value.
   lappend currents [expr {$raw*(16384.0/48000.0)/2048.0/392.0*1e6}]
  }
 }
 return [dict create pair [list $h0 $h1] pulses $pulses target_met $met \
         pulse_clipped $pulse_clipped last_index $last_index currents $currents]
}
proc ramp_confirm {r c op suffix last_step} {
 set readings {}
 for {set k 1} {$k<=10} {incr k} {
  lassign [ramp_read $r $c "confirm_${op}_${k}$suffix"] pair current
  set pass [ramp_passes $op $current]
  set outcome [expr {!$pass && $last_step ? "_limit" : ($pass && $k==10 ? "_met" : "")}]
  emit_scan $r $c "confirm_${op}_${k}${outcome}$suffix" 2400 $pair
  lappend readings $current
  if {!$pass} { return [dict create target_met 0 readings $readings last_current $current] }
 }
 return [dict create target_met 1 readings $readings last_current $current]
}
proc ramp_finish {op pulses met current} {
 set verdict [expr {$met ? "target confirmed by 10 reads" : "limit reached; target NOT met"}]
 puts "EVENT RAMP [string toupper $op]: $verdict; pulses=$pulses; last=[format %.3f $current] uA nominal"
 puts "RAMP_COMPLETE $op $pulses $met [format %.6f $current]"; flush stdout
 return [dict create operation $op pulses $pulses target_met $met last_current $current]
}
proc scan_program {r c op} {
 global setv setwl resetv resetwl hold
 set maxv [expr {$op eq "set" ? $setv : $resetv}]
 set maxwl [expr {$op eq "set" ? $setwl : $resetwl}]
 set grid [ramp_grid $op $maxv $maxwl]
 set step 0; set pulses 0
 # Establish the state once before the first pulse.  Every compound
 # PROGRAM_STEP below already restores the read rails and returns a clean
 # post-pulse capture, so repeating the same standalone read before the next
 # ramp point adds a VIO round trip without adding a new safety decision.
 lassign [lindex $grid 0] first_mv first_mw
 set first_suffix "__s1_v${first_mv}_wl${first_mw}"
 lassign [ramp_read $r $c "before_$op$first_suffix"] pair current
 emit_scan $r $c "before_$op$first_suffix" 2400 $pair
 if {[ramp_passes $op $current]} {
  set result [ramp_confirm $r $c $op $first_suffix 0]
  if {[dict get $result target_met]} {
   return [ramp_finish $op $pulses 1 [dict get $result last_current]]
  }
 }
 cancel_check
 puts "EVENT PROGRAM_RAMP [string toupper $op] r$r/c$c: FPGA owns up to [llength $grid] serial single-cell steps"; flush stdout
 set result [program_ramp $r $c $op $maxv $maxwl]
 set pulses [dict get $result pulses]
 set met [dict get $result target_met]
 set currents [dict get $result currents]
 for {set k 0} {$k<$pulses} {incr k} {
  lassign [lindex $grid $k] mv mw
  puts "RAMP_POINT $r $c $op [expr {$k+1}] $mv $mw [format %.6f [lindex $currents $k]]"
 }
 lassign [lindex $grid [expr {$pulses-1}]] mv mw
 set suffix "__s${pulses}_v${mv}_wl${mw}"
 set outcome [expr {$met ? "_met" : "_limit"}]
 set pair [dict get $result pair]
 emit_scan $r $c "after_${op}${outcome}$suffix" 2400 $pair
 set current [ramp_current $pair $r $c]
 if {[dict get $result pulse_clipped]} {
  puts "EVENT PROGRAM_RAMP pulse clipping observed; restored READ result is clean"
 }
 return [ramp_finish $op $pulses $met $current]
}
