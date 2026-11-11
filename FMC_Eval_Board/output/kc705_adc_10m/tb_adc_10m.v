`timescale 1ns/1ps
module tb_adc_10m;
    reg clk=0, run_enable=0;
    wire adc_clock_enable,adc_reset_n,spi_sclk,spi_sdata,spi_ncs,config_done;
    wire [2:0] sequence_index;
    wire [3:0] state_debug;
    ads5282_control dut(.*);
    always #2.5 clk=~clk;
    reg [23:0] expected[0:7];
    reg [23:0] rx=0;
    integer bits=0,frames=0;
    realtime reset_fell=0, reset_rose=0, final_write=0, clock_started=0;
    realtime data_changed=0, previous_rise=0;
    initial begin
        expected[0]=24'h124333;
        expected[1]=24'h030002;
        expected[2]=24'h010010;
        expected[3]=24'hC78001;
        expected[4]=24'hDE01C0;
        expected[5]=24'hE30060;
        expected[6]=24'h428001;
        expected[7]=24'h250000;
        #30;
        if(adc_clock_enable || adc_reset_n || spi_sclk || spi_sdata || !spi_ncs || config_done)
            $fatal(1,"Wrong disabled state");
        run_enable=1;
        wait(config_done); #20;
        if(frames!=8 || sequence_index!=7 || state_debug!=11 || !adc_clock_enable || !adc_reset_n || !spi_ncs || spi_sclk)
            $fatal(1,"Wrong configured state");
        if($realtime-clock_started < 100000) $fatal(1,"Clock settling less than 100 us");
        run_enable=0; #20;
        if(adc_clock_enable || adc_reset_n || config_done || !spi_ncs || spi_sclk)
            $fatal(1,"Stop did not stop clock and assert reset");
        $display("ADC_10MSPS_INTERNAL94_SPI_AND_TIMING_PASS"); $finish;
    end
    always @(negedge adc_reset_n) reset_fell=$realtime;
    always @(posedge adc_reset_n) if(reset_fell) begin
        if($realtime-reset_fell < 100) $fatal(1,"Reset low shorter than 100 ns");
        reset_rose=$realtime;
    end
    always @(spi_sdata) data_changed=$realtime;
    always @(negedge spi_ncs) begin
        if(adc_clock_enable) $fatal(1,"Sample clock started before SPI complete");
        if(!reset_rose || $realtime-reset_rose < 1000000) $fatal(1,"SPI before reset recovery");
        bits=0; rx=0; previous_rise=0;
    end
    always @(posedge spi_sclk) if(!spi_ncs) begin
        if($realtime-data_changed<250) $fatal(1,"Insufficient SPI data setup");
        if(previous_rise && $realtime-previous_rise<500) $fatal(1,"SPI faster than 2 MHz");
        previous_rise=$realtime; rx={rx[22:0],spi_sdata}; bits=bits+1;
    end
    always @(posedge spi_ncs) if(run_enable && bits) begin
        if(bits!=24 || frames>7 || rx!==expected[frames]) $fatal(1,"Bad SPI frame %0d: %06h",frames,rx);
        $display("ADC_SPI_FRAME_%0d=%06h",frames,rx);
        frames=frames+1; bits=0;
        if(frames==8) final_write=$realtime;
    end
    always @(posedge adc_clock_enable) begin
        if(frames!=8 || !final_write || $realtime-final_write<10000000)
            $fatal(1,"Sample clock enabled before configuration/10 ms wait");
        clock_started=$realtime;
    end
    initial begin #15000000; $fatal(1,"Timeout"); end
endmodule
