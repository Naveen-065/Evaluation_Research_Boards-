# Fixed KC705 management bus in Bank 15, independent of FMC VADJ.
# Same electrical settings as the previously tested management-I2C bridge.
set_property PACKAGE_PIN K21 [get_ports iic_scl_main]
set_property PACKAGE_PIN L21 [get_ports iic_sda_main]
set_property IOSTANDARD LVCMOS25 [get_ports {iic_scl_main iic_sda_main}]
set_property DRIVE 4 [get_ports {iic_scl_main iic_sda_main}]
set_property SLEW SLOW [get_ports {iic_scl_main iic_sda_main}]
# U49 RESET_B remains released by the carrier's existing pull-up.
