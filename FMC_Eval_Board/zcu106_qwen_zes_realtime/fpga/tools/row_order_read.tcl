# Read selected complete physical ReRAM rows in a caller-selected column order.
# The only array operation issued is op1 READ.  Each op1 command is a separate
# FPGA transaction; cell_control_engine therefore performs its mandatory fresh
# Caravel RESET_B and READY/fallback sequence for every cell.  No op12/op15
# programming command is reachable from this script.
#
# Usage:
#   vivado -mode batch -source row_order_read.tcl -tclargs \
#       output_prefix rows order ?seed?
#
# rows is a comma-separated set of individual rows and ascending ranges, for
# example "0,3,7-9".  order is forward, reverse, or random.  random requires a
# nonzero seed; the same 32-column permutation is applied to every chosen row.

set here [file dirname [file normalize [info script]]]
set fpga_root [file normalize [file join $here ..]]
source [file join $here row_order_common.tcl]

if {$argc < 3 || $argc > 4} {
 error "output_prefix rows order ?seed?"
}
lassign $argv output_prefix row_spec requested_order seed
lassign [row_order::validate_order_and_seed $requested_order $seed] order seed
set rows [row_order::parse_rows $row_spec]
set columns [row_order::columns $order $seed]

set hw_target_pattern localhost:3121/xilinx_tcf/Xilinx/*
set hw_part xczu7
set probes_file [file join $fpga_root zcu106_cell_control build zcu106_adc_capture.ltx]
set fmc_mux_address 0x75
set fmc_mux_value 0x01
set csv {}
set json {}
set status [catch {
 source [file join $fpga_root kc705_cell_control i2c_host.tcl]

 set scan_vio [get_hw_vios -quiet -of_objects $dev -filter {CELL_NAME == "u_scan_vio"}]
 set command_probe [get_hw_probes -quiet scan_command -of_objects $scan_vio -filter {TYPE == vio_output}]
 set result0_probe [get_hw_probes -quiet scan_result0 -of_objects $scan_vio -filter {TYPE == vio_input}]
 set result1_probe [get_hw_probes -quiet scan_result1 -of_objects $scan_vio -filter {TYPE == vio_input}]
 if {[llength $scan_vio]!=1 || [llength $command_probe]!=1 ||
     [llength $result0_probe]!=1 || [llength $result1_probe]!=1} {
  error "Bitmap-capable scan VIO was not found"
 }

 proc scan_status {} {
  global scan_vio result0_probe result1_probe
  refresh_hw_vio $scan_vio
  return [list [get_property INPUT_VALUE $result0_probe] \
                    [get_property INPUT_VALUE $result1_probe]]
 }

 proc scan_command {op payload {timeout_ms 6000}} {
  global command_probe
  # Fail closed: op1 is the only array-touching operation.  Op2 adjusts only
  # protected DAC rails for the read profile, op4 is abort/reset hold, and
  # op14 is allowed only as a read-only BMP2 identity transaction.
  if {$op ni {1 2 4 14}} {
   error "Unsafe opcode rejected by read-only row probe: $op"
  }
  if {$op==1 && ($payload>>25)!=0} {
   error "READ payload contains forbidden SET/MAC/reserved bits"
  }
  if {$op==2 && ($payload>>24)!=0} {
   error "Protected DAC payload exceeds the 24-bit frame"
  }
  if {$op==4 && $payload!=0} {
   error "Safe abort must use a zero payload"
  }
  if {$op==14 && $payload!=(1<<56)} {
   error "Only the non-mutating BMP2 identity transaction is permitted"
  }
  set old [expr 0x[get_property OUTPUT_VALUE $command_probe]]
  set toggle [expr {1-(($old>>63)&1)}]
  set value [expr {($toggle<<63)|(1<<62)|($op<<58)|$payload}]
  set_property OUTPUT_VALUE [format %016llX $value] $command_probe
  commit_hw_vio $command_probe
  set deadline [expr {[clock milliseconds]+$timeout_ms}]
  while {1} {
   lassign [scan_status] h0 h1
   set s [expr 0x$h0]
   if {(($s>>15)&1)==$toggle && ($s&512) && !($s&256)} { break }
   if {[clock milliseconds]>$deadline} {
    error "Controller timeout op=$op state=[expr {$s&255}] status=$h0/$h1"
   }
   after 10
  }
  if {$s&1024} { error "Controller fault [expr {($s>>11)&15}]: $h0/$h1" }
  return [list $h0 $h1]
 }

 proc protected_dac {channel voltage} {
  if {$channel ni {2 3 4 5 9 10 11 12 13} || $voltage<0 || $voltage>3.0} {
   error "Protected DAC channel/value"
  }
  set code [expr {min(39321,floor($voltage*65536.0/5.0))}]
  scan_command 2 [expr {(0x10+$channel)<<16 | int($code)}]
 }

 proc restore_read_profile {} {
  scan_command 4 0
  protected_dac 2 0.5
  protected_dac 3 2.5
  protected_dac 4 0.0
  protected_dac 5 2.3
  protected_dac 9 0.9
  protected_dac 10 0.9
  protected_dac 11 0.6
  protected_dac 12 1.6
  protected_dac 13 1.0
  scan_command 2 0x0901D0
 }

 proc decoded_current_uA {h0 h1 row column} {
  set a [expr 0x$h0]
  set b [expr 0x$h1]
  set packet [expr {($row<<10)|($column<<5)|$row}]
  if {($b>>224)!=0x53435232 || !($a&512) || ($a&1280) ||
      (($a>>16)&65535)!=$packet || (($a>>37)&1)} {
   error "Invalid ADC feedback at ($row,$column): $h0/$h1"
  }
  set baseline_count [expr {($a>>64)&65535}]
  set active_count [expr {($a>>80)&65535}]
  if {$baseline_count<500 || $baseline_count>800 ||
      $active_count<11960 || $active_count>12040} {
   error "Invalid ADC sample count at ($row,$column)"
  }
  set baseline [expr {double(($a>>160)&0xffffffff)/$baseline_count}]
  set active [expr {double(($b>>64)&0xffffffff)/$active_count}]
  if {$baseline<0 || $baseline>4095 || $active<0 || $active>4095} {
   error "ADC sum outside range at ($row,$column)"
  }
  return [expr {($active-$baseline)/2048.0/(7.0*56.0)*1e6}]
 }

 set csv_path "${output_prefix}.csv"
 set json_path "${output_prefix}.json"
 set csv_partial "${csv_path}.partial"
 set json_partial "${json_path}.partial"
 file mkdir [file dirname [file normalize $csv_path]]

 # Establish the same bounded read bias/profile used by bitmap_read.tcl, then
 # prove the connected image exposes the non-mutating BMP2 identity command.
 restore_read_profile
 lassign [scan_command 14 [expr {1<<56}]] identity0 identity1
 set identity [expr 0x$identity1]
 if {($identity>>224)!=0x424D5032 || !(($identity>>223)&1)} {
  error "Connected image is not the bitmap-capable BMP2 protocol: $identity0/$identity1"
 }

 # Final names are never opened directly.  A failed read or cleanup leaves
 # only explicit .partial evidence, never a valid-looking truncated result.
 set csv [open $csv_partial w]
 set json [open $json_partial w]
 puts $csv "acquisition_index,row,column,physical_index,column_order,seed,current_uA,conductance_uS,observed_bit,observed_state,threshold_uA"
 puts $json "{"
 puts $json "  \"protocol\": \"ZCU106_ROW_ORDER_READ_V1\","
 puts $json "  \"rows\": \[[join $rows {, }]\],"
 puts $json "  \"column_order_mode\": \"$order\","
 if {$seed eq {}} {
  puts $json "  \"seed\": null,"
 } else {
  puts $json "  \"seed\": $seed,"
 }
 puts $json "  \"column_order\": \[[join $columns {, }]\],"
 puts $json "  \"threshold_uA\": 34.2563054,"
 puts $json {  "cells": [}

 set acquisition_index 0
 set lrs_count 0
 set total [expr {[llength $rows]*32}]
 foreach row $rows {
  foreach column $columns {
   set physical_index [expr {32*$row+$column}]
   # op1 starts exactly one scan packet.  The RTL performs a fresh RESET_B and
   # READY/fallback handshake before shifting this packet; there is no packet
   # streaming or persistent-scan shortcut here.
   lassign [scan_command 1 [expr {(2400<<10)|($column<<5)|$row}]] h0 h1
   set current [decoded_current_uA $h0 $h1 $row $column]
   set conductance [expr {$current/0.5}]
   set observed [expr {$current>=34.2563054}]
   if {$observed} { incr lrs_count }
   set state [expr {$observed ? "LRS" : "HRS"}]
   set csv_seed [expr {$seed eq {} ? "" : $seed}]
   puts $csv "$acquisition_index,$row,$column,$physical_index,$order,$csv_seed,[format %.9f $current],[format %.9f $conductance],$observed,$state,34.2563054"
   puts -nonewline $json "    {\"acquisition_index\": $acquisition_index, \"row\": $row, \"column\": $column, \"physical_index\": $physical_index, \"current_uA\": [format %.9f $current], \"conductance_uS\": [format %.9f $conductance], \"observed_bit\": $observed, \"observed_state\": \"$state\"}"
   if {$acquisition_index!=$total-1} { puts $json "," } else { puts $json {} }
   incr acquisition_index
  }
  puts "ROW_ORDER_PROGRESS completed=$acquisition_index total=$total row=$row lrs=$lrs_count hrs=[expr {$acquisition_index-$lrs_count}]"
  flush stdout
 }
 puts $json "  ],"
 puts $json "  \"lrs_count\": $lrs_count,"
 puts $json "  \"hrs_count\": [expr {$total-$lrs_count}]"
 puts $json "}"
 close $csv
 set csv {}
 close $json
 set json {}
} message options]

if {$csv ne {}} { catch {close $csv} }
if {$json ne {}} { catch {close $json} }

# Always request an explicit safe abort/Caravel reset hold, then restore the
# bounded read profile.  Preserve the original diagnostic error if one exists.
set abort_status 0
set restore_status 0
if {[llength [info commands scan_command]]} {
 set abort_status [catch {scan_command 4 0} abort_message]
 set restore_status [catch {restore_read_profile} restore_message]
}
catch {close_hw_manager}
if {$status} {
 if {$abort_status} { puts stderr "WARNING: post-error abort also failed: $abort_message" }
 if {$restore_status} { puts stderr "WARNING: post-error read-profile restoration also failed: $restore_message" }
 return -options $options $message
}
if {$abort_status} { error "Read completed but final safe abort failed: $abort_message" }
if {$restore_status} { error "Read completed but read-profile restoration failed: $restore_message" }

# Promotion occurs only after every requested cell completed and both cleanup
# operations succeeded.  Existing completed files at this prefix are replaced
# only by another complete, safely restored acquisition.
file rename -force $csv_partial $csv_path
file rename -force $json_partial $json_path
if {$seed eq {}} { set seed_label none } else { set seed_label $seed }
puts "ROW_ORDER_DONE rows=[llength $rows] cells=$total order=$order seed=$seed_label lrs=$lrs_count hrs=[expr {$total-$lrs_count}] csv=$csv_path json=$json_path"
flush stdout
exit
