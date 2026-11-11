# Uses the existing PCB DAC scan profile and preserved FMC electrical settings.
set here [file dirname [file normalize [info script]]]
source [file join $here i2c_host.tcl]
source [file join $here assert_clock.tcl]
assert_caravel_clock
set control_vio [get_hw_vios -quiet -of_objects $dev -filter {CELL_NAME == "u_run_vio"}]
if {[llength $control_vio] != 1} { error "ADC/DAC VIO missing" }
proc p {name type} {
    global control_vio
    set v [get_hw_probes -quiet $name -of_objects $control_vio -filter "TYPE == $type"]
    if {[llength $v] != 1} { error "Missing unique $type probe $name" }
    return $v
}
proc value {name} { return [expr 0x[get_property INPUT_VALUE [p $name vio_input]]] }
refresh_hw_vio $control_vio
foreach {name expected} {dac_enable_2 1 dac_ready 1 dac_frame_index 20 dac_reset_n 1 dac_ncs 1 dac_sclk 0 pll_locked 1} {
    if {[value $name] != $expected} { error "Precondition failed: $name" }
}
set run_probe [p run_enable vio_output]
set_property OUTPUT_VALUE 1 $run_probe
commit_hw_vio $run_probe
set deadline [expr {[clock milliseconds] + 2000}]
while {1} {
    refresh_hw_vio $control_vio
    set complete 1
    foreach {name expected} {run_enable_2 1 adc_clock_running 1 adc_reset_n 1 config_done 1 sequence_index 7 control_state 11 spi_ncs 1 spi_sclk 0 pll_locked 1} {
        if {[value $name] != $expected} { set complete 0 }
    }
    if {$complete} { break }
    if {[clock milliseconds] > $deadline} {
        set_property OUTPUT_VALUE 0 $run_probe
        commit_hw_vio $run_probe
        error "ADC startup timeout; ADC clock stopped and reset asserted"
    }
    after 10
}
foreach name {run_enable_2 adc_clock_running adc_reset_n config_done sequence_index control_state spi_ncs spi_sclk pll_locked dac_enable_2 dac_ready dac_frame_index} {
    puts "LIVE_STATUS $name=[value $name]"
}
puts "ADS5282_10MSPS_SPI_SEQUENCE_COMPLETED"
puts "Sent: 124333 030002 010010 E30060 C78001 DE01C0 428001 250000"
puts "Internal nominal 94 ohm source termination; normal analog data; offset binary; LSB first."
puts "SPI completion is not ADC register readback. Returned LCLK/ADCLK must be checked separately."
assert_caravel_clock
if {$argv eq {CAPTURE}} {
    set ila [get_hw_ilas -quiet -of_objects $dev]
    if {[llength $ila] != 1} {error "Expected one ADC ILA"}
    set_property CONTROL.DATA_DEPTH 4096 $ila
    set_property CONTROL.TRIGGER_POSITION 512 $ila
    run_hw_ila $ila
    set deadline [expr {[clock milliseconds] + 10000}]
    while {1} {
        refresh_hw_ila $ila
        if {[get_property STATUS $ila] eq "IDLE"} {break}
        if {[clock milliseconds] > $deadline} {
            stop_hw_ila $ila
            error "No completed ILA capture within 10 s: returned LCLK not verified"
        }
        after 50
    }
    upload_hw_ila_data $ila
    file mkdir [file join $here captures]
    set csv [file join $here captures "adc_fmc_[clock format [clock seconds] -format %Y%m%d_%H%M%S].csv"]
    write_hw_ila_data -csv_file $csv [get_hw_ila_data -of_objects $ila]
    puts "ADC_RETURN_INTERFACE_CAPTURE=$csv"
    puts "Capture includes FMC channels 1..5 only. ADC6 at J8 is not wired to the KC705."
}
close_i2c_bridge
exit
