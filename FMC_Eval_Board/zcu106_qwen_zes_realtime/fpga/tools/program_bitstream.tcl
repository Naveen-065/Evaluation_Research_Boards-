# Program only a hash-pinned bitmap-capable ZCU106 image, explicitly disable
# the ADC/DAC interlocks, and hold Caravel in reset with the digital-only op4
# safety command. No array pulse, VADJ write, PMBus write, or DAC rail
# initialization is performed.
#
# Usage:
#   vivado -mode batch -source program_bitstream.tcl -tclargs \
#       image.bit image.ltx expected_bit_sha256 expected_ltx_sha256 \
#       deployment_receipt.json

if {$argc!=5} {
 error "image.bit image.ltx expected_bit_sha256 expected_ltx_sha256 deployment_receipt.json"
}
lassign $argv bitstream probes expected_sha expected_probes_sha receipt
foreach path [list $bitstream $probes] {
 if {![file exists $path]} { error "Required deployment file not found: $path" }
}
if {![regexp -nocase {^[0-9a-f]{64}$} $expected_sha] ||
    ![regexp -nocase {^[0-9a-f]{64}$} $expected_probes_sha]} {
 error "Expected bitstream and probes SHA-256 values must contain exactly 64 hex digits"
}

proc file_sha256 {path} {
 set output [exec certutil.exe -hashfile [file nativename $path] SHA256]
 if {![regexp -nocase {[0-9a-f]{64}} $output digest]} {
  error "Unable to parse SHA-256 for $path"
 }
 return [string tolower $digest]
}

set actual_sha [file_sha256 $bitstream]
set probes_sha [file_sha256 $probes]
if {$actual_sha ne [string tolower $expected_sha]} {
 error "Refusing to program: bitstream SHA-256 mismatch expected=$expected_sha actual=$actual_sha"
}
if {$probes_sha ne [string tolower $expected_probes_sha]} {
 error "Refusing to program: probes SHA-256 mismatch expected=$expected_probes_sha actual=$probes_sha"
}

set dev {}
set command_probe {}
set run_probe {}
set dac_probe {}
set deploy_status [catch {
open_hw_manager
connect_hw_server -allow_non_jtag
set targets [get_hw_targets -quiet localhost:3121/xilinx_tcf/Xilinx/*]
if {[llength $targets]!=1} { error "Expected exactly one local Xilinx JTAG target" }
set target [lindex $targets 0]
current_hw_target $target
open_hw_target
set devices [get_hw_devices -quiet -filter {PART == "xczu7"}]
if {[llength $devices]!=1} { error "Expected exactly one xczu7 ZCU106 device" }
set dev [lindex $devices 0]
current_hw_device $dev
set_property PROGRAM.FILE [file normalize $bitstream] $dev
set_property PROBES.FILE [file normalize $probes] $dev
set_property FULL_PROBES.FILE [file normalize $probes] $dev
program_hw_devices $dev
refresh_hw_device $dev

# Programming recreates the control VIO at INIT=0, but Vivado can retain a
# stale OUTPUT_VALUE property from the previous image. Reassert both hardware
# interlocks before touching the scan VIO. The corrected image permits only
# digital hold/abort op4 while dac_enable=0; all array-touching operations stay
# blocked by the DAC interlock.
set control_vio [get_hw_vios -quiet -of_objects $dev -filter {CELL_NAME == "u_run_vio"}]
set run_probe [get_hw_probes -quiet run_enable -of_objects $control_vio -filter {TYPE == vio_output}]
set dac_probe [get_hw_probes -quiet dac_enable -of_objects $control_vio -filter {TYPE == vio_output}]
if {[llength $control_vio]!=1 || [llength $run_probe]!=1 || [llength $dac_probe]!=1} {
 error "Programmed image does not expose the expected ADC/DAC interlocks"
}

proc force_safe_interlocks {} {
 global control_vio run_probe dac_probe
 set_property OUTPUT_VALUE 0 $run_probe
 set_property OUTPUT_VALUE 0 $dac_probe
 commit_hw_vio [list $run_probe $dac_probe]
 after 20
 refresh_hw_vio $control_vio
 if {[expr 0x[get_property OUTPUT_VALUE $run_probe]]!=0 ||
     [expr 0x[get_property OUTPUT_VALUE $dac_probe]]!=0} {
  error "ADC/DAC VIO interlocks did not remain disabled"
 }
}
force_safe_interlocks

set scan_vio [get_hw_vios -quiet -of_objects $dev -filter {CELL_NAME == "u_scan_vio"}]
set command_probe [get_hw_probes -quiet scan_command -of_objects $scan_vio -filter {TYPE == vio_output}]
set result0_probe [get_hw_probes -quiet scan_result0 -of_objects $scan_vio -filter {TYPE == vio_input}]
set result1_probe [get_hw_probes -quiet scan_result1 -of_objects $scan_vio -filter {TYPE == vio_input}]
if {[llength $scan_vio]!=1 || [llength $command_probe]!=1 ||
    [llength $result0_probe]!=1 || [llength $result1_probe]!=1} {
 error "Programmed image does not expose the expected scan VIO"
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
   error "Post-program operation $op timeout status=$h0/$h1"
  }
  after 10
 }
 if {$s&1024} { error "Post-program operation $op fault: $h0/$h1" }
 return [list $h0 $h1]
}

# Force command[62]=0 first. This clears the wrapper, tri-states the scan
# outputs, and synchronizes its toggle even if Vivado retained an old VIO
# OUTPUT_VALUE. Operation 14 is wrapper-local, so its read-only identity
# transaction remains valid while the DAC interlock is deliberately off.
proc disable_scan_interface {} {
 global command_probe scan_vio
 set_property OUTPUT_VALUE 0000000000000000 $command_probe
 commit_hw_vio $command_probe
 after 20
 refresh_hw_vio $scan_vio
}
disable_scan_interface
lassign [scan_command 14 [expr {1<<56}]] verify0 verify1
set verify [expr 0x$verify1]
if {($verify>>224)!=0x424D5032 || !(($verify>>223)&1)} {
 error "Programmed image failed bitmap-protocol identity check: $verify0/$verify1"
}
# op4 is intentionally the only inner-core command allowed with dac_enable=0.
# It owns only the digital scan pins, asserts Caravel RESET_B, and cannot issue
# a DAC start or array pulse. Require its acknowledgement before writing a
# successful deployment receipt.
lassign [scan_command 4 0] hold0 hold1
set hold [expr 0x$hold0]
if {($hold&1024) || (($hold>>32)&1)!=1 || ($hold&255)!=9} {
 error "Programmed image did not enter the verified reset hold: $hold0/$hold1"
}
force_safe_interlocks

file mkdir [file dirname [file normalize $receipt]]
set output [open $receipt w]
puts $output "{"
puts $output "  \"protocol\": \"ZCU106_BITMAP_V1\","
puts $output "  \"jtag_target\": \"[string map {\\ \\\\ \" \\\"} [get_property NAME $target]]\","
puts $output "  \"device_name\": \"[string map {\\ \\\\ \" \\\"} [get_property NAME $dev]]\","
puts $output "  \"device_part\": \"[get_property PART $dev]\","
puts $output "  \"bitstream\": \"[string map {\\ \\\\ \" \\\"} [file normalize $bitstream]]\","
puts $output "  \"bitstream_sha256\": \"$actual_sha\","
puts $output "  \"probes\": \"[string map {\\ \\\\ \" \\\"} [file normalize $probes]]\","
puts $output "  \"probes_sha256\": \"$probes_sha\","
puts $output "  \"programmed_utc\": \"[clock format [clock seconds] -gmt 1 -format {%Y-%m-%dT%H:%M:%SZ}]\","
puts $output "  \"post_program_state\": \"adc_off_dac_reset_caravel_reset_held_no_array_pulse\","
puts $output "  \"caravel_reset_drive\": \"asserted_low_by_fpga_op4\""
puts $output "}"
close $output
puts "PROGRAM_DONE bitstream_sha256=$actual_sha probes_sha256=$probes_sha receipt=$receipt"
flush stdout
} deploy_message deploy_options]

# On every exit, best-effort reassert the digital-only hold and both hardware
# interlocks. If hold cannot acknowledge (for example an incompatible image),
# fall back to command[62]=0 so no FPGA scan output remains actively driven.
set scan_hold_status 0
set scan_disable_status 0
set interlock_status 0
if {[llength $command_probe]==1 && [llength [info commands scan_command]]} {
 set scan_hold_status [catch {scan_command 4 0 2000} scan_hold_message]
 if {$scan_hold_status && [llength [info commands disable_scan_interface]]} {
  set scan_disable_status [catch {disable_scan_interface} scan_disable_message]
 }
}
if {[llength $run_probe]==1 && [llength $dac_probe]==1 &&
    [llength [info commands force_safe_interlocks]]} {
 set interlock_status [catch {force_safe_interlocks} interlock_message]
}
catch {close_hw_manager}
if {$deploy_status} {
 if {$scan_hold_status} { puts stderr "WARNING: post-error reset hold also failed: $scan_hold_message" }
 if {$scan_disable_status} { puts stderr "WARNING: post-error scan disable also failed: $scan_disable_message" }
 if {$interlock_status} { puts stderr "WARNING: post-error interlock disable also failed: $interlock_message" }
 return -options $deploy_options $deploy_message
}
if {$scan_hold_status} { error "Image programmed but final reset hold failed: $scan_hold_message" }
if {$scan_disable_status} { error "Image programmed but fallback scan disable failed: $scan_disable_message" }
if {$interlock_status} { error "Image programmed but final interlock disable failed: $interlock_message" }
exit
