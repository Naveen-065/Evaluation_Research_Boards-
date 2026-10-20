# Pins copied from AMD's KC705 Rev 1.0 master XDC.
set_property PACKAGE_PIN AD12 [get_ports SYSCLK_P]
set_property IOSTANDARD LVDS [get_ports SYSCLK_P]
set_property PACKAGE_PIN AD11 [get_ports SYSCLK_N]
set_property IOSTANDARD LVDS [get_ports SYSCLK_N]
create_clock -name sysclk_200mhz -period 5.000 [get_ports SYSCLK_P]

set_property PACKAGE_PIN AB8 [get_ports GPIO_LED_0_LS]
set_property IOSTANDARD LVCMOS15 [get_ports GPIO_LED_0_LS]
set_property DRIVE 8 [get_ports GPIO_LED_0_LS]
set_property SLEW SLOW [get_ports GPIO_LED_0_LS]

# Do not enable internal pulls on any unused pin, including all FMC signals.
set_property BITSTREAM.CONFIG.UNUSEDPIN Pullnone [current_design]

# KC705 bank 0 and CFGBVS are tied to VCC2V5_FPGA in the official schematic.
set_property CFGBVS VCCO [current_design]
set_property CONFIG_VOLTAGE 2.5 [current_design]
