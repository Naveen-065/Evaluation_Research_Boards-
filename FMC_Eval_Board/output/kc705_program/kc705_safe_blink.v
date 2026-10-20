`timescale 1ns / 1ps

// KC705 JTAG/clock/LED smoke test.
// No FMC ports are instantiated; every unused package pin remains unused.
module kc705_safe_blink (
    input  wire SYSCLK_P,
    input  wire SYSCLK_N,
    output wire GPIO_LED_0_LS
);
    wire sysclk_200mhz;
    reg [27:0] divider = 28'd0;

    IBUFDS sysclk_buffer (
        .I  (SYSCLK_P),
        .IB (SYSCLK_N),
        .O  (sysclk_200mhz)
    );

    always @(posedge sysclk_200mhz)
        divider <= divider + 1'b1;

    // About 0.75 Hz full-cycle blink from the 200 MHz oscillator.
    assign GPIO_LED_0_LS = divider[27];
endmodule
