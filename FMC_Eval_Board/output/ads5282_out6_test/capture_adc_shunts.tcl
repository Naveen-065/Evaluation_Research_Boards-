set here [file dirname [file normalize [info script]]]
set capture_dir [file join $here captures]
set ltx [file join $here build kc705_dac_pcb.ltx]
if {![file exists $ltx]} { error "Missing build/kc705_dac_pcb.ltx" }
file mkdir $capture_dir
set stamp [clock format [clock seconds] -format "%Y%m%d_%H%M%S"]
set csv [file join $capture_dir "ads5282_analog_${stamp}.csv"]

open_hw_manager
connect_hw_server -allow_non_jtag
set target [get_hw_targets -quiet localhost:3121/xilinx_tcf/Xilinx/00001f14c98801]
if {[llength $target] != 1} { error "Known KC705 JTAG cable 00001f14c98801 not found" }
current_hw_target $target
open_hw_target
set dev [get_hw_devices -quiet -filter {PART == "xc7k325t"}]
if {[llength $dev] != 1} { error "Expected exactly one Kintex-7 xc7k325t" }
current_hw_device $dev
set_property PROBES.FILE $ltx $dev
set_property FULL_PROBES.FILE $ltx $dev
refresh_hw_device $dev

set vios [get_hw_vios -quiet -of_objects $dev -filter {CELL_NAME == "u_run_vio"}]
if {[llength $vios] != 1} { error "Expected exactly one run-control VIO" }
set run_probe [get_hw_probes -quiet -of_objects [lindex $vios 0] -filter {TYPE == vio_output && NAME == run_enable}]
if {[llength $run_probe] != 1} { error "Expected one VIO output named run_enable" }
refresh_hw_vio [lindex $vios 0]
if {[get_property OUTPUT_VALUE $run_probe] != 1} {
    error "ADC test is disabled; run enable_adc_test.tcl only after fitting terminations"
}
set dac_probe [get_hw_probes -quiet -of_objects [lindex $vios 0] -filter {TYPE == vio_output && NAME == dac_enable}]
if {[llength $dac_probe] != 1 || [get_property OUTPUT_VALUE $dac_probe] != 1} {
    error "DAC shunt rails are disabled; enable and measure them before capture"
}

set ilas [get_hw_ilas -quiet -of_objects $dev]
if {[llength $ilas] != 1} { error "Expected exactly one ADC capture ILA" }
set ila [lindex $ilas 0]
set_property CONTROL.DATA_DEPTH 4096 $ila
set_property CONTROL.TRIGGER_POSITION 512 $ila
# With every trigger comparator left at don't-care, this is an immediate
# diagnostic snapshot on the running LCLK domain.
run_hw_ila $ila
# An absent LCLK must fail cleanly rather than leave a batch job blocked.
set deadline [expr {[clock milliseconds] + 10000}]
while {[get_property STATUS $ila] ne "IDLE"} {
    if {[clock milliseconds] > $deadline} {
        stop_hw_ila $ila
        error "ILA capture timeout: no usable LCLK/trigger within 10 seconds"
    }
    after 50
}
upload_hw_ila_data $ila
set data [get_hw_ila_data -of_objects $ila]
write_hw_ila_data -csv_file $csv $data
puts "ADS5282_CAPTURE_WRITTEN $csv"
close_hw_target
disconnect_hw_server
close_hw_manager
exit
