`timescale 1ns/1ps
module tb_control;
 reg clk=0,fb=0,ready=0,ready_auto=1,rx=1,healthy=1,valid=0;
 reg [63:0] cmd=0;
 wire en,rst,tm,se,si,sz,siz,ds,dd,db,sc,sd,cs;
 wire [23:0] df;
 wire [255:0] r0,r1;
 always #2.5 clk=~clk;
 always #25 fb=~fb;
 wire [59:0] adc_samples=(tm&&se) ? {5{12'h011}} : {5{12'h001}};
 cell_control_engine #(.RESET_SYS(100),.POST_CYCLES(128),.READY_FALLBACK_CYCLES(40),
  .WATCHDOG_CYCLES(2000000),.DAC_SETTLE_CYCLES(20),
  .WB_ZERO(30),.WB_ONE(90),.WB_HIGH(50),.WB_END(50)) dut(
  .clk(clk),.feedback_clk(fb),.ready_i(ready),.reset_i(!rst),.uart_rx(rx),
  .dac_ready(1'b1),.adc_healthy(healthy),.command(cmd),.sample_valid(valid),
  .samples(adc_samples),.interface_enable(en),.reset_low(rst),.tm(tm),.se(se),.si(si),
  .scan_tristate(sz),.si_tristate(siz),.dac_start(ds),.dac_frame(df),.dac_done(dd),
  .result0(r0),.result1(r1));
 runtime_dac_spi #(.HALF(6),.GAP(10)) spi(.clk(clk),.enable(en),.start(ds),.data(df),
  .busy(db),.done(dd),.sclk(sc),.sdata(sd),.ncs(cs));
 integer count=0,frames=0,shiftbits=0,reset_edges=0;
 reg [23:0] received=0;
 reg [15:0] scan_packet=0;
 always @(negedge sc) if(!cs) begin received={received[22:0],sd}; count=count+1; end
 always @(posedge cs) if(en) begin
  if(count!=24 || received!=df) $fatal(1,"SPI frame %h expected %h / edges %d",received,df,count);
  count=0; frames=frames+1;
 end
 always @(posedge fb) begin
  if(tm&&!se) begin
   if(shiftbits>=1 && shiftbits<=16) scan_packet[shiftbits-1]=si;
   shiftbits=shiftbits+1;
  end
  valid<=!valid;
 end
 always @(posedge rst) begin ready<=0; reset_edges=reset_edges+1; end
 // Board-level prerequisite: TXS0108E pull-ups make a floating SE high,
 // which disables the Caravel functional WB FSM despite correct UART traffic.
always @(negedge clk) if(en && dut.core.wb_mode && (sz || se || tm))
  $fatal(1,"WB must actively hold SE and TM low");
 always @(negedge rst) if(ready_auto) begin repeat(12) @(posedge clk); ready<=1; end
 task command;
  input [3:0] op; input [57:0] payload;
  begin @(negedge clk); cmd={~cmd[63],1'b1,op,payload}; repeat(6) @(posedge clk); end
 endtask
 task completed;
  integer t;
  begin
   t=0;
   while(!(r0[15]==cmd[63] && r0[9] && !r0[8])) begin
    @(posedge clk); t=t+1; if(t>1500000) $fatal(1,"timeout state=%d fault=%d",r0[7:0],r0[14:11]);
   end
   repeat(3) @(posedge clk);
  end
 endtask
 task byte_tx;
  input [7:0] b; integer k;
  begin rx=0; repeat(100) @(negedge clk);
   for(k=0;k<8;k=k+1) begin rx=b[k]; repeat(100) @(negedge clk); end
   rx=1; repeat(100) @(negedge clk);
  end
 endtask
 task frame_tx;
  input [7:0] tag; input [31:0] value;
  begin
   byte_tx(8'hA5); byte_tx(8'h5A); byte_tx(tag);
   byte_tx(value[31:24]); byte_tx(value[23:16]); byte_tx(value[15:8]); byte_tx(value[7:0]);
   byte_tx(tag^value[31:24]^value[23:16]^value[15:8]^value[7:0]);
  end
 endtask
 integer k,wb_bits=0;
 reg [63:0] captured=0;
 time start_low;
always @(negedge si) if(dut.core.wb_mode && dut.core.state==13) begin
  start_low=$time; ready<=~ready;
 end
always @(posedge si) if(dut.core.wb_mode && dut.core.state==14) begin
  captured={captured[62:0],(($time-start_low)>3000)}; wb_bits=wb_bits+1;
 end
 initial begin
  #100;
  if(dut.ramp_vcc_code(1'b0,1'b0,7'd95)!=16'd39321)
   $fatal(1,"RESET 3.000-V ramp code must match the hard host cap");
  if(dut.ramp_vcc_code(1'b0,1'b1,7'd1)!=16'd36700 ||
     dut.ramp_wl_code(1'b0,1'b1,7'd1)!=16'd23986 ||
     dut.ramp_wl_code(1'b1,1'b1,7'd2)!=16'd22938)
   $fatal(1,"Measured three-point ramp codes are incorrect");
  command(4,0); completed();
  command(2,24'h12999A); completed();
  if(r0[10] || frames!=1) $fatal(1,"allowed DAC failed");
  command(2,24'h1E0000); completed();
  if(!r0[10] || frames!=1) $fatal(1,"supply protection failed");
  command(2,24'h0901CC); completed();
  if(r0[10] || frames!=2 || received!=24'h0901CC)
   $fatal(1,"WB physical VCC_SET shutdown mask failed");
  command(2,24'h09FFFF); completed();
  if(!r0[10] || frames!=2) $fatal(1,"supply power-down mask protection failed");
  command(2,24'h0901D0); completed();
  if(r0[10] || frames!=3) $fatal(1,"scan power restoration mask failed");
  command(4,58'd1<<57); completed();
  if(sz || se || tm || !rst) $fatal(1,"WB hold pin ownership failed");
  command(2,24'h12999A); completed();
  if(sz || se || tm || frames!=4) $fatal(1,"WB DAC setup released SE/TM");
  command(4,0); completed();
  if(sz || !se || tm || !rst) $fatal(1,"scan hold restoration failed");
  command(1,(58'd1<<57)|(58'd40<<10)|(58'd9<<5)|58'd3); completed();
  if(r0[10] || scan_packet!={1'b1,5'd3,5'd9,5'd3} || shiftbits!=18)
   $fatal(1,"scan packet %h shifts%d status%h",scan_packet,shiftbits,r0[63:0]);
  if(r0[79:64]==0 || r0[95:80]==0) $fatal(1,"missing samples");
  // Packets may not be streamed continuously: assert reset again, then use
  // the same bounded READY fallback as the proven Kintex implementation.
  ready_auto=0; ready=0; shiftbits=0; scan_packet=0;
  command(1,(58'd40<<10)|(58'd7<<5)|58'd2); completed();
  if(r0[10] || !r0[45] || scan_packet!={1'b0,5'd2,5'd7,5'd2} || shiftbits!=18)
   $fatal(1,"reset-per-packet READY fallback failed packet=%h shifts=%d status=%h",scan_packet,shiftbits,r0[63:0]);
  ready_auto=1;
  // A compound SET step must issue mask/VCC/WL and two read-restore frames,
  // run both the programming and read scans, and return the READ packet.
  k=frames;
  command(8,(58'd1<<57)|(58'h7000<<41)|(58'h3000<<25)|(58'd40<<10)|(58'd5<<5)|58'd4);
  completed();
  if(r0[10] || frames!=k+5 || received!=24'h138000 || r0[31:16]!={1'b0,5'd4,5'd5,5'd4} || dut.core.program_active)
   $fatal(1,"compound PROGRAM_STEP failed frames=%d last=%h status=%h",frames-k,received,r0[63:0]);
  // RESET uses that same proven DAC2/DAC3 path, with OP_SET low.
  k=frames;
  command(8,(58'h7000<<41)|(58'h3000<<25)|(58'd40<<10)|(58'd24<<5)|58'd3);
  completed();
  if(r0[10] || frames!=k+5 || received!=24'h138000 ||
     r0[31:16]!={1'b0,5'd3,5'd24,5'd3} || dut.core.program_active)
   $fatal(1,"compound RESET set-rail path failed frames=%d last=%h status=%h",frames-k,received,r0[63:0]);
  // One external fast PROGRAM_RAMP command must execute a SET step and all ten
  // confirmation reads internally.  Only one selected cell is ever scanned.
  k=frames; shiftbits=0; scan_packet=0;
  command(11,(58'd1<<57)|(58'h8000<<41)|(58'h8000<<25)|(58'd40<<10)|(58'd5<<5)|58'd4);
  completed();
  if(r0[10] || r1[223:216]!=1 || !r1[215] || r1[206:203]!=10 || frames!=k+5)
   $fatal(1,"fabric fast PROGRAM_RAMP SET failed frames=%d status=%h/%h",frames-k,r0,r1);
  command(10,0); completed(); repeat(10) @(posedge clk);
  if(r1[255:224]!=32'h524D5032 || r0[23:16]!=1 || !r0[24] || $signed(r0[47:32])<=0)
   $fatal(1,"PROGRAM_RAMP trace page failed %h/%h",r0,r1);
  command(6,0); completed(); repeat(10) @(posedge clk);
  if(r1[255:224]!=32'h54524332 || r1[200:192]<3 ||
     r1[11:0]!=2048 || r1[63:56]!=3 || r1[55:36]!=0)
   $fatal(1,"measured trace header/first baseline point mismatch %h",r1);
  // The array scheduler performs an initial read plus ten confirmations for
  // each cell without any host command between cells.  The core underneath
  // still resets and waits READY for every one of those scan packets.
  k=reset_edges;
  command(12,(58'd1<<57)|(58'd1<<36)|(58'd40<<21)); completed();
  if(r0[10] || r1[255:224]!=32'h41525232 || r1[223:213]!=2 ||
     r1[212:202]!=0 || r1[160:151]!=1 || reset_edges!=k+22)
   $fatal(1,"two-cell fabric scheduler failed %h/%h",r0,r1);
  command(13,0); completed(); repeat(10) @(posedge clk);
  if(r1[255:224]!=32'h41524732 || !r0[58] || !r0[90] ||
     r0[57:48]!=0 || r0[89:80]!=0)
   $fatal(1,"array result page failed %h/%h",r0,r1);
  // count_minus_one=1023 must become 1024, not wrap to zero.  Abort before
  // the intentionally long test operation proceeds past its first packet.
  command(12,(58'd1<<56)|(58'd1023<<36)|(58'd40<<21)|(58'd2<<19));
  if(dut.array_remaining!=1024 || dut.array_set || !dut.array_reliable ||
     dut.array_retry_limit!=2)
   $fatal(1,"full reliable RESET scheduler configuration failed count=%d",dut.array_remaining);
  command(4,0); completed();
  if(!rst || tm) $fatal(1,"array scheduler abort not safe");
  // The MAC scan still selects only one row/cell.  Its signed input product
  // is accumulated inside the FPGA for the selected output column.
  command(7,58'd1<<57); completed();
  shiftbits=0; scan_packet=0;
  command(1,(58'd1<<56)|(58'd3<<48)|(58'd2400<<10)|(58'd9<<5)|58'd3); completed();
  if(scan_packet!={1'b0,5'd3,5'd9,5'd3} || shiftbits!=18)
   $fatal(1,"MAC scan selected more than the requested cell");
  command(7,58'd9); completed(); repeat(10) @(posedge clk);
  if(r1[255:224]!=32'h4D414332 || r1[60:56]!=9 || r1[95:64]!=48000 || $signed(r1[55:0])<=0)
   $fatal(1,"signed FPGA MAC accumulation failed %h",r1);
  command(7,58'd1<<57); completed(); repeat(10) @(posedge clk);
  if(r1[55:0]!=0) $fatal(1,"MAC accumulator clear failed %h",r1);
  command(3,(58'd128<<32)|58'h41F2AA82);
  wait(!rst); repeat(100) @(posedge clk); frame_tx(8'hF1,1);
  wait(siz);
  if(wb_bits!=64 || captured!=dut.core.wb_frame) $fatal(1,"WB frame mismatch %h %h bits%d",captured,dut.core.wb_frame,wb_bits);
  frame_tx(8'hF2,32'h41F2AA82);
  for(k=0;k<15;k=k+1) frame_tx(8'h80+k,32'h12340000+k);
  completed();
  if(r0[10] || r1[54:40]!=15'h7FFF || sz || se || tm || !siz) $fatal(1,"WB result failure");
  command(5,14); completed(); repeat(10) @(posedge clk);
  if(r1[31:0]!=32'h1234000E) $fatal(1,"WB result bank");
  command(1,58'd40<<10); healthy=0; completed();
  if(!r0[10] || !rst) $fatal(1,"ADC fault not contained");
  healthy=1; command(4,0); completed();
  if(!rst || tm) $fatal(1,"abort not safe");
  $display("PASS protected DAC and WB supply mask, serial scan, FPGA MAC, ADC trace, WB frame/UART, abort/fault");
  $finish;
 end
 initial begin #100000000; $fatal(1,"global timeout"); end
endmodule
