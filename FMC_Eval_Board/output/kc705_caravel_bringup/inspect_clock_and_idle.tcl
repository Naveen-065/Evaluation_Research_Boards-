set here [file dirname [file normalize [info script]]]
source [file join $here i2c_host.tcl]
if {[mux_read] != 4} { error "FMC I2C channel is no longer selected" }
foreach {reg wanted} {
    3 0xFC 16 0x4F 17 0x4F 18 0x80
    26 0 27 1 28 0 29 0x10 30 0 31 0 32 0 33 0
    42 0 43 1 44 0 45 0x2B 46 0 47 0 48 0 49 0
    50 0 51 1 52 0 53 0x2B 54 0 55 0 56 0 57 0
} {
    set value [si5351_read $reg]
    if {$value != $wanted} { error "Clock configuration changed: reg $reg expected $wanted actual $value" }
}
set status0 [si5351_read 0]
if {$status0 & 0xA8} { error "Si5351 SYS_INIT, PLLA loss-of-lock, or crystal loss set" }
puts [format "SI5351_10MHZ_STILL_CONFIGURED_AND_PLLA_LOCKED status=0x%02X" $status0]
set control_vio [get_hw_vios -quiet -of_objects $dev -filter {CELL_NAME == "u_run_vio"}]
if {[llength $control_vio] != 1} { error "ADC/DAC VIO missing" }
refresh_hw_vio $control_vio
foreach {name wanted} {
    run_enable_2 0 adc_clock_running 0 adc_reset_n 0 spi_ncs 1 spi_sclk 0
    dac_enable_2 0 dac_reset_n 0 dac_ready 0 dac_ncs 1 dac_sclk 0
} {
    set p [get_hw_probes -quiet $name -of_objects $control_vio]
    if {[llength $p] != 1} { error "Status probe $name missing" }
    set value [expr 0x[get_property INPUT_VALUE $p]]
    puts "IDLE_STATE $name=$value"
    if {$value != $wanted} { error "Unexpected controller state" }
}
puts "ADC_DAC_REMAIN_DISABLED"
close_i2c_bridge
exit
