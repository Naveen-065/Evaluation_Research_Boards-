# KC705 fixed 200 MHz system clock and user LED.
set_property PACKAGE_PIN AD12 [get_ports sysclk_p]
set_property PACKAGE_PIN AD11 [get_ports sysclk_n]
set_property IOSTANDARD LVDS [get_ports {sysclk_p sysclk_n}]
create_clock -name sysclk_200mhz -period 5.000 [get_ports sysclk_p]

set_property PACKAGE_PIN AB8 [get_ports led0]
set_property IOSTANDARD LVCMOS15 [get_ports led0]
set_property DRIVE 4 [get_ports led0]
set_property SLEW SLOW [get_ports led0]

# Seven input-only ADC differential pairs. The PCB must provide the intended
# 100-ohm receiver termination; FPGA internal termination remains off.
set_property PACKAGE_PIN AK20 [get_ports out4_p]
set_property PACKAGE_PIN AK21 [get_ports out4_n]
set_property PACKAGE_PIN AG22 [get_ports out5_p]
set_property PACKAGE_PIN AH22 [get_ports out5_n]
set_property PACKAGE_PIN AD23 [get_ports lclk_p]
set_property PACKAGE_PIN AE24 [get_ports lclk_n]
set_property PACKAGE_PIN AG20 [get_ports out2_p]
set_property PACKAGE_PIN AH20 [get_ports out2_n]
set_property PACKAGE_PIN AF22 [get_ports adclk_p]
set_property PACKAGE_PIN AG23 [get_ports adclk_n]
set_property PACKAGE_PIN AF20 [get_ports out1_p]
set_property PACKAGE_PIN AF21 [get_ports out1_n]
set_property PACKAGE_PIN AH21 [get_ports out3_p]
set_property PACKAGE_PIN AJ21 [get_ports out3_n]
set_property IOSTANDARD LVDS_25 [get_ports {
    out4_p out4_n out5_p out5_n lclk_p lclk_n out2_p out2_n
    adclk_p adclk_n out1_p out1_n out3_p out3_n
}]
set_property DIFF_TERM FALSE [get_ports {
    out4_p out4_n out5_p out5_n lclk_p lclk_n out2_p out2_n
    adclk_p adclk_n out1_p out1_n out3_p out3_n
}]

# Other permanent inputs. D8/D9 are the operational ADC clock direction in the
# full application, but this static test image leaves them input/high-Z.
# SCAN_SI and RESET_B are input-only because other devices can own those nets.
set_property PACKAGE_PIN AJ24 [get_ports fpga_rx]
set_property PACKAGE_PIN AD21 [get_ports scan_si]
set_property PACKAGE_PIN AE23 [get_ports fpga_mclkin_p]
set_property PACKAGE_PIN AF23 [get_ports fpga_mclkin_n]
set_property PACKAGE_PIN AK23 [get_ports ready_i]
set_property PACKAGE_PIN AK24 [get_ports reset_b]
set_property PACKAGE_PIN AC24 [get_ports si5351_clk1_1v8]
set_property IOSTANDARD LVCMOS18 [get_ports {
    fpga_rx scan_si fpga_mclkin_p fpga_mclkin_n
    ready_i reset_b si5351_clk1_1v8
}]
set_property PULLTYPE NONE [get_ports {
    fpga_rx scan_si fpga_mclkin_p fpga_mclkin_n
    ready_i reset_b si5351_clk1_1v8
}]

# FPGA -> PCB pins. Every pin takes only its reviewed static quiescent level.
# FPGA_LOE is low after configuration so PCB pull-up R52 cannot enable U17.
set_property PACKAGE_PIN AK25 [get_ports fpga_tx]
set_property PACKAGE_PIN AE21 [get_ports scan_cc]
set_property PACKAGE_PIN AB24 [get_ports scan_se]
set_property PACKAGE_PIN AC25 [get_ports scan_tm]
set_property PACKAGE_PIN AJ22 [get_ports aq1_sck]
set_property PACKAGE_PIN AJ23 [get_ports aq1_mosi]
set_property PACKAGE_PIN AA20 [get_ports fpga_sck]
set_property PACKAGE_PIN AB20 [get_ports fpga_sdata]
set_property PACKAGE_PIN AC22 [get_ports adc_pd]
set_property PACKAGE_PIN AD22 [get_ports fpga_loe]
set_property PACKAGE_PIN AG25 [get_ports aq1_ncs]
set_property PACKAGE_PIN AH25 [get_ports aq1_nldac]
set_property PACKAGE_PIN AE25 [get_ports fpga_ncs]
set_property PACKAGE_PIN AF25 [get_ports fpga_nadcrst]
set_property PACKAGE_PIN AD24 [get_ports aq1_nrst]
set_property IOSTANDARD LVCMOS18 [get_ports {
    fpga_tx scan_cc scan_se scan_tm aq1_sck aq1_mosi fpga_sck
    fpga_sdata adc_pd fpga_loe aq1_ncs aq1_nldac fpga_ncs
    fpga_nadcrst aq1_nrst
}]
set_property DRIVE 4 [get_ports {
    fpga_tx scan_cc scan_se scan_tm aq1_sck aq1_mosi fpga_sck
    fpga_sdata adc_pd fpga_loe aq1_ncs aq1_nldac fpga_ncs
    fpga_nadcrst aq1_nrst
}]
set_property SLEW SLOW [get_ports {
    fpga_tx scan_cc scan_se scan_tm aq1_sck aq1_mosi fpga_sck
    fpga_sdata adc_pd fpga_loe aq1_ncs aq1_nldac fpga_ncs
    fpga_nadcrst aq1_nrst
}]
set_property PULLTYPE NONE [get_ports {
    fpga_tx scan_cc scan_se scan_tm aq1_sck aq1_mosi fpga_sck
    fpga_sdata adc_pd fpga_loe aq1_ncs aq1_nldac fpga_ncs
    fpga_nadcrst aq1_nrst
}]

# Asynchronous diagnostic observations; only the first synchronizer stage is
# exempt from timing analysis.
set_false_path -to [get_cells -hier -filter {NAME =~ *input_sync_1_reg*}]

set_property BITSTREAM.CONFIG.UNUSEDPIN Pullnone [current_design]
set_property CFGBVS VCCO [current_design]
set_property CONFIG_VOLTAGE 2.5 [current_design]
