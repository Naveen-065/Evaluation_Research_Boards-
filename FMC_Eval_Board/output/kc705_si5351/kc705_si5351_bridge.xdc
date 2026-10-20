# KC705 fixed management I2C bus and 200 MHz system clock.
set_property PACKAGE_PIN AD12 [get_ports sysclk_p]
set_property PACKAGE_PIN AD11 [get_ports sysclk_n]
set_property IOSTANDARD LVDS [get_ports {sysclk_p sysclk_n}]
create_clock -name sysclk_200mhz -period 5.000 [get_ports sysclk_p]

set_property PACKAGE_PIN K21 [get_ports iic_scl_main]
set_property PACKAGE_PIN L21 [get_ports iic_sda_main]
set_property PACKAGE_PIN P23 [get_ports iic_mux_reset_b]
set_property IOSTANDARD LVCMOS25 [get_ports {iic_scl_main iic_sda_main iic_mux_reset_b}]
set_property DRIVE 4 [get_ports {iic_scl_main iic_sda_main iic_mux_reset_b}]
set_property SLEW SLOW [get_ports {iic_scl_main iic_sda_main iic_mux_reset_b}]

set_property PACKAGE_PIN AB8 [get_ports led0]
set_property IOSTANDARD LVCMOS15 [get_ports led0]
set_property DRIVE 4 [get_ports led0]
set_property SLEW SLOW [get_ports led0]

set_property BITSTREAM.CONFIG.UNUSEDPIN Pullnone [current_design]
set_property CFGBVS VCCO [current_design]
set_property CONFIG_VOLTAGE 2.5 [current_design]
