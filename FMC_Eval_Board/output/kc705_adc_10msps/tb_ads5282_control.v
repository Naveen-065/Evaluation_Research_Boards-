`timescale 1ns/1ps
module tb_ads5282_control;
    reg clk=0, run_enable=0;
    wire adc_clock_enable, adc_reset_n, spi_sclk, spi_sdata, spi_ncs, config_done;
    wire [2:0] sequence_index;
    wire [3:0] state_debug;
    ads5282_control dut (.*);
    always #2.5 clk=~clk;
    reg [23:0] rx=0;
    reg [15:0] regs[0:255];
    integer bits=0, frames=0, i;
    realtime data_change=0, last_rise=0, last_frame=0, clock_started=0;
    realtime reset_fell=0, reset_rose=0;
    initial for(i=0;i<256;i=i+1) regs[i]=0;
    always @(spi_sdata) data_change=$realtime;
    always @(negedge adc_reset_n) reset_fell=$realtime;
    always @(posedge adc_reset_n) begin
        if ($realtime-reset_fell < 100) $fatal(1,"Reset pulse too short");
        reset_rose=$realtime;
    end
    always @(negedge spi_ncs) begin rx=0; bits=0; last_rise=0; end
    always @(posedge spi_sclk) if(!spi_ncs) begin
        if (!adc_reset_n || adc_clock_enable) $fatal(1,"SPI must run after reset, before sample clock");
        if ($realtime-data_change < 5) $fatal(1,"SDATA setup too short");
        if (last_rise && $realtime-last_rise < 500) $fatal(1,"SPI exceeds 2 MHz");
        last_rise=$realtime;
        rx={rx[22:0],spi_sdata}; bits=bits+1;
    end
    always @(posedge spi_ncs) if(bits) begin
        if(bits!=24) $fatal(1,"SPI frame is not 24 bits");
        if(frames==0 && rx!=24'h124333) $fatal(1,"Internal termination not configured first");
        regs[rx[23:16]]=rx[15:0];
        $display("ADC_SPI_WRITE address=%02h data=%04h",rx[23:16],rx[15:0]);
        frames=frames+1; bits=0; last_frame=$realtime;
    end
    always @(posedge adc_clock_enable) begin
        if(frames!=8 || regs[8'h12]!=16'h4333 || regs[8'hE3]!=16'h0060 ||
           regs[8'h42]!=16'h8001 || regs[8'h25]!=0 ||
           regs[8'h03]!=2 || regs[8'h01]!=16'h10 ||
           regs[8'hC7]!=16'h8001 || regs[8'hDE]!=16'h01C0)
            $fatal(1,"Wrong ADC configuration at clock start");
        if($realtime-last_frame<10000000) $fatal(1,"Less than 10 ms after register writes");
        clock_started=$realtime;
    end
    initial begin
        #1000;
        if(adc_clock_enable || adc_reset_n || spi_sclk || !spi_ncs || config_done)
            $fatal(1,"Unsafe disabled state");
        run_enable=1;
        wait(config_done); #10;
        if($realtime-clock_started<100000 || sequence_index!=7 || state_debug!=11)
            $fatal(1,"ADC declared ready too soon or wrong final state");
        run_enable=0; #20;
        if(adc_clock_enable || adc_reset_n || spi_sclk || !spi_ncs || config_done)
            $fatal(1,"Stop did not restore idle state");
        $display("ADS5282_10MSPS_INTERNAL94_SIM_PASS");
        $finish;
    end
    initial begin #15000000; $fatal(1,"Simulation timeout"); end
endmodule
