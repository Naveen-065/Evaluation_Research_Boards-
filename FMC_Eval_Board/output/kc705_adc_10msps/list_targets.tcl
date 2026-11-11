open_hw_manager
connect_hw_server -allow_non_jtag
foreach t [get_hw_targets -quiet] { puts "JTAG_TARGET=$t" }
disconnect_hw_server
close_hw_manager
exit
