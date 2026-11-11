# PL side of ZCU106 I2C1.  U45 level-translates this 1.2 V bank to the
# carrier's 3.3 V shared management bus.  U135 (0x75), channel 0 routes that
# bus to FMC HPC0 C30/C31.
set_property PACKAGE_PIN AH19 [get_ports iic_scl_main]
set_property PACKAGE_PIN AL21 [get_ports iic_sda_main]
set_property IOSTANDARD LVCMOS12 [get_ports {iic_scl_main iic_sda_main}]
set_property DRIVE 4 [get_ports {iic_scl_main iic_sda_main}]
set_property SLEW SLOW [get_ports {iic_scl_main iic_sda_main}]

