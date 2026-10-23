`timescale 1ns/1ps

module tb_bitmap_scheduler;
 reg clk=0, fb=0, ready=0, rx=1, healthy=1, valid=0, dac_ok=0;
 reg [63:0] cmd=0;
 wire en, rst, tm, se, si, scan_z, si_z, dac_start, dac_done;
 wire [23:0] dac_frame;
 wire dac_busy, dac_sclk, dac_sdata, dac_ncs;
 wire [255:0] r0, r1;
 integer reset_edges=0;
 integer k;
 integer schedule_count=0;
 integer schedule_order[0:15];
 reg capture_schedule=0;
 reg last_inner_toggle=0;
 reg [31:0] expected_word;
 reg [31:0] page_word0, page_word1;

 always #2.5 clk=~clk;
 always #25 fb=~fb;

 // Model an already-correct mixed image: SET targets read high-current and
 // RESET targets read low-current.  This exercises skip/verify behavior for
 // both states without hiding the mandatory packet/reset cadence.
 wire [59:0] adc_samples=(tm&&se) ?
   ((dut.bitmap_mode && !dut.ramp_set) ? {5{12'h001}} : {5{12'h011}}) :
   {5{12'h001}};

 cell_control_engine #(
  .RESET_SYS(100), .POST_CYCLES(128), .READY_FALLBACK_CYCLES(40),
  .WATCHDOG_CYCLES(2000000), .DAC_SETTLE_CYCLES(20),
  .WB_ZERO(30), .WB_ONE(90), .WB_HIGH(50), .WB_END(50)
 ) dut (
  .clk(clk), .feedback_clk(fb), .ready_i(ready), .reset_i(!rst),
  .uart_rx(rx), .dac_ready(dac_ok), .adc_healthy(healthy), .command(cmd),
  .sample_valid(valid), .samples(adc_samples), .interface_enable(en),
  .reset_low(rst), .tm(tm), .se(se), .si(si),
  .scan_tristate(scan_z), .si_tristate(si_z),
  .dac_start(dac_start), .dac_frame(dac_frame), .dac_done(dac_done),
  .result0(r0), .result1(r1)
 );

 runtime_dac_spi #(.HALF(6), .GAP(10)) spi (
  .clk(clk), .enable(en), .start(dac_start), .data(dac_frame),
  .busy(dac_busy), .done(dac_done), .sclk(dac_sclk),
  .sdata(dac_sdata), .ncs(dac_ncs)
 );

 always @(posedge fb) valid<=!valid;
 // Capture only the initial read issued for each op15 cell.  Confirmation
 // reads use WR_ARRAY_CONFIRM and therefore do not enter this sequence.
 always @(posedge clk) begin
  if(dut.inner_command[63]!=last_inner_toggle) begin
   last_inner_toggle<=dut.inner_command[63];
   if(capture_schedule && dut.bitmap_mode && dut.wrapper_state==7 &&
      dut.inner_command[61:58]==1) begin
    schedule_order[schedule_count]={dut.inner_command[4:0],dut.inner_command[9:5]};
    schedule_count=schedule_count+1;
   end
  end
 end
 always @(posedge rst) begin
  ready<=0;
  reset_edges=reset_edges+1;
 end
 always @(negedge rst) begin
  repeat(12) @(posedge clk);
  ready<=1;
 end

 task command;
  input [3:0] op;
  input [57:0] payload;
  begin
   @(negedge clk);
   cmd={~cmd[63],1'b1,op,payload};
   repeat(6) @(posedge clk);
  end
 endtask

 task read_bitmap_word;
  input [4:0] index;
  input [31:0] data;
  begin
   command(14,(58'd1<<56)|({53'd0,index}<<51));
   completed();
   if(r0[10] || !r1[223] || !r1[216] ||
      r1[215:184]!=32'hFFFFFFFF || r1[183:152]!=data)
    $fatal(1,"bitmap stored readback failed index=%0d expected=%h result=%h/%h",index,data,r0,r1);
  end
 endtask

 task load_uniform_bitmap;
  input [31:0] data;
  integer word_index;
  begin
   for(word_index=0;word_index<32;word_index=word_index+1)
    load_bitmap_word(word_index[4:0],data,word_index==0);
   for(word_index=0;word_index<32;word_index=word_index+1)
    read_bitmap_word(word_index[4:0],data);
  end
 endtask

 task completed;
  integer timeout;
  begin
   timeout=0;
   while(!(r0[15]==cmd[63] && r0[9] && !r0[8])) begin
    @(posedge clk);
    timeout=timeout+1;
    if(timeout>10000000)
     $fatal(1,"timeout state=%0d fault=%0d result=%h/%h",r0[7:0],r0[14:11],r0,r1);
   end
   repeat(3) @(posedge clk);
  end
 endtask

 task load_bitmap_word;
  input [4:0] index;
  input [31:0] data;
  input clear_first;
  reg [57:0] payload;
  reg [31:0] expected_valid;
  begin
   payload=(clear_first ? (58'd1<<57) : 0) | ({53'd0,index}<<51) | data;
   command(14,payload);
   completed();
   expected_valid=clear_first ? (32'h1<<index) : ((32'h1<<(index+1))-1);
   if(r0[10] || r1[255:224]!=32'h424D5032 || r1[223] ||
      r1[221:217]!=index || r1[183:152]!=data ||
      r1[215:184]!=expected_valid)
    $fatal(1,"bitmap load/ack failed index=%0d result=%h/%h",index,r0,r1);
  end
 endtask

 initial begin
  #100;

  // Deployment leaves the DAC interlock deliberately disabled.  The op14
  // identity transaction is wrapper-local and must still complete while the
  // inner core/scan pad interface remains disabled.
  command(14,(58'd1<<56));
  completed();
  if(en || r0[10] || r1[255:224]!=32'h424D5032 || !r1[223])
   $fatal(1,"disabled-interlock BMP2 identity failed %h/%h",r0,r1);

  // Safety hold must be available before the DAC interlock is enabled. This
  // is the deployment path: op4 owns the digital pins, asserts RESET_B, and
  // cannot launch a DAC transaction or programming pulse.
  command(4,0);
  completed();
  if(!en || !rst || tm || !se || si || scan_z || si_z || dac_start ||
     r0[10] || !r0[32] || r0[7:0]!=9)
   $fatal(1,"disabled-interlock op4 hold failed %h/%h",r0,r1);

  // The same exception also covers the documented WB-pin ownership variant.
  command(4,(58'd1<<57));
  completed();
  if(!en || !rst || tm || se || !si || scan_z || si_z || dac_start ||
     r0[10] || !r0[32] || !r0[38] || r0[7:0]!=9)
   $fatal(1,"disabled-interlock WB op4 hold failed %h/%h",r0,r1);

  // Return to scan ownership before testing explicit interface release.
  command(4,0);
  completed();
  if(!en || !rst || tm || !se || si || r0[10] || r0[7:0]!=9)
   $fatal(1,"disabled-interlock scan op4 re-hold failed %h/%h",r0,r1);

  // command[62]=0 is the explicit release path used by host cleanup.
  @(negedge clk);
  cmd={cmd[63],1'b0,62'd0};
  repeat(6) @(posedge clk);
  if(en || !scan_z || !si_z || rst)
   $fatal(1,"disabled-interlock release failed %h/%h",r0,r1);

  // A non-op4 pass-through remains fail-closed with dac_ok=0. A subsequent
  // op4 must still break the wrapper out of WR_WAIT and restore the reset hold.
  command(1,(58'd40<<10));
  repeat(10) @(posedge clk);
  if(!r0[8] || en || dac_start)
   $fatal(1,"non-op4 command was not interlocked %h/%h",r0,r1);
  command(4,0);
  completed();
  if(!en || !rst || tm || r0[10] || r0[7:0]!=9)
   $fatal(1,"disabled-interlock WR_WAIT abort failed %h/%h",r0,r1);

  @(negedge clk);
  cmd={cmd[63],1'b0,62'd0};
  repeat(6) @(posedge clk);
  dac_ok=1;
  repeat(6) @(posedge clk);

  // Operation 15 must fail closed before all 32 words have been loaded.
  command(15,(58'd1<<57)|(58'd1<<37)|(58'd40<<22)|(58'd2<<20));
  completed();
  if(!r0[10] || r0[14:11]!=8 || r1[255:224]!=32'h424D4532 ||
     r1[39:32]!=3)
   $fatal(1,"incomplete bitmap did not fail closed %h/%h",r0,r1);

  // Word 0 alternates targets; remaining words carry deterministic data so
  // that readback is meaningful rather than a validity-mask-only check.
  for(k=0;k<32;k=k+1) begin
   expected_word=(k==0) ? 32'hA5A5A5A5 : (32'h13579BDF^k);
   load_bitmap_word(k[4:0],expected_word,k==0);
  end
  if(dut.bitmap_valid!=32'hFFFFFFFF)
   $fatal(1,"bitmap validity mask incomplete %h",dut.bitmap_valid);

  // Read the stored word, not merely the last command echo.
  command(14,(58'd1<<56));
  completed();
  if(r0[10] || !r1[223] || !r1[216] ||
     r1[215:184]!=32'hFFFFFFFF || r1[183:152]!=32'hA5A5A5A5)
   $fatal(1,"bitmap readback failed %h/%h",r0,r1);

  // Program physical cells 0..7 from 0xA5: SET indices 0,2,5,7 must all be
  // visited before RESET indices 1,3,4,6.  Every cell is already correct, so
  // each receives one initial read plus ten confirmation reads, no pulse.
  k=reset_edges;
  schedule_count=0; capture_schedule=1;
  command(15,(58'd1<<57)|(58'd7<<37)|(58'd40<<22)|(58'd2<<20));
  completed();
  capture_schedule=0;
  if(r0[10] || r1[255:224]!=32'h42504432 ||
     r1[223:213]!=8 || r1[212:202]!=0 || reset_edges!=k+88 ||
     r1[118:108]!=4 || r1[107:97]!=4 ||
     r1[96:86]!=0 || r1[85:75]!=0)
   $fatal(1,"two-phase bitmap scheduler failed resets=%0d result=%h/%h",reset_edges-k,r0,r1);
  if(schedule_count!=8 || schedule_order[0]!=0 || schedule_order[1]!=2 ||
     schedule_order[2]!=5 || schedule_order[3]!=7 ||
     schedule_order[4]!=1 || schedule_order[5]!=3 ||
     schedule_order[6]!=4 || schedule_order[7]!=6)
   $fatal(1,"bitmap execution was not SET-then-RESET: count=%0d order=%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d",
          schedule_count,schedule_order[0],schedule_order[1],schedule_order[2],schedule_order[3],
          schedule_order[4],schedule_order[5],schedule_order[6],schedule_order[7]);

  // Degenerate ranges must also terminate: an all-SET range finishes without
  // entering RESET phase, while an all-RESET range crosses the empty SET phase.
  k=reset_edges;
  command(15,(58'd1<<57)|(58'd40<<22)|(58'd2<<20));
  completed();
  if(r0[10] || r1[223:213]!=1 || r1[118:108]!=1 ||
     r1[107:97]!=0 || reset_edges!=k+11)
   $fatal(1,"single SET bitmap range failed %h/%h",r0,r1);
  k=reset_edges;
  command(15,(58'd1<<57)|(58'd1<<47)|(58'd40<<22)|(58'd2<<20));
  completed();
  if(r0[10] || r1[223:213]!=1 || r1[118:108]!=0 ||
     r1[107:97]!=1 || reset_edges!=k+11)
   $fatal(1,"single RESET bitmap range failed %h/%h",r0,r1);

  // Existing op13 paging now exposes requested state and bitmap-record marker
  // in formerly reserved bits 28 and 29.  Legacy current/pulse/pass fields are
  // untouched.  Word 0 is cell (0,0); word 1 is cell (0,1).
  command(13,0);
  completed();
  repeat(10) @(posedge clk);
  if(r1[255:224]!=32'h41524732 ||
     !r0[61] || !r0[60] || !r0[58] || r0[57:48]!=0 ||
     !r0[93] || r0[92] || !r0[90] || r0[89:80]!=0)
   $fatal(1,"bitmap op13 record decode failed %h/%h",r0,r1);

  // Compatibility guard: op12 retains ARR2 and leaves bitmap-only reserved
  // flags zero in its op13 records.
  k=reset_edges;
  command(12,(58'd1<<57)|(58'd1<<36)|(58'd40<<21));
  completed();
  if(r0[10] || r1[255:224]!=32'h41525232 || r1[223:213]!=2 ||
     reset_edges!=k+22)
   $fatal(1,"legacy op12 compatibility failed %h/%h",r0,r1);
  command(13,0);
  completed();
  repeat(10) @(posedge clk);
  if(r0[61:60]!=0 || r0[93:92]!=0)
   $fatal(1,"legacy op13 reserved fields changed %h",r0);

  // Exercise complete 1024-bit zero, one, and alternating images.  Launching
  // count_minus_one=1023 proves the 11-bit remaining count does not wrap;
  // abort immediately so this structural test does not spend simulation time
  // on 11,264 modeled scan packets per image.
  load_uniform_bitmap(32'h00000000);
  command(15,(58'd1<<57)|(58'd1023<<37)|(58'd40<<22)|(58'd2<<20));
  if(dut.array_remaining!=1024 || !dut.bitmap_mode ||
     dut.bitmap_reset_phase || dut.wrapper_state!=10)
   $fatal(1,"all-zero full bitmap launch failed count=%0d",dut.array_remaining);
  command(4,0); completed();
  if(!rst || tm) $fatal(1,"all-zero full bitmap abort not safe");

  load_uniform_bitmap(32'hFFFFFFFF);
  command(15,(58'd1<<57)|(58'd1023<<37)|(58'd40<<22)|(58'd2<<20));
  if(dut.array_remaining!=1024 || !dut.bitmap_mode || !dut.array_set)
   $fatal(1,"all-one full bitmap launch failed count=%0d",dut.array_remaining);
  command(4,0); completed();
  if(!rst || tm) $fatal(1,"all-one full bitmap abort not safe");

  load_uniform_bitmap(32'hAAAAAAAA);
  command(15,(58'd1<<57)|(58'd1023<<37)|(58'd40<<22)|(58'd2<<20));
  if(dut.array_remaining!=1024 || !dut.bitmap_mode || !dut.array_set ||
     dut.bitmap_reset_phase)
   $fatal(1,"alternating full bitmap launch failed count=%0d",dut.array_remaining);
  command(4,0); completed();
  if(!rst || tm) $fatal(1,"alternating full bitmap abort not safe");

  // Program physical indices 13 and 14 across the op13 page boundary.  In
  // 0xAAAAAAAA, odd index 13 is SET and even index 14 is RESET.
  k=reset_edges;
  command(15,(58'd1<<57)|(58'd13<<47)|(58'd1<<37)|
             (58'd40<<22)|(58'd2<<20));
  completed();
  // The preceding abort already holds reset asserted, so the first of the
  // scheduler's 22 packets restarts that hold without another rising edge.
  if(r0[10] || r1[255:224]!=32'h42504432 ||
     r1[223:213]!=2 || r1[212:202]!=0 || reset_edges!=k+21)
   $fatal(1,"page-boundary bitmap scheduler failed %h/%h",r0,r1);
  command(13,0); completed(); repeat(10) @(posedge clk);
  page_word0=r1[223:192];
  command(13,1); completed(); repeat(10) @(posedge clk);
  page_word1=r0[63:32];
  if(!page_word0[29] || !page_word0[28] || !page_word0[26] ||
     !page_word1[29] || page_word1[28] || !page_word1[26])
   $fatal(1,"op13 page-boundary target decode failed %h/%h",page_word0,page_word1);

  $display("PASS disabled-interlock BMP2/op4/direct-WR_WAIT-abort, bitmap load/readback, fail-closed launch, two-phase SET-then-RESET scheduler, full patterns/abort, page boundary, packet reset cadence, op12/13 compatibility");
  $finish;
 end

 initial begin
  #200000000;
  $fatal(1,"global timeout");
 end
endmodule
