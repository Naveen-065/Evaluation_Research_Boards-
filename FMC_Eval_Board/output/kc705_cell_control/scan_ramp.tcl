# Scan ramp adapted from Evaluation_Research_Boards-/api_v1/cell_api.py
# _ramp_until / confirm_reads. No hardware access occurs when sourcing this file.
# Current uses this PCB's ADC3 / R10: active-minus-idle, 56 ohm, nominal gain 7.
# Read-stage labels carry actual step rails through the existing API protocol.
proc ramp_grid {op maxv maxwl} {
 if {$op ni {set reset}} { error "Unknown ramp operation" }
 foreach v [list $maxv $maxwl] {
  if {![string is double -strict $v] || $v<=0 || $v>3.0} { error "Ramp limit must be >0 and <=3.0 V" }
 }
 if {$op eq "set"} {
  set vs {2300 2400 2500}
  set ws {440 500 560 630 690 750 810 870 940 1000 1060 1120 1190 1250 1310 1370 1430 1500 1560 1620 1680 1750 1810 1870 1930 1990 2060 2120 2180 2240 2310 2370}
 } else {
  # Reference 2.3/2.7/3.1/3.5 V, clipped and deduplicated at the PCB limit.
  set vs {2300 2700 3000}
  set ws {940 1010 1070 1130 1190 1260 1320 1380 1440 1510 1570 1630 1690 1760 1820 1880 1940 2010 2070 2130 2190 2260 2320 2380 2440 2500 2570 2630 2690 2750 2820 2880}
 }
 set grid {}
 foreach v $vs {
  if {$v>round($maxv*1000)} continue
  foreach w $ws {
   if {$w<=round($maxwl*1000)} { lappend grid [list $v $w] }
  }
 }
 if {![llength $grid]} { error "Ramp limits exclude every reference step" }
 return $grid
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
 foreach rails $grid {
  cancel_check
  incr step
  lassign $rails mv mw
  set suffix "__s${step}_v${mv}_wl${mw}"
  set last_step [expr {$step==[llength $grid]}]
  lassign [ramp_read $r $c "before_$op$suffix"] pair current
  emit_scan $r $c "before_$op$suffix" 2400 $pair
  if {[ramp_passes $op $current]} {
   set result [ramp_confirm $r $c $op $suffix 0]
   if {[dict get $result target_met]} {
    return [ramp_finish $op $pulses 1 [dict get $result last_current]]
   }
  }
  cancel_check
  puts "EVENT RAMP [string toupper $op] step $step/[llength $grid]: VCC=[expr {$mv/1000.0}] V, WL=[expr {$mw/1000.0}] V"; flush stdout
  hold_cpu
  dac 2 [expr {$mv/1000.0}]; dac 3 [expr {$mw/1000.0}]
  scan_capture $r $c [expr {$op eq "set"}] $hold "${op}_pulse"
  incr pulses
  hold_cpu; dac 2 0.5; dac 3 2.5
  lassign [ramp_read $r $c "after_$op$suffix"] pair current
  set pass [ramp_passes $op $current]
  set outcome [expr {!$pass && $last_step ? "_limit" : ""}]
  emit_scan $r $c "after_${op}${outcome}$suffix" 2400 $pair
  if {$pass} {
   set result [ramp_confirm $r $c $op $suffix $last_step]
   set current [dict get $result last_current]
   if {[dict get $result target_met]} { return [ramp_finish $op $pulses 1 $current] }
  }
 }
 return [ramp_finish $op $pulses 0 $current]
}
