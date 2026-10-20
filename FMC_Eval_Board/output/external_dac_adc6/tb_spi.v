`timescale 1ns/1ps
module tb_spi;
 reg clk=0; always #10 clk=~clk;
 reg [63:0] cmd=0;
 reg sdo=0;
 wire [63:0] status;
 wire sclk,sdi,ncs;
 dac_spi_service dut(clk,cmd,sdo,status,sclk,sdi,ncs);
 reg [23:0] received=0;
 integer n=0, frames=0;
 time last_rise=0;
 always @(negedge ncs) begin n=0; received=0; end
 always @(posedge sclk) begin
   last_rise=$time;
   sdo=(24'hA5C39E >> (23-n)) & 1;
 end
 always @(negedge sclk) if(!ncs) begin
   if($time-last_rise < 1000) $fatal(1,"SPI setup/half-period too short");
   received={received[22:0],sdi}; n=n+1;
 end
 always @(posedge ncs) if(n>0) begin
   if(n!=24) $fatal(1,"Bad frame length");
   if(received !== 24'h182CCD && received !== 24'h1E4000) $fatal(1,"Wrong frame");
   frames=frames+1;
 end
 initial begin
   #10000;
   if(frames!=0 || ncs!==1 || sclk!==0) $fatal(1,"Unexpected automatic transaction");
   cmd=64'h0100000000182CCD;
   wait(status[39:32]==1); #100;
   if(status[40] || status[23:0]!==24'hA5C39E || frames!=1) $fatal(1,"Transfer/readback failed");
   #10000; if(frames!=1) $fatal(1,"Duplicate token replayed");
   cmd=64'h02000000001E4000;
   wait(status[39:32]==2); #100;
   if(status[40] || status[23:0]!==24'hA5C39E || frames!=2) $fatal(1,"Second transfer failed");
   $display("EXTERNAL_DAC_SPI_SIM_PASS"); $finish;
 end
 initial begin #1000000; $fatal(1,"Timeout"); end
endmodule
