`timescale 1ns/1ps

module tb_ads5282_control;
    reg clk = 0;
    reg run_enable = 0;
    wire adc_clock_enable;
    wire adc_reset_n;
    wire spi_sclk;
    wire spi_sdata;
    wire spi_ncs;
    wire config_done;
    wire [2:0] sequence_index;
    wire [3:0] state_debug;

    always #2.5 clk = ~clk;

    ads5282_control #(
        .RESET_HIGH_CYCLES(4),
        .RESET_LOW_CYCLES(4),
        .RESET_RELEASE_CYCLES(6),
        .PRE_CLOCK_WAIT_CYCLES(8),
        .POST_CLOCK_WAIT_CYCLES(6),
        .SPI_HALF_CYCLES(4)
    ) dut (
        .clk(clk), .run_enable(run_enable),
        .adc_clock_enable(adc_clock_enable), .adc_reset_n(adc_reset_n),
        .spi_sclk(spi_sclk), .spi_sdata(spi_sdata), .spi_ncs(spi_ncs),
        .config_done(config_done), .sequence_index(sequence_index),
        .state_debug(state_debug)
    );

    reg [23:0] captured = 0;
    integer captured_bits = 0;
    integer frame = 0;
    integer errors = 0;
    reg [23:0] expected [0:6];

    initial begin
        expected[0] = 24'h03_0002;
        expected[1] = 24'h01_0010;
        expected[2] = 24'hE3_0060;
        expected[3] = 24'hC7_8001;
        expected[4] = 24'hDE_01C0;
        expected[5] = 24'h42_8001;
        expected[6] = 24'h25_0000;

        repeat (12) @(posedge clk);
        if (adc_clock_enable !== 0 || adc_reset_n !== 0 ||
            spi_sclk !== 0 || spi_sdata !== 0 || spi_ncs !== 1) begin
            $display("ERROR: unsafe disabled state");
            errors = errors + 1;
        end

        run_enable = 1;
        wait (config_done === 1'b1);
        repeat (4) @(posedge clk);
        if (frame != 7) begin
            $display("ERROR: expected 7 SPI frames, got %0d", frame);
            errors = errors + 1;
        end
        if (!adc_clock_enable || !adc_reset_n || !spi_ncs || spi_sclk) begin
            $display("ERROR: bad configured idle state");
            errors = errors + 1;
        end

        run_enable = 0;
        repeat (2) @(posedge clk);
        if (adc_clock_enable !== 0 || adc_reset_n !== 0 ||
            spi_sclk !== 0 || spi_sdata !== 0 || spi_ncs !== 1) begin
            $display("ERROR: unsafe state after VIO stop");
            errors = errors + 1;
        end

        if (errors == 0) $display("TB_PASS: safe gating and normal-data ADS5282 writes verified");
        else $display("TB_FAIL: %0d errors", errors);
        $finish;
    end

    // ADS5282 latches A7 first on each rising SCLK edge while nCS is low.
    always @(posedge spi_sclk) begin
        if (!spi_ncs) begin
            captured = {captured[22:0], spi_sdata};
            captured_bits = captured_bits + 1;
            if (captured_bits == 24) begin
                if (frame > 6 || captured !== expected[frame]) begin
                    $display("ERROR: frame %0d got %06h expected %06h",
                             frame, captured, expected[frame]);
                    errors = errors + 1;
                end
                frame = frame + 1;
                captured_bits = 0;
                captured = 0;
            end
        end
    end

    initial begin
        #1000000;
        $display("ERROR: timeout");
        $finish;
    end
endmodule
