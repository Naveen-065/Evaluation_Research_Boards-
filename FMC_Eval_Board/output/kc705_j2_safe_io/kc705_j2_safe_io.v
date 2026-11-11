`timescale 1ns/1ps

// Passive-first KC705 image for the 36 populated ordinary J2 contacts on the
// CaravelReRAM-SenseEval card. Outputs are compile-time PCB-safe static
// levels; this design contains no host-controlled or arbitrary pin drive.
module kc705_j2_safe_io (
    input wire sysclk_p,
    input wire sysclk_n,
    output wire led0,

    // ADC/PCB -> FPGA inputs.
    input wire out4_p,
    input wire out4_n,
    input wire fpga_rx,
    input wire scan_si,
    // Operational ADC input-clock outputs in the full design; deliberately
    // input/high-Z in this static safety image.
    input wire fpga_mclkin_p,
    input wire fpga_mclkin_n,
    input wire out5_p,
    input wire out5_n,
    input wire ready_i,
    input wire reset_b,
    input wire lclk_p,
    input wire lclk_n,
    input wire out2_p,
    input wire out2_n,
    input wire adclk_p,
    input wire adclk_n,
    input wire out1_p,
    input wire out1_n,
    input wire out3_p,
    input wire out3_n,
    input wire si5351_clk1_1v8,

    // FPGA -> PCB nets. These take only their reviewed quiescent levels after
    // configuration. FPGA_LOE stays low so PCB pull-up R52 cannot enable U17.
    output wire fpga_tx,
    output wire scan_cc,
    output wire scan_se,
    output wire scan_tm,
    output wire aq1_sck,
    output wire aq1_mosi,
    output wire fpga_sck,
    output wire fpga_sdata,
    output wire adc_pd,
    output wire fpga_loe,
    output wire aq1_ncs,
    output wire aq1_nldac,
    output wire fpga_ncs,
    output wire fpga_nadcrst,
    output wire aq1_nrst
);
    wire clk_raw;
    wire clk;
    reg [27:0] blink_count = 0;

    // Logical receive values from the seven ADC differential pairs.
    wire out4;
    wire out5;
    wire lclk;
    wire out2;
    wire adclk;
    wire out1;
    wire out3;

    IBUFDS sysclk_input (.I(sysclk_p), .IB(sysclk_n), .O(clk_raw));
    BUFG sysclk_global (.I(clk_raw), .O(clk));

    always @(posedge clk)
        blink_count <= blink_count + 1'b1;
    assign led0 = blink_count[27];

    // The card is expected to provide the intended external 100-ohm receiver
    // termination. The XDC sets DIFF_TERM FALSE for every pair.
    IBUFDS out4_input  (.I(out4_p),  .IB(out4_n),  .O(out4));
    IBUFDS out5_input  (.I(out5_p),  .IB(out5_n),  .O(out5));
    IBUFDS lclk_input  (.I(lclk_p),  .IB(lclk_n),  .O(lclk));
    IBUFDS out2_input  (.I(out2_p),  .IB(out2_n),  .O(out2));
    IBUFDS adclk_input (.I(adclk_p), .IB(adclk_n), .O(adclk));
    IBUFDS out1_input  (.I(out1_p),  .IB(out1_n),  .O(out1));
    IBUFDS out3_input  (.I(out3_p),  .IB(out3_n),  .O(out3));

    // Keep every physical input instantiated for the I/O audit. This simple
    // synchronizer is not an ADC receiver and cannot judge data/clock timing.
    wire [13:0] input_sample = {
        fpga_mclkin_n, fpga_mclkin_p,
        si5351_clk1_1v8, scan_si, reset_b, ready_i, fpga_rx,
        out3, out1, adclk, out2, lclk, out5, out4
    };
    (* ASYNC_REG = "TRUE", DONT_TOUCH = "TRUE" *) reg [13:0] input_sync_1 = 0;
    (* ASYNC_REG = "TRUE", DONT_TOUCH = "TRUE" *) reg [13:0] input_sync_2 = 0;
    always @(posedge clk) begin
        input_sync_1 <= input_sample;
        input_sync_2 <= input_sync_1;
    end

    // Fixed, reviewed PCB-safe static states. No clock toggles are generated.
    OBUF  fpga_tx_output      (.I(1'b1), .O(fpga_tx));
    OBUF  scan_cc_output      (.I(1'b0), .O(scan_cc));
    OBUF  scan_se_output      (.I(1'b0), .O(scan_se));
    OBUF  scan_tm_output      (.I(1'b0), .O(scan_tm));
    OBUF  aq1_sck_output      (.I(1'b0), .O(aq1_sck));
    OBUF  aq1_mosi_output     (.I(1'b0), .O(aq1_mosi));
    OBUF  fpga_sck_output     (.I(1'b0), .O(fpga_sck));
    OBUF  fpga_sdata_output   (.I(1'b0), .O(fpga_sdata));
    OBUF  adc_pd_output       (.I(1'b0), .O(adc_pd));
    OBUF  fpga_loe_output     (.I(1'b0), .O(fpga_loe));
    OBUF  aq1_ncs_output      (.I(1'b1), .O(aq1_ncs));
    OBUF  aq1_nldac_output    (.I(1'b1), .O(aq1_nldac));
    OBUF  fpga_ncs_output     (.I(1'b1), .O(fpga_ncs));
    OBUF  fpga_nadcrst_output (.I(1'b0), .O(fpga_nadcrst));
    OBUF  aq1_nrst_output     (.I(1'b0), .O(aq1_nrst));
endmodule
