# Read-only probe for the fixed-address Si5351 on either ZCU106 FMC slot.
set zcu_here [file dirname [file normalize [info script]]]
set source_dir [file normalize [file join $zcu_here .. kc705_cell_control]]
set hw_target_pattern localhost:3121/xilinx_tcf/Xilinx/*
set hw_part xczu7
set probes_file [file join $zcu_here build zcu106_adc_capture.ltx]
source [file join $source_dir i2c_host.tcl]
foreach {slot value} {HPC0/J5 0x01 HPC1/J4 0x02} {
    i2c_transfer 0x75 [list $value] 0
    set selected [lindex [i2c_transfer 0x75 [list] 1] 0]
    if {[catch {set status0 [si5351_read 0]} message]} {
        puts [format "FMC_SLOT_PROBE %s mux=0x%02X SI5351_0x60=NACK" $slot $selected]
    } else {
        puts [format "FMC_SLOT_PROBE %s mux=0x%02X SI5351_0x60=ACK status=0x%02X" $slot $selected $status0]
    }
}
# Leave all downstream I2C channels deselected.
i2c_transfer 0x75 [list 0x00] 0
close_i2c_bridge
exit

