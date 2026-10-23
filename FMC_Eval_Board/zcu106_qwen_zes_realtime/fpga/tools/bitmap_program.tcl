# Load, verify, and program a 1024-bit physical ReRAM target bitmap through
# the ZCU106 VIO.  This script assumes the new bitmap-capable bitstream is
# already programmed and the normal 2-MHz Caravel/ADC clocks are healthy.
#
# Usage:
#   vivado -mode batch -source bitmap_program.tcl -tclargs \
#       bitmap.hex output_prefix ?start count hold_clocks reset_retries?
#
# bitmap.hex contains exactly 32 whitespace-separated eight-hex-digit words.
# Word 0 covers row 0, columns 0..31; its LSB is physical cell (0,0).
# A one requests LRS/SET and a zero requests HRS/RESET.
# The op15 implementation visits all requested SET cells first and all RESET
# cells second; result records remain addressed by physical row-major index.

set here [file dirname [file normalize [info script]]]
set fpga_root [file normalize [file join $here ..]]
if {$argc < 2 || $argc > 6} {
 error "bitmap.hex output_prefix ?start count hold_clocks reset_retries?"
}
lassign $argv bitmap_file output_prefix start count hold retries
if {$start eq {}} { set start 0 }
if {$count eq {}} { set count 1024 }
if {$hold eq {}} { set hold 2400 }
if {$retries eq {}} { set retries 2 }
foreach pair [list [list start $start] [list count $count] \
                        [list hold_clocks $hold] [list reset_retries $retries]] {
 lassign $pair label value
 if {![string is integer -strict $value]} { error "$label must be an integer" }
}
if {$start<0 || $start>1023 || $count<1 || $start+$count>1024} {
 error "Requested bitmap range lies outside the physical 32x32 array"
}
if {$hold<20 || $hold>12000 || $retries<0 || $retries>3} {
 error "hold_clocks must be 20..12000 and reset_retries must be 0..3"
}
if {![file exists $bitmap_file]} { error "Bitmap file not found: $bitmap_file" }

set f [open $bitmap_file r]
set words {}
foreach line [split [read $f] "\n"] {
 regsub {#.*$} $line {} line
 foreach token [regexp -all -inline {\S+} $line] {
  if {![regexp {^[0-9a-fA-F]{8}$} $token]} {
   close $f
   error "Each bitmap word must contain exactly eight hexadecimal digits: $token"
  }
  lappend words [expr 0x$token]
 }
}
close $f
if {[llength $words]!=32} {
 error "Bitmap must contain exactly 32 words (1024 bits), found [llength $words]"
}

proc file_sha256 {path} {
 set output [exec certutil.exe -hashfile [file nativename $path] SHA256]
 if {![regexp -nocase {[0-9a-f]{64}} $output digest]} {
  error "Unable to parse SHA-256 for $path"
 }
 return [string tolower $digest]
}

# Reuse the board-proven hardware connection helper from this self-contained
# copy.  No PMBus/VADJ write is performed here.
set hw_target_pattern localhost:3121/xilinx_tcf/Xilinx/*
set hw_part xczu7
set probes_file [file join $fpga_root zcu106_cell_control build zcu106_adc_capture.ltx]
set fmc_mux_address 0x75
set fmc_mux_value 0x01
set csv {}
set program_status [catch {
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
 set last_completed -1
 while {1} {
  lassign [scan_status] h0 h1
  set s [expr 0x$h0]
  set q [expr 0x$h1]
  if {$op==15 && ($q>>224)==0x42505232} {
   set completed [expr {($q>>213)&0x7ff}]
   if {$completed!=$last_completed} {
    set failures [expr {($q>>202)&0x7ff}]
    set index [expr {($q>>173)&0x3ff}]
    set target [expr {($q>>172)&1}]
    puts "BITMAP_PROGRESS completed=$completed failures=$failures row=[expr {$index>>5}] column=[expr {$index&31}] target=$target"
    flush stdout
    set last_completed $completed
   }
  }
  if {(($s>>15)&1)==$toggle && ($s&512) && !($s&256)} { break }
  if {[clock milliseconds]>$deadline} {
   error "Controller timeout op=$op state=[expr {$s&255}] status=$h0/$h1"
  }
  after 10
 }
 if {$s&1024} {
  error "Controller fault [expr {($s>>11)&15}]: $h0 / $h1"
 }
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

set valid_mask 0
for {set index 0} {$index<32} {incr index} {
 set data [lindex $words $index]
 set clear [expr {$index==0}]
 set payload [expr {($clear<<57)|($index<<51)|$data}]
 lassign [scan_command 14 $payload] h0 h1
 set q [expr 0x$h1]
 set valid_mask [expr {$valid_mask|(1<<$index)}]
 if {($q>>224)!=0x424D5032 || (($q>>217)&31)!=$index ||
     (($q>>184)&0xffffffff)!=$valid_mask ||
     (($q>>152)&0xffffffff)!=$data} {
  error "Bitmap load acknowledgment mismatch at word $index: $h0/$h1"
 }
}

# A second pass reads the actual FPGA register image.  This is deliberately
# independent of the write-command echo and is required before programming.
for {set index 0} {$index<32} {incr index} {
 set payload [expr {(1<<56)|($index<<51)}]
 lassign [scan_command 14 $payload] h0 h1
 set q [expr 0x$h1]
 if {($q>>224)!=0x424D5032 || !(($q>>223)&1) || !(($q>>216)&1) ||
     (($q>>184)&0xffffffff)!=0xffffffff ||
     (($q>>152)&0xffffffff)!=[lindex $words $index]} {
  error "Stored bitmap readback mismatch at word $index: $h0/$h1"
 }
}
puts "BITMAP_VERIFIED words=32 bits=1024 sha256=[file_sha256 $bitmap_file]"
flush stdout

restore_read_profile
set payload [expr {(1<<57)|($start<<47)|(($count-1)<<37)|
                   ($hold<<22)|($retries<<20)}]
lassign [scan_command 15 $payload 28800000] summary0 summary1
set summary [expr 0x$summary1]
if {($summary>>224)!=0x42504432} {
 error "Invalid bitmap-program completion signature: $summary0/$summary1"
}
set completed [expr {($summary>>213)&0x7ff}]
set failures [expr {($summary>>202)&0x7ff}]
set set_targets [expr {($summary>>108)&0x7ff}]
set reset_targets [expr {($summary>>97)&0x7ff}]
set set_failures [expr {($summary>>86)&0x7ff}]
set reset_failures [expr {($summary>>75)&0x7ff}]
if {$completed!=$count || $set_targets+$reset_targets!=$count ||
    $set_failures+$reset_failures!=$failures} {
 error "Bitmap summary count mismatch: completed=$completed failures=$failures SET=$set_targets/$set_failures RESET=$reset_targets/$reset_failures"
}

set csv_path "${output_prefix}.csv"
set manifest_path "${output_prefix}.manifest.json"
file mkdir [file dirname [file normalize $csv_path]]
set csv [open $csv_path w]
puts $csv "physical_index,row,column,requested_state,requested_bit,pass,pulses,clipped,current_uA"
set scale [expr {(16384.0/48000.0)/2048.0/392.0*1e6}]
set first_page [expr {$start/14}]
set last_page [expr {($start+$count-1)/14}]
for {set page $first_page} {$page<=$last_page} {incr page} {
 lassign [scan_command 13 $page] p0 p1
 set x [expr 0x$p0]
 set y [expr 0x$p1]
 set page_base [expr {$page*14}]
 if {($y>>224)!=0x41524732 || (($x>>16)&0xffff)!=$page_base} {
  close $csv
  error "Invalid result page $page: $p0/$p1"
 }
 for {set slot 0} {$slot<14} {incr slot} {
  set physical_index [expr {$page_base+$slot}]
  if {$physical_index<$start || $physical_index>=$start+$count} { continue }
  set word [expr {$slot<7 ?
      (($x>>(32+32*$slot))&0xffffffff) :
      (($y>>(32*($slot-7)))&0xffffffff)}]
  set raw [expr {$word&0xffff}]
  if {$raw&0x8000} { set raw [expr {$raw-0x10000}] }
  set pulses [expr {($word>>16)&0x3ff}]
  set pass [expr {($word>>26)&1}]
  set clipped [expr {($word>>27)&1}]
  set target [expr {($word>>28)&1}]
  set bitmap_record [expr {($word>>29)&1}]
  set expected [expr {([lindex $words [expr {$physical_index>>5}]]>>($physical_index&31))&1}]
  if {!$bitmap_record || $target!=$expected} {
   close $csv
   error "Target/result mismatch at physical index $physical_index"
  }
  set current [expr {$raw*$scale}]
  set target_state [expr {$target ? "LRS_SET" : "HRS_RESET"}]
  puts $csv "$physical_index,[expr {$physical_index>>5}],[expr {$physical_index&31}],$target_state,$target,$pass,$pulses,$clipped,[format %.6f $current]"
 }
}
close $csv
set csv {}

set source_sha [file_sha256 $bitmap_file]
set manifest [open $manifest_path w]
puts $manifest "{"
puts $manifest "  \"protocol\": \"ZCU106_BITMAP_V1\","
puts $manifest "  \"source_sha256\": \"$source_sha\","
puts $manifest "  \"fpga_bitmap_register_readback_match\": true,"
puts $manifest "  \"mapping\": \"row-major; word 0 bit 0 = physical row 0 column 0\","
puts $manifest "  \"execution_order\": \"all SET targets, then all RESET targets\","
puts $manifest "  \"start\": $start,"
puts $manifest "  \"count\": $count,"
puts $manifest "  \"hold_clocks\": $hold,"
puts $manifest "  \"reset_retry_limit\": $retries,"
puts $manifest "  \"completed\": $completed,"
puts $manifest "  \"failures\": $failures,"
puts $manifest "  \"set_targets\": $set_targets,"
puts $manifest "  \"set_failures\": $set_failures,"
puts $manifest "  \"reset_targets\": $reset_targets,"
puts $manifest "  \"reset_failures\": $reset_failures"
puts $manifest "}"
close $manifest

restore_read_profile
puts "BITMAP_DONE completed=$completed failures=$failures set_targets=$set_targets set_failures=$set_failures reset_targets=$reset_targets reset_failures=$reset_failures csv=$csv_path manifest=$manifest_path"
flush stdout
} program_message program_options]

# Whether the body passed or failed, first request the core's safe abort/hold,
# then restore all protected DACs to the read profile.  This is intentionally
# best-effort: preserve the original exception while still closing JTAG.
if {$csv ne {}} { catch {close $csv} }
set abort_status 0
set restore_status 0
if {[llength [info commands scan_command]]} {
 set abort_status [catch {scan_command 4 0} abort_message]
 set restore_status [catch {restore_read_profile} restore_message]
}
catch {close_hw_manager}
if {$program_status} {
 if {$abort_status} { puts stderr "WARNING: post-error abort also failed: $abort_message" }
 if {$restore_status} { puts stderr "WARNING: post-error read-profile restoration also failed: $restore_message" }
 return -options $program_options $program_message
}
if {$abort_status} { error "Bitmap job completed but final safe abort failed: $abort_message" }
if {$restore_status} { error "Bitmap job completed but read-profile restoration failed: $restore_message" }
exit
