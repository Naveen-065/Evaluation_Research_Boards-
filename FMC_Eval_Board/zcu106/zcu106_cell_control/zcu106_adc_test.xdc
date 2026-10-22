# ZCU106 300 MHz USER_SI570 clock and PL user LED.
set_property PACKAGE_PIN AH12 [get_ports sysclk_p]
set_property PACKAGE_PIN AJ12 [get_ports sysclk_n]
set_property IOSTANDARD DIFF_SSTL12 [get_ports {sysclk_p sysclk_n}]
create_clock -name sysclk_300mhz -period 3.333 [get_ports sysclk_p]

set_property PACKAGE_PIN AL11 [get_ports led0]
set_property IOSTANDARD LVCMOS12 [get_ports led0]
set_property DRIVE 4 [get_ports led0]
set_property SLEW SLOW [get_ports led0]

# FMC HPC0/J5.  Every used connector signal belongs to the LPC subset.
# The shared VADJ_FMC rail must be 1.8 V before this image is programmed.
set_property PACKAGE_PIN H19 [get_ports out4_p]
set_property PACKAGE_PIN G19 [get_ports out4_n]
set_property PACKAGE_PIN K17 [get_ports out5_p]
set_property PACKAGE_PIN J17 [get_ports out5_n]
set_property PACKAGE_PIN F17 [get_ports lclk_p]
set_property PACKAGE_PIN F16 [get_ports lclk_n]
set_property PACKAGE_PIN K19 [get_ports out2_p]
set_property PACKAGE_PIN K18 [get_ports out2_n]
set_property PACKAGE_PIN E15 [get_ports adclk_p]
set_property PACKAGE_PIN E14 [get_ports adclk_n]
set_property PACKAGE_PIN L20 [get_ports out1_p]
set_property PACKAGE_PIN K20 [get_ports out1_n]
set_property PACKAGE_PIN L17 [get_ports out3_p]
set_property PACKAGE_PIN L16 [get_ports out3_n]
set_property IOSTANDARD LVDS [get_ports {
    out4_p out4_n out5_p out5_n lclk_p lclk_n out2_p out2_n
    adclk_p adclk_n out1_p out1_n out3_p out3_n
}]
set_property DIFF_TERM_ADV TERM_NONE [get_ports {
    out4_p out4_n out5_p out5_n lclk_p lclk_n out2_p out2_n
    adclk_p adclk_n out1_p out1_n out3_p out3_n
}]
create_clock -name adc_lclk -period 16.667 [get_ports lclk_p]
set_clock_groups -asynchronous \
    -group [get_clocks -include_generated_clocks sysclk_300mhz] \
    -group [get_clocks adc_lclk]

# LA01, connector D8/D9.  D9 is intentionally a driven-low reference.
set_property PACKAGE_PIN H18 [get_ports fpga_mclkin_p]
set_property PACKAGE_PIN H17 [get_ports fpga_mclkin_n]
set_property IOSTANDARD LVCMOS18 [get_ports {fpga_mclkin_p fpga_mclkin_n}]
set_property DRIVE 12 [get_ports {fpga_mclkin_p fpga_mclkin_n}]
set_property SLEW SLOW [get_ports {fpga_mclkin_p fpga_mclkin_n}]

# Other mezzanine-to-FPGA signals.
set_property PACKAGE_PIN L15 [get_ports fpga_rx]
set_property PACKAGE_PIN C13 [get_ports scan_si]
set_property PACKAGE_PIN H16 [get_ports ready_i]
set_property PACKAGE_PIN G16 [get_ports reset_b]
set_property PACKAGE_PIN D16 [get_ports si5351_clk1_1v8]
set_property IOSTANDARD LVCMOS18 [get_ports {
    fpga_rx scan_si ready_i reset_b si5351_clk1_1v8
}]
set_property PULLTYPE NONE [get_ports {
    fpga_rx scan_si ready_i reset_b si5351_clk1_1v8
}]

# FPGA-to-mezzanine control signals.
set_property PACKAGE_PIN K15 [get_ports fpga_tx]
set_property PACKAGE_PIN C12 [get_ports scan_cc]
set_property PACKAGE_PIN G15 [get_ports scan_se]
set_property PACKAGE_PIN F15 [get_ports scan_tm]
set_property PACKAGE_PIN E18 [get_ports aq1_sck]
set_property PACKAGE_PIN E17 [get_ports aq1_mosi]
set_property PACKAGE_PIN G18 [get_ports fpga_sck]
set_property PACKAGE_PIN F18 [get_ports fpga_sdata]
set_property PACKAGE_PIN D17 [get_ports adc_pd]
set_property PACKAGE_PIN C17 [get_ports fpga_loe]
set_property PACKAGE_PIN J16 [get_ports aq1_ncs]
set_property PACKAGE_PIN J15 [get_ports aq1_nldac]
set_property PACKAGE_PIN A13 [get_ports fpga_ncs]
set_property PACKAGE_PIN A12 [get_ports fpga_nadcrst]
set_property PACKAGE_PIN C16 [get_ports aq1_nrst]
set_property IOSTANDARD LVCMOS18 [get_ports {
    fpga_tx scan_cc scan_se scan_tm aq1_sck aq1_mosi fpga_sck
    fpga_sdata adc_pd fpga_loe aq1_ncs aq1_nldac fpga_ncs
    fpga_nadcrst aq1_nrst
}]
set_property DRIVE 4 [get_ports {
    fpga_tx scan_cc scan_se scan_tm aq1_sck aq1_mosi fpga_sck
    fpga_sdata adc_pd fpga_loe aq1_ncs aq1_nldac fpga_ncs
    fpga_nadcrst aq1_nrst scan_si reset_b
}]
set_property SLEW SLOW [get_ports {
    fpga_tx scan_cc scan_se scan_tm aq1_sck aq1_mosi fpga_sck
    fpga_sdata adc_pd fpga_loe aq1_ncs aq1_nldac fpga_ncs
    fpga_nadcrst aq1_nrst scan_si reset_b
}]
set_property PULLTYPE NONE [get_ports {
    fpga_tx scan_cc scan_se scan_tm aq1_sck aq1_mosi fpga_sck
    fpga_sdata adc_pd fpga_loe aq1_ncs aq1_nldac fpga_ncs
    fpga_nadcrst aq1_nrst
}]

set_false_path -to [get_cells -hier -filter {NAME =~ *input_sync_1_reg*}]
set_false_path -to [get_cells -hier -filter {NAME =~ scan_reader/*_sync_reg[0]}]
set_property BITSTREAM.CONFIG.UNUSEDPIN Pullnone [current_design]
