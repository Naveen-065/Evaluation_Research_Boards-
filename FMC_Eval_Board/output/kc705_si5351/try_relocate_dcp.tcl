set here [file dirname [file normalize [info script]]]
open_checkpoint {C:/Users/fpga.DESKTOP-CVDV1JP/kc705_vadj/build/kc705_vadj_bridge.dcp}
set_property PACKAGE_PIN K21 [get_ports pmbus_scl]
set_property PACKAGE_PIN L21 [get_ports pmbus_sda]
set_property IOSTANDARD LVCMOS25 [get_ports {pmbus_scl pmbus_sda}]
puts "NEW_SCL PACKAGE_PIN=[get_property PACKAGE_PIN [get_ports pmbus_scl]] IOSTANDARD=[get_property IOSTANDARD [get_ports pmbus_scl]]"
puts "NEW_SDA PACKAGE_PIN=[get_property PACKAGE_PIN [get_ports pmbus_sda]] IOSTANDARD=[get_property IOSTANDARD [get_ports pmbus_sda]]"
report_io -file [file join $here relocated_io_before_route.rpt]
write_checkpoint -force [file join $here relocated_before_route.dcp]
exit
