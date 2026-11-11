# Read a physical ReRAM range directly through the bitmap-capable ZCU106 VIO.
# This deliberately has no SenseEval deployment-hash dependency.
#
# Usage:
#   vivado -mode batch -source bitmap_read.tcl -tclargs \
#       output_prefix ?start count?

set here [file dirname [file normalize [info script]]]
set fpga_root [file normalize [file join $here ..]]
if {$argc < 1 || $argc > 3} { error "output_prefix ?start count?" }
lassign $argv output_prefix start count
if {$start eq {}} { set start 0 }
if {$count eq {}} { set count 1024 }
if {![string is integer -strict $start] || ![string is integer -strict $count] ||
    $start<0 || $start>1023 || $count<1 || $start+$count>1024} {
 error "Read range lies outside the physical 32x32 array"
}

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
file mkdir [file dirname [file normalize $csv_path]]
 restore_read_profile
 lassign [scan_command 14 [expr {1<<56}]] identity0 identity1
 set identity [expr 0x$identity1]
 if {($identity>>224)!=0x424D5032 || !(($identity>>223)&1)} {
  error "Connected image is not the bitmap-capable BMP2 protocol: $identity0/$identity1"
 }
 set csv [open $csv_path w]
 set json [open $json_path w]
 puts $csv "physical_index,row,column,current_uA,conductance_uS,observed_bit,observed_state,threshold_uA"
 puts $json "{"
 puts $json "  \"protocol\": \"ZCU106_BITMAP_READ_V1\","
 puts $json "  \"start\": $start,"
 puts $json "  \"count\": $count,"
 puts $json "  \"threshold_uA\": 34.2563054,"
 puts $json {  "cells": [}
 set lrs_count 0
 for {set offset 0} {$offset<$count} {incr offset} {
  set physical_index [expr {$start+$offset}]
  set row [expr {$physical_index>>5}]
  set column [expr {$physical_index&31}]
  lassign [scan_command 1 [expr {(2400<<10)|($column<<5)|$row}]] h0 h1
  set current [decoded_current_uA $h0 $h1 $row $column]
  set conductance [expr {$current/0.5}]
  set observed [expr {$current>=34.2563054}]
  if {$observed} { incr lrs_count }
  set state [expr {$observed ? "LRS" : "HRS"}]
  puts $csv "$physical_index,$row,$column,[format %.9f $current],[format %.9f $conductance],$observed,$state,34.2563054"
  puts -nonewline $json "    {\"physical_index\": $physical_index, \"row\": $row, \"column\": $column, \"current_uA\": [format %.9f $current], \"conductance_uS\": [format %.9f $conductance], \"observed_bit\": $observed, \"observed_state\": \"$state\"}"
  if {$offset!=$count-1} { puts $json "," } else { puts $json {} }
  if {($offset%16)==15 || $offset==$count-1} {
   puts "READ_PROGRESS completed=[expr {$offset+1}] count=$count row=$row column=$column lrs=$lrs_count hrs=[expr {$offset+1-$lrs_count}]"
   flush stdout
  }
 }
 puts $json "  ],"
 puts $json "  \"lrs_count\": $lrs_count,"
 puts $json "  \"hrs_count\": [expr {$count-$lrs_count}]"
 puts $json "}"
 close $csv
 set csv {}
 close $json
 set json {}
 puts "READ_DONE count=$count lrs=$lrs_count hrs=[expr {$count-$lrs_count}] csv=$csv_path json=$json_path"
 flush stdout
} message options]

if {$csv ne {}} { catch {close $csv} }
if {$json ne {}} { catch {close $json} }
set restore_status 0
if {[llength [info commands scan_command]]} {
 set restore_status [catch {restore_read_profile} restore_message]
}
catch {close_hw_manager}
if {$status} {
 if {$restore_status} {
  puts stderr "WARNING: post-error read-profile restoration also failed: $restore_message"
 }
 return -options $options $message
}
if {$restore_status} { error "Read completed but safe-profile restoration failed: $restore_message" }
exit
