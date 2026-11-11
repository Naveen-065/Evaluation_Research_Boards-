# Hardware-free integration test for row_order_read.tcl.  The mocked VIO
# responds synchronously and records every opcode/payload, allowing the real
# tool body, CSV/JSON generation, and cleanup path to execute without JTAG.

set here [file dirname [file normalize [info script]]]
set fpga_root [file normalize [file join $here ..]]
set output_prefix [file join $fpga_root output row_order_test mock_reverse]
file mkdir [file dirname $output_prefix]
file delete -force "${output_prefix}.csv" "${output_prefix}.json"

set ::mock_command 0
set ::mock_result0 0
set ::mock_result1 0
set ::mock_commands {}
set ::mock_close_count 0
set ::mock_read_count 0
set ::mock_fail_read_at -1

proc mock_hex {value digits} {
 set result {}
 for {set index 0} {$index<$digits} {incr index} {
  set result "[string index 0123456789ABCDEF [expr {$value&15}]]$result"
  set value [expr {$value>>4}]
 }
 if {$value!=0} { error "mock hexadecimal value overflow" }
 return $result
}

proc open_hw_manager {} {}
proc connect_hw_server {args} {}
proc get_hw_targets {args} { return mock_target }
proc current_hw_target {args} {}
proc open_hw_target {args} {}
proc get_hw_devices {args} { return mock_device }
proc current_hw_device {args} {}
proc refresh_hw_device {args} {}
proc close_hw_target {args} {}
proc disconnect_hw_server {args} {}
proc close_hw_manager {args} { incr ::mock_close_count }

proc get_hw_vios {args} {
 set joined [join $args { }]
 if {[string match {*u_i2c_vio*} $joined]} { return mock_i2c_vio }
 if {[string match {*u_scan_vio*} $joined]} { return mock_scan_vio }
 return {}
}

proc get_hw_probes {args} {
 set joined [join $args { }]
 if {[string match {*mock_i2c_vio*} $joined]} {
  if {[string match {*vio_output*} $joined]} { return mock_i2c_command }
  return mock_i2c_status
 }
 if {[string match {*scan_command*} $joined]} { return mock_scan_command }
 if {[string match {*scan_result0*} $joined]} { return mock_scan_result0 }
 if {[string match {*scan_result1*} $joined]} { return mock_scan_result1 }
 return {}
}

proc set_property {property value object} {
 if {$property eq "OUTPUT_VALUE" && $object eq "mock_scan_command"} {
  set ::mock_command [expr 0x$value]
 }
}

proc get_property {property object} {
 if {$property eq "OUTPUT_VALUE" && $object eq "mock_scan_command"} {
  return [mock_hex $::mock_command 16]
 }
 if {$property eq "INPUT_VALUE" && $object eq "mock_scan_result0"} {
  return [mock_hex $::mock_result0 64]
 }
 if {$property eq "INPUT_VALUE" && $object eq "mock_scan_result1"} {
  return [mock_hex $::mock_result1 64]
 }
 if {$property eq "INPUT_VALUE" && $object eq "mock_i2c_status"} {
  return 0
 }
 return {}
}

proc refresh_hw_vio {args} {}
proc commit_hw_vio {probe} {
 if {$probe ne "mock_scan_command"} { return }
 set command $::mock_command
 set toggle [expr {($command>>63)&1}]
 set op [expr {($command>>58)&15}]
 set payload [expr {$command&((1<<58)-1)}]
 lappend ::mock_commands [list $op $payload]
 set ::mock_result0 [expr {($toggle<<15)|512}]
 set ::mock_result1 0

 if {$op==1} {
  incr ::mock_read_count
  if {$::mock_read_count==$::mock_fail_read_at} {
   # Completed+fault response: scan_command must detect this, abort, restore
   # the read profile, and leave only explicit .partial output files.
   set ::mock_result0 [expr {($toggle<<15)|512|1024|(4<<11)}]
   return
  }
  set row [expr {$payload&31}]
  set column [expr {($payload>>5)&31}]
  set packet [expr {($row<<10)|($column<<5)|$row}]
  set baseline_count 600
  set active_count 12000
  set baseline_sum [expr {1200*$baseline_count}]
  set active_sum [expr {1220*$active_count}]
  set ::mock_result0 [expr {$::mock_result0|($packet<<16)|
                                 ($baseline_count<<64)|($active_count<<80)|
                                 ($baseline_sum<<160)}]
  set ::mock_result1 [expr {(0x53435232<<224)|($active_sum<<64)}]
 } elseif {$op==14} {
  if (!(($payload>>56)&1)) { error "mock observed forbidden mutating op14" }
  set ::mock_result1 [expr {(0x424D5032<<224)|(1<<223)}]
 } elseif {$op ni {2 4}} {
  error "mock observed forbidden opcode $op"
 }
}

proc assert_equal {actual expected label} {
 if {$actual ne $expected} { error "$label: expected '$expected', got '$actual'" }
}

# Prevent the tool's final exit command from terminating this test harness.
rename exit real_exit
proc exit {args} { return }
set argc 3
set argv [list $output_prefix 5 reverse]
set tool_status [catch {source [file join $fpga_root tools row_order_read.tcl]} tool_message tool_options]
rename exit {}
rename real_exit exit
if {$tool_status} { return -options $tool_options $tool_message }

set op1_payloads {}
array set counts {1 0 2 0 4 0 14 0}
foreach item $::mock_commands {
 lassign $item op payload
 if {![info exists counts($op)]} { error "forbidden opcode escaped allowlist: $op" }
 incr counts($op)
 if {$op==1} { lappend op1_payloads $payload }
}
assert_equal $counts(1) 32 "one independent read per column"
assert_equal $counts(2) 20 "initial and final read-profile commands"
assert_equal $counts(4) 3 "initial hold plus final abort/profile hold"
assert_equal $counts(14) 1 "one read-only identity query"
assert_equal $::mock_close_count 1 "hardware-manager cleanup"

foreach unsafe_case [list \
    [list 1 [expr {1<<57}] {*forbidden SET/MAC/reserved bits*}] \
    [list 2 [expr {1<<24}] {*exceeds the 24-bit frame*}] \
    [list 4 1 {*zero payload*}] \
    [list 14 0 {*non-mutating BMP2 identity*}] \
    [list 15 0 {*Unsafe opcode*}]] {
 lassign $unsafe_case unsafe_op unsafe_payload unsafe_pattern
 if {![catch {scan_command $unsafe_op $unsafe_payload} unsafe_message] ||
     ![string match $unsafe_pattern $unsafe_message]} {
  error "unsafe command was not rejected: op=$unsafe_op message=$unsafe_message"
 }
}

set expected_columns {}
for {set column 31} {$column>=0} {incr column -1} { lappend expected_columns $column }
set observed_columns {}
foreach payload $op1_payloads {
 assert_equal [expr {$payload&31}] 5 "requested row"
 assert_equal [expr {$payload>>10}] 2400 "read hold clocks"
 lappend observed_columns [expr {($payload>>5)&31}]
}
assert_equal $observed_columns $expected_columns "reverse acquisition order"

set csv [open "${output_prefix}.csv" r]
set csv_lines [split [string trim [read $csv]] "\n"]
close $csv
assert_equal [llength $csv_lines] 33 "CSV header plus 32 cells"

set json [open "${output_prefix}.json" r]
set json_text [read $json]
close $json
if {![string match {*"protocol": "ZCU106_ROW_ORDER_READ_V1"*} $json_text] ||
    ![string match {*"column_order_mode": "reverse"*} $json_text] ||
    ![string match {*"seed": null*} $json_text]} {
 error "JSON metadata is incomplete"
}

# Re-run the real tool body with the third read forced to report an FPGA fault.
# Final filenames must not be promoted, but cleanup must still issue abort and
# every command in the read-profile restoration sequence before closing JTAG.
set failure_prefix [file join $fpga_root output row_order_test mock_failure]
foreach suffix {.csv .json .csv.partial .json.partial} {
 file delete -force "${failure_prefix}${suffix}"
}
set ::mock_command 0
set ::mock_result0 0
set ::mock_result1 0
set ::mock_commands {}
set ::mock_close_count 0
set ::mock_read_count 0
set ::mock_fail_read_at 3

rename exit real_exit
proc exit {args} { return }
set argc 3
set argv [list $failure_prefix 6 forward]
set failure_status [catch {source [file join $fpga_root tools row_order_read.tcl]} failure_message]
rename exit {}
rename real_exit exit
if {!$failure_status || ![string match {*Controller fault*} $failure_message]} {
 error "injected read fault was not propagated: $failure_message"
}

array set failure_counts {1 0 2 0 4 0 14 0}
foreach item $::mock_commands {
 lassign $item op payload
 if {![info exists failure_counts($op)]} { error "failure path issued forbidden opcode $op" }
 incr failure_counts($op)
}
assert_equal $failure_counts(1) 3 "injected failure read count"
assert_equal $failure_counts(2) 20 "failure-path read-profile restoration"
assert_equal $failure_counts(4) 3 "failure-path safe abort and holds"
assert_equal $failure_counts(14) 1 "failure-path identity query"
assert_equal $::mock_close_count 1 "failure-path hardware-manager cleanup"
if {[file exists "${failure_prefix}.csv"] || [file exists "${failure_prefix}.json"]} {
 error "failed acquisition promoted a final output"
}
if {![file exists "${failure_prefix}.csv.partial"] ||
    ![file exists "${failure_prefix}.json.partial"]} {
 error "failed acquisition did not retain explicit partial evidence"
}

puts "PASS row-order read-only mock integration, failure cleanup, and atomic outputs"
exit
