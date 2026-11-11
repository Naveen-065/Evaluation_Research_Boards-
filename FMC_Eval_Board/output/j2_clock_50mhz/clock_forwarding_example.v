// Integration example only, not a complete or timing-closed KC705 design.
// clk_50 must be an actual clean, continuously running 50 MHz clock.
// enable_50 must be synchronized to clk_50 and asserted only after both boards'
// supplies, ADC configuration and all other interface safety conditions are valid.
module clock_forwarding_example(
    input wire clk_50,
    input wire enable_50,
    output wire adc_clk_p,
    output wire adc_clk_n_ref
);
    wire forwarded_clock;
    ODDR #(.DDR_CLK_EDGE("SAME_EDGE"), .INIT(1'b0), .SRTYPE("SYNC")) fwd (
        .Q(forwarded_clock), .C(clk_50), .CE(1'b1),
        .D1(1'b1), .D2(1'b0), .R(~enable_50), .S(1'b0)
    );
    OBUF p_buffer(.I(forwarded_clock), .O(adc_clk_p));
    // Deliberately an actively driven LOW output, not a floating input.
    OBUF n_reference_buffer(.I(1'b0), .O(adc_clk_n_ref));
endmodule
