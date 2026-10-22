`timescale 1ns/1ps

// Carrier-only probe used before the FMC image is loaded. No VADJ-powered bank
// or FMC connector signal exists in this design.
module zcu106_vadj_check (
    input wire sysclk_p,
    input wire sysclk_n,
    inout wire iic_scl_pmbus,
    inout wire iic_sda_pmbus
);
    wire clk300;
    wire clk200_unbuffered;
    wire clk200;
    wire feedback_unbuffered;
    wire feedback;
    wire unused_clk10;
    wire unused_locked;
    IBUFDS clock_input (.I(sysclk_p), .IB(sysclk_n), .O(clk300));
    PLLE4_BASE #(
        .CLKFBOUT_MULT(10), .CLKIN_PERIOD(3.333),
        .CLKOUT0_DIVIDE(5), .CLKOUT1_DIVIDE(100),
        .DIVCLK_DIVIDE(3), .STARTUP_WAIT("FALSE")
    ) clock_pll (
        .CLKIN(clk300), .CLKFBIN(feedback), .RST(1'b0), .PWRDWN(1'b0),
        .CLKOUTPHYEN(1'b0), .CLKFBOUT(feedback_unbuffered),
        .CLKOUT0(clk200_unbuffered), .CLKOUT1(unused_clk10),
        .LOCKED(unused_locked)
    );
    BUFG feedback_buffer (.I(feedback_unbuffered), .O(feedback));
    BUFG system_clock_buffer (.I(clk200_unbuffered), .O(clk200));

    wire [127:0] command;
    wire [127:0] status;
    reg [4:0] por_count = 0;
    always @(posedge clk200)
        if (!por_count[4]) por_count <= por_count + 1'b1;
    vadj_check_vio u_i2c_vio (
        .clk(clk200), .probe_out0(command), .probe_in0(status)
    );
    i2c_transaction_bridge bridge (
        .clk(clk200), .reset(!por_count[4]),
        .command(command), .status(status),
        .scl(iic_scl_pmbus), .sda(iic_sda_pmbus)
    );
endmodule

