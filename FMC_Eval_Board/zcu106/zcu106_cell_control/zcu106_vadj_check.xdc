# Only fixed-voltage carrier banks are used by this preflight image.
set_property PACKAGE_PIN AH12 [get_ports sysclk_p]
set_property PACKAGE_PIN AJ12 [get_ports sysclk_n]
set_property IOSTANDARD DIFF_SSTL12 [get_ports {sysclk_p sysclk_n}]
create_clock -name sysclk_300mhz -period 3.333 [get_ports sysclk_p]

# PL side of I2C0 through carrier level shifter U44 to PMBus mux U60.
set_property PACKAGE_PIN AE19 [get_ports iic_scl_pmbus]
set_property PACKAGE_PIN AH23 [get_ports iic_sda_pmbus]
set_property IOSTANDARD LVCMOS12 [get_ports {iic_scl_pmbus iic_sda_pmbus}]
set_property DRIVE 4 [get_ports {iic_scl_pmbus iic_sda_pmbus}]
set_property SLEW SLOW [get_ports {iic_scl_pmbus iic_sda_pmbus}]

