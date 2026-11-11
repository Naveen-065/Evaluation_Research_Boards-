`timescale 1ns/1ps
module tb_return_clock_monitor;
    reg clk = 0, enable = 0;
    reg lclk_source = 0, adclk_source = 0;
    reg lclk_on = 1, adclk_on = 1;
    realtime lclk_half = 8.333333, adclk_half = 50;
    wire lclk_async = lclk_on && lclk_source;
    wire adclk_async = adclk_on && adclk_source;
    wire window_valid, lclk_seen, adclk_seen, lclk_60m, adclk_10m;
    adc_return_clock_monitor dut(.*);
    always #2.5 clk = ~clk;
    always begin #(lclk_half); lclk_source = ~lclk_source; end
    always begin #(adclk_half); adclk_source = ~adclk_source; end
    task check_status(input [4:0] expected);
        begin
            if ({window_valid,lclk_seen,adclk_seen,lclk_60m,adclk_10m} !== expected)
                $fatal(1,"Unexpected counter result actual=%b expected=%b",{window_valid,lclk_seen,adclk_seen,lclk_60m,adclk_10m},expected);
        end
    endtask
    initial begin
        #100; check_status(5'b00000);
        enable = 1;
        #2100000; check_status(5'b11111);
        lclk_on = 0;
        #2100000; check_status(5'b10101);
        adclk_on = 0;
        #2100000; check_status(5'b10000);
        lclk_half = 16.666667; adclk_half = 100;
        lclk_on = 1; adclk_on = 1;
        #2100000; check_status(5'b11100);
        enable = 0;
        #50; check_status(5'b00000);
        $display("RETURN_CLOCK_MONITOR_NOMINAL_STOPPED_WRONG_FREQUENCY_PASS");
        $finish;
    end
endmodule
