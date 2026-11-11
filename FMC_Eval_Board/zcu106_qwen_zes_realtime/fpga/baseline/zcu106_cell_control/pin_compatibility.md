# FMC pin compatibility audit

The original KC705 design uses only FMC signals that are present in the LPC
subset. A ZCU106 HPC socket is therefore connector-compatible. This port is
assigned specifically to **ZCU106 HPC0/J5**.

| Project signal | FMC signal | Connector pin | KC705 FPGA pin | ZCU106 FPGA pin |
|---|---|---:|---:|---:|
| `lclk_p/n` | LA00_CC_P/N | G6/G7 | AD23/AE24 | F17/F16 |
| `fpga_mclkin_p/n` | LA01_CC_P/N | D8/D9 | AE23/AF23 | H18/H17 |
| `out1_p/n` | LA02_P/N | H7/H8 | AF20/AF21 | L20/K20 |
| `out2_p/n` | LA03_P/N | G9/G10 | AG20/AH20 | K19/K18 |
| `out3_p/n` | LA04_P/N | H10/H11 | AH21/AJ21 | L17/L16 |
| `out5_p/n` | LA05_P/N | D11/D12 | AG22/AH22 | K17/J17 |
| `out4_p/n` | LA06_P/N | C10/C11 | AK20/AK21 | H19/G19 |
| `aq1_ncs/aq1_nldac` | LA07_P/N | H13/H14 | AG25/AH25 | J16/J15 |
| `aq1_sck/aq1_mosi` | LA08_P/N | G12/G13 | AJ22/AJ23 | E18/E17 |
| `ready_i/reset_b` | LA09_P/N | D14/D15 | AK23/AK24 | H16/G16 |
| `fpga_rx/fpga_tx` | LA10_P/N | C14/C15 | AJ24/AK25 | L15/K15 |
| `fpga_ncs/fpga_nadcrst` | LA11_P/N | H16/H17 | AE25/AF25 | A13/A12 |
| `fpga_sck/fpga_sdata` | LA12_P/N | G15/G16 | AA20/AB20 | G18/F18 |
| `scan_se/scan_tm` | LA13_P/N | D17/D18 | AB24/AC25 | G15/F15 |
| `scan_si/scan_cc` | LA14_P/N | C18/C19 | AD21/AE21 | C13/C12 |
| `si5351_clk1_1v8/aq1_nrst` | LA15_P/N | H19/H20 | AC24/AD24 | D16/C16 |
| `adc_pd/fpga_loe` | LA16_P/N | G18/G19 | AC22/AD22 | D17/C17 |
| `adclk_p/n` | CLK0_M2C_P/N | H4/H5 | AF22/AG23 | E15/E14 |
| management I2C | SCL/SDA | C30/C31 | carrier I2C mux | carrier I2C mux |

The LA and CLK0 signals use the shared 1.8 V `VADJ_FMC` rail. C30/C31 are the
separate 3.3 V management bus. On ZCU106, U135 at address `0x75` selects HPC0
with control byte `0x01`; the PL reaches the upstream bus through the U45 level
shifter using FPGA pins AH19/AL21 at LVCMOS12.

