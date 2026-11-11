open_hw_manager
connect_hw_server -allow_non_jtag
foreach target [get_hw_targets -quiet] {
    puts "TARGET=$target"
    if {[catch {open_hw_target $target} msg]} { puts "OPEN_FAILED=$msg"; continue }
    foreach dev [get_hw_devices -quiet] {
        puts "DEVICE=$dev PART=[get_property PART $dev]"
        if {[get_property PART $dev] eq "xc7z020"} {
            current_hw_device $dev
            set_property PROBES.FILE {C:/Users/fpga.DESKTOP-CVDV1JP/zynq_scan_debug/caravel_scan_debug_runtime_dac81416_uart_wb_highz_v35_wb_read_repair.ltx} $dev
            refresh_hw_device $dev
            puts "ZYNQ_DONE=[get_property REGISTER.CONFIG_STATUS.BIT13_DONE_INTERNAL_SIGNAL_STATUS $dev]"
            foreach v [get_hw_vios -quiet -of_objects $dev] {
                puts "VIO=$v CELL=[get_property CELL_NAME $v]"
                refresh_hw_vio $v
                foreach p [get_hw_probes -quiet -of_objects $v] {
                    if {[get_property TYPE $p] eq "vio_input"} { puts "STATUS $p=[get_property INPUT_VALUE $p]" }
                    if {[get_property TYPE $p] eq "vio_output"} { puts "COMMAND $p=[get_property OUTPUT_VALUE $p]" }
                }
            }
        }
    }
    close_hw_target $target
}
disconnect_hw_server
close_hw_manager
exit
