# Pure argument parsing and deterministic column-order construction for
# row_order_read.tcl.  This file deliberately contains no Vivado or hardware
# commands so it can be unit-tested without opening the hardware manager.

namespace eval row_order {
 proc unsigned_decimal {text label} {
  if {![regexp {^[0-9]+$} $text]} { error "$label must be an unsigned decimal integer" }
  set normalized [string trimleft $text 0]
  if {$normalized eq {}} { return 0 }
  if {[string length $normalized]>10 || [scan $normalized %d value]!=1} {
   error "$label is too large"
  }
  return $value
 }

 proc parse_rows {spec} {
  set spec [string trim $spec]
  if {$spec eq {}} { error "rows must not be empty" }

  set rows {}
  array set seen {}
  foreach raw_token [split $spec ,] {
   set token [string trim $raw_token]
   if {[regexp {^([0-9]+)$} $token -> first_text]} {
    set first [unsigned_decimal $first_text row]
    set last $first
   } elseif {[regexp {^([0-9]+)-([0-9]+)$} $token -> first_text last_text]} {
    set first [unsigned_decimal $first_text row]
    set last [unsigned_decimal $last_text row]
    if {$first>$last} {
     error "row range must be ascending: $token"
    }
   } else {
    error "invalid row token: $token"
   }

   if {$first<0 || $last>31} {
    error "row lies outside the physical 0..31 range: $token"
   }
   for {set row $first} {$row<=$last} {incr row} {
    if {[info exists seen($row)]} {
     error "row is selected more than once: $row"
    }
    set seen($row) 1
    lappend rows $row
   }
  }
  if {[llength $rows]==0} { error "rows must select at least one row" }
  return $rows
 }

 proc parse_seed {seed} {
  if {[catch {unsigned_decimal $seed {random seed}} value] ||
      $value<1 || $value>2147483647} {
   error "random seed must be an integer in 1..2147483647"
  }
  return $value
 }

 proc xorshift32 {state} {
  set value [expr {$state & 0xffffffff}]
  set value [expr {($value ^ (($value << 13) & 0xffffffff)) & 0xffffffff}]
  set value [expr {($value ^ ($value >> 17)) & 0xffffffff}]
  set value [expr {($value ^ (($value << 5) & 0xffffffff)) & 0xffffffff}]
  return $value
 }

 proc columns {mode seed} {
  set mode [string tolower [string trim $mode]]
  set result {}
  for {set column 0} {$column<32} {incr column} { lappend result $column }

  switch -- $mode {
   forward { return $result }
   reverse { return [lreverse $result] }
   random {
    set state [parse_seed $seed]
    # Fisher-Yates driven by a fixed xorshift32 PRNG.  This deliberately
    # avoids Tcl's process-global rand() implementation, so a seed produces
    # the same order across Tcl/Vivado sessions and host machines.
    for {set index 31} {$index>0} {incr index -1} {
     set state [xorshift32 $state]
     set other [expr {$state % ($index+1)}]
     set a [lindex $result $index]
     set b [lindex $result $other]
     lset result $index $b
     lset result $other $a
    }
    return $result
   }
   default {
    error "order must be forward, reverse, or random"
   }
  }
 }

 proc validate_order_and_seed {mode seed} {
  set normalized [string tolower [string trim $mode]]
  if {$normalized ni {forward reverse random}} {
   error "order must be forward, reverse, or random"
  }
  if {$normalized eq "random"} {
   return [list $normalized [parse_seed $seed]]
  }
  if {$seed ne {}} {
   error "seed is accepted only when order is random"
  }
  return [list $normalized {}]
 }
}
