# Clock-output fragment only. These names must match the integrated top level.
# This does NOT program the KC705 regulator; measure actual VADJ = 1.8 V.
# J2 D8 -> FPGA AE23 -> card C61 -> ADC CLKP.
# J2 D9 -> FPGA AF23 -> card C60 -> ADC CLKN.
set_property PACKAGE_PIN AE23 [get_ports adc_clk_p]
set_property PACKAGE_PIN AF23 [get_ports adc_clk_n_ref]
set_property IOSTANDARD LVCMOS18 [get_ports {adc_clk_p adc_clk_n_ref}]
set_property DRIVE 24 [get_ports {adc_clk_p adc_clk_n_ref}]
# Initial bench choice, not validated by the generic SPICE resistance model.
# Verify rise/fall, zero crossings, duty cycle and overshoot at the ADC.
set_property SLEW SLOW [get_ports {adc_clk_p adc_clk_n_ref}]
# Do not use OBUFDS/LVDS_25 for these two OUTPUTS at 1.8 V.
# ADC RETURN pairs use LVDS_25 INPUTS, DIFF_TERM FALSE and external termination.
