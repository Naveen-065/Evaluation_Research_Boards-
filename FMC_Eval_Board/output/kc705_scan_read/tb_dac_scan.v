`timescale 1ns/1ps
// Behavioral SPI receiver: checks actual wire traffic, voltage conversion,
// reference/supply sequencing, inactive channels and reset/restart behavior.
module tb_dac81416_pcb_scan;
    reg clk = 0, enable = 0;
    wire sclk, sdata, ncs, nldac, reset_n, ready;
    wire [4:0] frame_index;
    wire [2:0] state_debug;
    dac81416_pcb_scan_control dut (.*);
    always #2.5 clk = ~clk;
    reg [23:0] rx = 0;
    integer bits = 0, frames = 0, channel, i;
    reg [15:0] regs [0:31];
    reg [15:0] written = 0;
    realtime reset_fell = 0, reset_rose = 0, ref_on = 0, supplies_on = 0;
    realtime rise_time = 0, last_data_change = 0, last_cs_rise = 0;
    real volts;

    task fail(input [511:0] why);
        $display("FAIL %0t: %0s", $time, why);
        $fatal(1);
    endtask
    task model_reset;
        begin
            for (i=0; i<32; i=i+1) regs[i]=0;
            regs[4]=16'h7F00;
            regs[9]=16'hFFFF;
            written=0; bits=0; frames=0; rx=0;
            ref_on=0; supplies_on=0; last_cs_rise=0;
        end
    endtask
    initial model_reset();
    always @(negedge reset_n) begin
        reset_fell=$realtime;
        model_reset();
    end
    always @(posedge reset_n) begin
        if ($realtime-reset_fell < 500) fail("RESET low shorter than 500 ns");
        reset_rose=$realtime;
    end
    always @(sdata) last_data_change=$realtime;
    always @(posedge sclk) rise_time=$realtime;
    always @(negedge ncs) if (reset_n && enable) begin
        if ($realtime-reset_rose < 1000000) fail("SPI before 1 ms POR recovery");
        if (last_cs_rise && $realtime-last_cs_rise < 5000) fail("Short interframe gap");
        bits=0; rx=0;
    end
    always @(negedge sclk) if (!ncs && reset_n && enable) begin
        if ($realtime-rise_time < 250) fail("SCLK high shorter than 250 ns");
        if ($realtime-last_data_change < 250) fail("SDI setup shorter than 250 ns");
        rx={rx[22:0],sdata}; bits=bits+1;
    end
    always @(posedge ncs) if (reset_n && enable && bits) begin
        if (bits != 24) fail("Frame must contain exactly 24 falling edges");
        if (rx[23:16] > 31) fail("Unexpected register address");
        if (rx[23:16] >= 16) written[rx[19:16]]=1;
        if (rx[23:16] == 4 && !rx[14]) ref_on=$realtime;
        if (rx[23:16] == 9 && rx[15:0] != 16'hFFFF) begin
            if (!ref_on || $realtime-ref_on < 1000000) fail("Reference not settled");
            if (regs[10] || regs[11] || regs[12] || regs[13]) fail("Wrong output spans");
            if (rx[15:0] == 16'h3FDF) begin
                if (regs[31] != 16'h5C29 || regs[21] != 16'h75C3 || regs[30] != 16'h999A)
                    fail("Wrong VCCD2/VDDA2 supply codes");
                supplies_on=$realtime;
            end else if (rx[15:0] == 16'h01D0) begin
                if (!supplies_on || $realtime-supplies_on < 10000000)
                    fail("Supply startup delay shorter than 10 ms");
                if ((written & ~rx[15:0]) != ~rx[15:0])
                    fail("Enabled output before loading its code");
            end else fail("Unexpected power mask");
        end
        regs[rx[23:16]]=rx[15:0];
        frames=frames+1; bits=0; last_cs_rise=$realtime;
    end
    task check_voltage(input integer ch, input real target);
        begin
            volts=5.0 * regs[16+ch] / 65536.0;
            if (regs[9][ch] || volts < target-0.00004 || volts > target+0.00004)
                fail("Wrong enabled-channel voltage");
            $display("DAC%0d = %.6f V (decoded SPI model)", ch, volts);
        end
    endtask
    initial begin
        #50;
        if (reset_n || ready || !ncs || sclk || sdata || !nldac) fail("Unsafe initial state");
        enable=1;
        // Interrupt an in-flight frame; resetting must discard partial SPI data.
        wait (!ncs); repeat(5) @(negedge sclk);
        @(negedge clk); enable=0;
        #1000;
        if (reset_n || ready || !ncs || sclk || sdata || frame_index) fail("Disable failed");
        enable=1;
        wait(ready); #100;
        if (frames != 22 || frame_index != 21 || !reset_n || !ncs || sclk || !nldac)
            fail("Incomplete initialization");
        if (regs[9] != 16'h01D0 || regs[4][14]) fail("Power or reference config wrong");
        if ((written & 16'h01C0) != 0) fail("Wrote unused DAC6/7/8/14");
        check_voltage(0,0.5); check_voltage(1,2.5); check_voltage(2,0.5);
        check_voltage(3,2.5); check_voltage(5,2.3); check_voltage(9,0.9);
        check_voltage(10,0.9); check_voltage(11,0.6); check_voltage(12,1.6);
        check_voltage(13,1.0); check_voltage(14,3.0); check_voltage(15,1.8);
        #100000;
        if (frames != 22) fail("SPI continued after ready");
        enable=0; #20;
        if (reset_n || ready || !ncs || sclk || sdata || frame_index) fail("Final disable failed");
        $display("DAC81416_PCB_SCAN_SIM_PASS");
        $finish;
    end
    initial begin #25000000; fail("Simulation timeout"); end
endmodule

