`timescale 1ns/1ps
module tb_scan_read;
reg clk=0, fb=0, ready=0, healthy=1, sv=0, clock_on=1, ready_allowed=1; reg[63:0] cmd=0;
wire enabled, resetlow,tm,se,si; wire[255:0] r0,r1;
reg[59:0] samples=0; integer n=0, captures=0, errors=0; reg [15:0] shifted=0; reg prev_se=1;
always #2.5 clk=~clk;
always #250 if(clock_on) fb=~fb;
scan_read_engine #(.RESET_CYCLES(8),.POST_CYCLES(8),.HOLD_CYCLES(24),.WATCHDOG_CYCLES(100000)) dut(
 .clk(clk),.feedback_clk(fb),.ready_i(ready),.reset_i(!resetlow),.dac_ready(1'b1),.adc_healthy(healthy),
 .command(cmd),.sample_valid(sv),.samples(samples),.interface_enable(enabled),.reset_low(resetlow),
 .tm(tm),.se(se),.si(si),.result0(r0),.result1(r1));
function[11:0] rev;input[11:0]v;integer k;begin for(k=0;k<12;k=k+1)rev[k]=v[11-k];end endfunction
always @(posedge clk) begin
 n<=n+1; sv <= n%20==0;
 if(resetlow || !ready_allowed) ready<=0; else ready<=1;
 samples <= {rev(12'd2400),rev(12'd2300),rev(12'd2200),rev(12'd2100),rev(tm&&se?12'd2150:12'd2050)};
end
always @(posedge fb) begin
 if(tm && !se) begin
   if(captures>=1 && captures<=16) shifted[captures-1]=si;
   if((captures==0||captures==17)&&si!==0) $fatal(1,"padding bit");
   captures=captures+1;
 end
end
initial begin
 #2000; if(enabled || tm || resetlow) $fatal(1,"startup not idle");
 cmd=64'h4000000000000000; #3000;
 cmd=64'hE000000000000000 | (5<<5) | 3;
 wait(r0[9]); #100;
 if(r0[10]) $fatal(1,"unexpected fault %h",r0);
 if(captures!=18 || shifted!=16'h0CA3) $fatal(1,"scan packet/count %h %d",shifted,captures);
 if(r0[31:16]!=16'h0CA3) $fatal(1,"status packet");
 if(r0[79:64]<20 || r0[95:80]<90) $fatal(1,"missing ADC samples");
 if(r0[127:96]/r0[79:64]!=2050) $fatal(1,"baseline accumulation");
 if(r1[31:0]/r0[95:80]<2140) $fatal(1,"active accumulation");
 if(tm || resetlow) $fatal(1,"read did not finish");
 healthy=0; cmd=64'h6000000000000000; #1000;
 if(!r0[10] || r0[14:11]!=1 || tm) $fatal(1,"ADC loss did not abort");
 cmd=0; #100;
 if(enabled || tm || resetlow) $fatal(1,"disable did not release");
 healthy=1; cmd=64'h4000000000000000; #1000;
 cmd=64'hE000000000000000; wait(r0[8]); clock_on=0;
 wait(r0[9]); #100;
 if(!r0[10] || r0[14:11]!=2 || tm || resetlow) $fatal(1,"clock loss did not abort");
 cmd=0; clock_on=1; ready_allowed=0; #20000;
 cmd=64'h4000000000000000; #1000; cmd=64'hE000000000000000;
 wait(r0[9]); #100;
 if(!r0[10] || r0[14:11]!=3 || tm || resetlow) $fatal(1,"missing READY did not time out");
 $display("SCAN_READ_TEST_PASS: LSB-first 18 cycles, OP_SET=0, bounded hold, ADC sums, ADC/clock/READY fault aborts, idle isolation");
 $finish;
end
initial begin #2000000; $fatal(1,"simulation timed out"); end
endmodule
