`timescale 1ns/1ps

module tb_dac81416_shunt_control;
    reg clk = 1'b0;
    reg enable = 1'b0;
    wire sclk, sdata, ncs, nldac, reset_n, ready;
    wire [3:0] frame_index;
    wire [2:0] state_debug;

    reg [23:0] captured = 24'd0;
    integer captured_bits = 0;
    integer captured_frames = 0;
    integer errors = 0;

    reg [23:0] expected [0:10];
    initial begin
        expected[0] = 24'h09FFFF;
        expected[1] = 24'h0A0000;
        expected[2] = 24'h0B0000;
        expected[3] = 24'h0C0000;
        expected[4] = 24'h0D0000;
        expected[5] = 24'h030004;
        expected[6] = 24'h040000;
        expected[7] = 24'h10199A;
        expected[8] = 24'h12199A;
        expected[9] = 24'h158000;
        expected[10] = 24'h09FFDA;
    end

    always #2.5 clk = ~clk;

    dac81416_shunt_control #(
        .RESET_LOW_CYCLES(4),
        .RESET_RELEASE_CYCLES(10),
        .REFERENCE_SETTLE_CYCLES(12),
        .SPI_HALF_CYCLES(2),
        .INTERFRAME_CYCLES(3)
    ) dut (
        .clk(clk), .enable(enable), .sclk(sclk), .sdata(sdata), .ncs(ncs),
        .nldac(nldac), .reset_n(reset_n), .ready(ready),
        .frame_index(frame_index), .state_debug(state_debug)
    );

    // DAC81416 samples SDI on falling SCLK edges.
    always @(negedge sclk) begin
        if (!ncs) begin
            captured = {captured[22:0], sdata};
            captured_bits = captured_bits + 1;
        end
    end

    always @(posedge ncs) begin
        if (enable && captured_bits != 0) begin
            if (captured_bits != 24) begin
                $display("ERROR: frame %0d had %0d bits", captured_frames, captured_bits);
                errors = errors + 1;
            end else if (captured !== expected[captured_frames]) begin
                $display("ERROR: frame %0d got %06h expected %06h",
                         captured_frames, captured, expected[captured_frames]);
                errors = errors + 1;
            end
            captured_frames = captured_frames + 1;
            captured_bits = 0;
            captured = 24'd0;
        end
    end

    initial begin
        #20;
        if (sclk !== 0 || sdata !== 0 || ncs !== 1 || nldac !== 1 ||
            reset_n !== 0 || ready !== 0) begin
            $display("ERROR: disabled outputs are not safe");
            errors = errors + 1;
        end

        enable = 1'b1;
        wait (ready == 1'b1);
        #20;
        if (captured_frames != 11) begin
            $display("ERROR: captured %0d frames, expected 11", captured_frames);
            errors = errors + 1;
        end
        if (frame_index !== 4'd10 || sclk !== 0 || ncs !== 1 ||
            reset_n !== 1 || nldac !== 1) begin
            $display("ERROR: final DAC controller state is wrong");
            errors = errors + 1;
        end

        // Removing the VIO enable must immediately restore the reset-low,
        // chip-select-high, clock-low state and clear completion.
        enable = 1'b0;
        #10;
        if (sclk !== 0 || sdata !== 0 || ncs !== 1 || reset_n !== 0 ||
            ready !== 0 || frame_index !== 0) begin
            $display("ERROR: disable did not restore safe state");
            errors = errors + 1;
        end

        if (errors == 0)
            $display("DAC81416_SHUNT_CONTROL_SIM_PASS");
        else
            $fatal(1, "DAC81416_SHUNT_CONTROL_SIM_FAIL: %0d errors", errors);
        $finish;
    end

    initial begin
        #100000;
        $fatal(1, "DAC81416_SHUNT_CONTROL_SIM_TIMEOUT");
    end
endmodule
