`timescale 1ns/1ps

// VIO command scheduler around the validated single-step controller.
// Operation 9 executes the complete bounded SET/RESET grid in fabric.
// Operation 11 executes a measured three-point min/mean/max grid.  Every
// inner operation remains a one-cell PROGRAM_STEP (operation 8), including
// rail restoration and a clean post-pulse read.  A passing read is followed
// by ten ordinary confirmation reads before success is reported.
// Operation 10 pages out the compact signed ADC-code trace, 28 points/page.
// Operation 12 owns a contiguous row-major array range in fabric.  It performs
// an initial state read, the selected fast/reliable ramp, and ten stable
// confirmation reads for every cell.  Payload bits 20:19 select zero to three
// additional bounded RESET sweeps when reliable mode is enabled.  Each inner packet still receives the
// mandatory Caravel reset/READY sequence from cell_control_core.
// Operation 13 pages out fourteen compact per-cell array results per request.
// Operation 14 loads or reads one of thirty-two 32-bit target bitmap words.
// Bit N is physical row-major cell {row=N[9:5], column=N[4:0]}; one bits
// request LRS/SET and zero bits request HRS/RESET.  All words must be loaded
// and read back before operation 15 is accepted.
// Operation 15 programs an arbitrary bitmap range in two deterministic phases:
// all SET targets first, then all RESET targets.  This makes the final operation
// on every requested HRS cell a RESET instead of allowing a later neighboring
// SET to disturb a previously verified HRS cell.  SET targets use the measured
// three-step path; RESET targets use the reliable 96-step path plus the
// requested bounded retry count.  Every read/program/confirmation remains an
// ordinary operation-1/8 packet and thus still receives the mandatory Caravel
// reset/READY handshake in the core.
module cell_control_engine #(
 parameter RESET_SYS=2400000, POST_CYCLES=128,
 parameter READY_FALLBACK_CYCLES=2000,
 parameter [63:0] WATCHDOG_CYCLES=64'd12000000000,
 parameter WB_ZERO=200000, WB_ONE=800000, WB_HIGH=500000, WB_END=500000,
 parameter CLOCK_MISSING=2000, DAC_SETTLE_CYCLES=200000
)(
 input wire clk, feedback_clk, ready_i, reset_i, uart_rx,
 input wire dac_ready, adc_healthy, input wire [63:0] command,
 input wire sample_valid, input wire [59:0] samples,
 output wire interface_enable,
 output wire reset_low, tm, se, si,
 output wire scan_tristate, si_tristate,
 output wire dac_start, output wire [23:0] dac_frame, input wire dac_done,
 output reg [255:0] result0=0, result1=0
);
 localparam WR_READY=0, WR_WAIT=1, WR_STEP=2, WR_CONFIRM=3, WR_ABORT=4,
            WR_ADVANCE=5, WR_PAGE=6, WR_ARRAY_PRE=7,
            WR_ARRAY_CONFIRM=8, WR_ARRAY_PAGE=9, WR_BITMAP_NEXT=10;
 localparam signed [39:0] SET_THRESHOLD=40'sd1348731;
 localparam signed [39:0] RESET_THRESHOLD=40'sd192676;
 // 68.5126 uS measured best HRS/LRS separator at the 0.5-V read bias.
 // Equivalent nominal current is 34.2563 uA.  This is used only by the
 // reliable 96-point RESET path; command 11 retains the strict 5-uA target.
 localparam signed [39:0] HRS_THRESHOLD=40'sd1320073;

 reg [3:0] wrapper_state=WR_READY;
 reg host_seen=0, have_result=0, ramp_result=0, ramp_view=0;
 reg array_active=0, array_result=0, array_view=0;
 reg [63:0] inner_command=0;
 reg [255:0] saved0=0, saved1=0;
 reg ramp_set=0, ramp_fast=0, ramp_met=0, ramp_clip_seen=0;
 reg [4:0] ramp_row=0, ramp_col=0;
 reg [14:0] ramp_hold=2400, array_base_hold=2400;
 reg [15:0] ramp_max_vcc=0, ramp_max_wl=0;
 reg [6:0] ramp_index=0;
 reg [7:0] ramp_pulses=0;
 reg [3:0] ramp_confirm_count=0;
 reg signed [15:0] ramp_current_code[0:95];
 reg [6:0] ramp_read_addr=0;
 reg [4:0] ramp_page_cursor=0;
 reg signed [15:0] ramp_read_data=0;
 reg ramp_page_primed=0;
 reg array_set=0, array_reliable=0;
 reg [9:0] array_start=0, array_end=0, array_index=0;
 reg [10:0] array_remaining=0;
 reg [10:0] array_completed=0, array_failures=0;
 reg [18:0] array_total_pulses=0;
 reg signed [15:0] array_last_current=0;
 reg [9:0] array_last_pulses=0, array_retry_pulses=0;
 reg [1:0] array_retry=0, array_retry_limit=0;
 reg array_last_met=0, array_last_clip=0;
 // One packed synchronous store maps cleanly to block RAM and keeps paging
 // logic small: {reserved[3:0], clip, met, pulses[9:0], current[15:0]}.
 reg [31:0] array_result_memory[0:1023];
 reg array_write_enable=0;
 reg [9:0] array_write_addr=0;
 reg [31:0] array_write_data=0;
 reg [9:0] array_read_addr=0;
 reg [3:0] array_page_cursor=0;
 reg [31:0] array_read_data=0;
 reg array_page_primed=0;
 // A full target image is deliberately held in registers: operation 14 writes
 // one naturally aligned 32-bit word at a time, while the serial array
 // scheduler needs one random target bit per cell.  1024 bits are negligible
 // on ZU7EV and avoid a divider or multi-port RAM around the critical path.
 reg [1023:0] desired_bitmap=0;
 reg [31:0] bitmap_valid=0;
 reg bitmap_mode=0;
 // Phase zero visits only requested SET bits; phase one then visits only
 // requested RESET bits.  The scanner advances one physical index per fabric
 // clock, negligible beside a scan packet, and avoids a 1024-way priority mux.
 reg bitmap_reset_phase=0;
 reg [9:0] bitmap_scan_index=0;
 reg [10:0] bitmap_set_targets=0, bitmap_reset_targets=0;
 reg [10:0] bitmap_set_failures=0, bitmap_reset_failures=0;
 wire [255:0] inner_result0, inner_result1;
 wire inner_interface_enable;
 wire inner_complete=inner_result0[15]==inner_command[63] &&
                     inner_result0[9] && !inner_result0[8];

 cell_control_core #(
  .RESET_SYS(RESET_SYS),.POST_CYCLES(POST_CYCLES),.WATCHDOG_CYCLES(WATCHDOG_CYCLES),
  .READY_FALLBACK_CYCLES(READY_FALLBACK_CYCLES),
  .WB_ZERO(WB_ZERO),.WB_ONE(WB_ONE),.WB_HIGH(WB_HIGH),.WB_END(WB_END),
  .CLOCK_MISSING(CLOCK_MISSING),.DAC_SETTLE_CYCLES(DAC_SETTLE_CYCLES)
 ) core (
  .clk(clk),.feedback_clk(feedback_clk),.ready_i(ready_i),.reset_i(reset_i),.uart_rx(uart_rx),
  .dac_ready(dac_ready),.adc_healthy(adc_healthy),.command(inner_command),
  .sample_valid(sample_valid),.samples(samples),.interface_enable(inner_interface_enable),
  .reset_low(reset_low),.tm(tm),.se(se),.si(si),.scan_tristate(scan_tristate),
  .si_tristate(si_tristate),.dac_start(dac_start),.dac_frame(dac_frame),.dac_done(dac_done),
  .result0(inner_result0),.result1(inner_result1));
 assign interface_enable=inner_interface_enable;

 // Precomputed round(mV*65536/5000) codes keep the ramp scheduler out of
 // the 200 MHz critical path; there is no fabric divider or multiplier.
 function [15:0] ramp_vcc_code;
  input set_operation, fast_operation; input [6:0] index;
  begin
   if(fast_operation) begin
    if(set_operation) ramp_vcc_code=16'd30147; // SET: 2.30 V for all 3 points
    else case(index)
     0:ramp_vcc_code=16'd30147; // RESET minimum: 2.30 V
     1:ramp_vcc_code=16'd36700; // RESET measured mean: 2.80 V
     default:ramp_vcc_code=16'd39321; // RESET maximum: <=3.00 V hard cap
    endcase
   end else if(set_operation) ramp_vcc_code=index<32 ? 16'd30147 :
                                      (index<64 ? 16'd31457 : 16'd32768);
   else ramp_vcc_code=index<32 ? 16'd30147 :
                                // Match the host's hard 3.000-V floor cap.
                                (index<64 ? 16'd35389 : 16'd39321);
  end
 endfunction
 function [15:0] ramp_wl_code;
  input set_operation, fast_operation; input [6:0] index;
  begin
   if(fast_operation) begin
    if(set_operation) case(index)
     0:ramp_wl_code=16'd5767;   // 0.44 V measured minimum
     1:ramp_wl_code=16'd14287;  // 1.09 V measured mean
     default:ramp_wl_code=16'd22938; // 1.75 V measured maximum
    endcase
    else case(index)
     0:ramp_wl_code=16'd12321;  // 0.94 V response minimum
     1:ramp_wl_code=16'd23986;  // 1.83 V response mean
     default:ramp_wl_code=16'd37749; // 2.88 V configured maximum
    endcase
   end else if(set_operation) case(index[4:0])
    0:ramp_wl_code=5767; 1:ramp_wl_code=6554; 2:ramp_wl_code=7340; 3:ramp_wl_code=8258;
    4:ramp_wl_code=9044; 5:ramp_wl_code=9830; 6:ramp_wl_code=10617; 7:ramp_wl_code=11403;
    8:ramp_wl_code=12321; 9:ramp_wl_code=13107; 10:ramp_wl_code=13894; 11:ramp_wl_code=14680;
    12:ramp_wl_code=15598; 13:ramp_wl_code=16384; 14:ramp_wl_code=17170; 15:ramp_wl_code=17957;
    16:ramp_wl_code=18743; 17:ramp_wl_code=19661; 18:ramp_wl_code=20447; 19:ramp_wl_code=21234;
    20:ramp_wl_code=22020; 21:ramp_wl_code=22938; 22:ramp_wl_code=23724; 23:ramp_wl_code=24510;
    24:ramp_wl_code=25297; 25:ramp_wl_code=26083; 26:ramp_wl_code=27001; 27:ramp_wl_code=27787;
    28:ramp_wl_code=28574; 29:ramp_wl_code=29360; 30:ramp_wl_code=30278; default:ramp_wl_code=31064;
   endcase
   else case(index[4:0])
    0:ramp_wl_code=12321; 1:ramp_wl_code=13238; 2:ramp_wl_code=14025; 3:ramp_wl_code=14811;
    4:ramp_wl_code=15598; 5:ramp_wl_code=16515; 6:ramp_wl_code=17302; 7:ramp_wl_code=18088;
    8:ramp_wl_code=18874; 9:ramp_wl_code=19792; 10:ramp_wl_code=20578; 11:ramp_wl_code=21365;
    12:ramp_wl_code=22151; 13:ramp_wl_code=23069; 14:ramp_wl_code=23855; 15:ramp_wl_code=24642;
    16:ramp_wl_code=25428; 17:ramp_wl_code=26345; 18:ramp_wl_code=27132; 19:ramp_wl_code=27918;
    20:ramp_wl_code=28705; 21:ramp_wl_code=29622; 22:ramp_wl_code=30409; 23:ramp_wl_code=31195;
    24:ramp_wl_code=31982; 25:ramp_wl_code=32768; 26:ramp_wl_code=33686; 27:ramp_wl_code=34472;
    28:ramp_wl_code=35258; 29:ramp_wl_code=36045; 30:ramp_wl_code=36962; default:ramp_wl_code=37749;
   endcase
  end
 endfunction

 wire [33:0] ramp_active_times4={inner_result1[95:64],2'b00};
 wire [38:0] ramp_base_times75=inner_result0[191:160]*7'd75;
 wire signed [39:0] ramp_delta=$signed({6'd0,ramp_active_times4})-
                                  $signed({1'b0,ramp_base_times75});
 wire ramp_pass=ramp_set ? ramp_delta>=SET_THRESHOLD :
                 ramp_delta<=(ramp_fast ? RESET_THRESHOLD : HRS_THRESHOLD);
 wire array_initial_pass=array_set ? ramp_delta>=SET_THRESHOLD : ramp_delta<=HRS_THRESHOLD;
 wire signed [15:0] ramp_current_compact=ramp_delta>>>14;
 wire [10:0] array_command_count={1'b0,command[45:36]}+11'd1;
 wire [10:0] array_command_end={1'b0,command[55:46]}+
                               array_command_count-11'd1;
 wire [10:0] bitmap_command_count={1'b0,command[46:37]}+11'd1;
 wire [10:0] bitmap_command_end={1'b0,command[56:47]}+
                                bitmap_command_count-11'd1;

 task issue_step;
  input set_operation; input [6:0] index;
  input [14:0] pulse_hold; input [4:0] row, col;
  begin
   inner_command<={~inner_command[63],1'b1,4'd8,set_operation,
                   ramp_vcc_code(set_operation,ramp_fast,index),
                   ramp_wl_code(set_operation,ramp_fast,index),
                   pulse_hold,col,row};
  end
 endtask
 task issue_read;
  input [4:0] row, col;
  begin inner_command<={~inner_command[63],1'b1,4'd1,1'b0,32'd0,15'd2400,col,row}; end
 endtask
 task finish_array_cell;
  input cell_met; input signed [15:0] current_code; input [9:0] pulse_count;
  reg [9:0] next_index;
  begin
   array_write_enable<=1; array_write_addr<=array_index;
   // Bits 29:28 are only defined for bitmap records.  Legacy op12 records
   // retain zero in all four reserved MSBs, preserving the op13 wire format.
   array_write_data<=bitmap_mode ?
      {2'd0,1'b1,array_set,ramp_clip_seen,cell_met,pulse_count,current_code} :
      {4'd0,ramp_clip_seen,cell_met,pulse_count,current_code};
   array_completed<=array_completed+1'b1;
   if(!cell_met) array_failures<=array_failures+1'b1;
   if(bitmap_mode) begin
    if(array_set) begin
     bitmap_set_targets<=bitmap_set_targets+1'b1;
     if(!cell_met) bitmap_set_failures<=bitmap_set_failures+1'b1;
    end else begin
     bitmap_reset_targets<=bitmap_reset_targets+1'b1;
     if(!cell_met) bitmap_reset_failures<=bitmap_reset_failures+1'b1;
    end
   end
   array_total_pulses<=array_total_pulses+pulse_count;
   array_last_current<=current_code; array_last_pulses<=pulse_count;
   array_last_met<=cell_met; array_last_clip<=ramp_clip_seen;
   if(array_remaining==1) begin
    array_remaining<=0; array_active<=0; array_result<=1;
    have_result<=1; saved0<=0; saved1<=0; wrapper_state<=WR_READY;
   end else begin
    array_remaining<=array_remaining-1'b1;
    ramp_index<=0; ramp_pulses<=0; ramp_confirm_count<=0;
    ramp_met<=0; ramp_clip_seen<=0; array_retry<=0; array_retry_pulses<=0;
    ramp_hold<=array_base_hold;
    if(bitmap_mode) begin
     // Continue the current phase after this physical index.  If this was the
     // end of the SET scan, restart at the range base for the RESET phase.
     if(!bitmap_reset_phase && array_index==array_end) begin
      bitmap_reset_phase<=1;
      bitmap_scan_index<=array_start;
     end else bitmap_scan_index<=array_index+1'b1;
     wrapper_state<=WR_BITMAP_NEXT;
    end else begin
     next_index=array_index+1'b1;
     array_index<=next_index;
     ramp_row<=next_index[9:5]; ramp_col<=next_index[4:0];
     issue_read(next_index[9:5],next_index[4:0]);
     wrapper_state<=WR_ARRAY_PRE;
    end
   end
  end
 endtask
 task complete_array_sweep;
  input cell_met; input signed [15:0] current_code; input [7:0] sweep_pulses;
  reg [9:0] total_pulses;
  reg [9:0] next_index;
  begin
   total_pulses=array_retry_pulses+sweep_pulses;
   if(!cell_met && !array_set && array_reliable && array_retry<array_retry_limit) begin
    array_retry<=array_retry+1'b1; array_retry_pulses<=total_pulses;
    ramp_index<=0; ramp_pulses<=0; ramp_confirm_count<=0;
    // Escalate width only after a complete safe-voltage sweep fails.  With
    // the default 2400 clocks: 1.2 ms, 2.4 ms, then 6.0 ms at 2 MHz.
    ramp_hold<=array_retry==0 ?
               (array_base_hold>6000 ? 15'd12000 : array_base_hold<<1) :
               15'd12000;
    ramp_met<=0; wrapper_state<=WR_ADVANCE;
   end else begin
    array_write_enable<=1; array_write_addr<=array_index;
    array_write_data<=bitmap_mode ?
       {2'd0,1'b1,array_set,ramp_clip_seen,cell_met,total_pulses,current_code} :
       {4'd0,ramp_clip_seen,cell_met,total_pulses,current_code};
    array_completed<=array_completed+1'b1;
    if(!cell_met) array_failures<=array_failures+1'b1;
    if(bitmap_mode) begin
     if(array_set) begin
      bitmap_set_targets<=bitmap_set_targets+1'b1;
      if(!cell_met) bitmap_set_failures<=bitmap_set_failures+1'b1;
     end else begin
      bitmap_reset_targets<=bitmap_reset_targets+1'b1;
      if(!cell_met) bitmap_reset_failures<=bitmap_reset_failures+1'b1;
     end
    end
    array_total_pulses<=array_total_pulses+total_pulses;
    array_last_current<=current_code; array_last_pulses<=total_pulses;
    array_last_met<=cell_met; array_last_clip<=ramp_clip_seen;
    if(array_remaining==1) begin
     array_remaining<=0; array_active<=0; array_result<=1;
     have_result<=1; saved0<=0; saved1<=0; wrapper_state<=WR_READY;
    end else begin
     array_remaining<=array_remaining-1'b1;
     ramp_index<=0; ramp_pulses<=0; ramp_confirm_count<=0;
     ramp_met<=0; ramp_clip_seen<=0; array_retry<=0; array_retry_pulses<=0;
     ramp_hold<=array_base_hold;
     if(bitmap_mode) begin
      if(!bitmap_reset_phase && array_index==array_end) begin
       bitmap_reset_phase<=1;
       bitmap_scan_index<=array_start;
      end else bitmap_scan_index<=array_index+1'b1;
      wrapper_state<=WR_BITMAP_NEXT;
     end else begin
      next_index=array_index+1'b1;
      array_index<=next_index;
      ramp_row<=next_index[9:5]; ramp_col<=next_index[4:0];
      issue_read(next_index[9:5],next_index[4:0]);
      wrapper_state<=WR_ARRAY_PRE;
     end
    end
   end
  end
 endtask

 always @* begin
  result0=have_result ? saved0 : inner_result0;
  result1=have_result ? saved1 : inner_result1;
  result0[15]=host_seen;
  if(wrapper_state==WR_READY) begin result0[8]=0; result0[9]=have_result; end
  else begin result0[8]=1; result0[9]=0; end
  if(ramp_result && have_result && !ramp_view) begin
   result1[223:216]=ramp_pulses;
   result1[215]=ramp_met;
   result1[214]=ramp_clip_seen;
   result1[213:207]=ramp_index;
   result1[206:203]=ramp_confirm_count;
  end
  if((array_active || array_result) && !array_view) begin
   result1=0;
   result1[255:224]=bitmap_mode ?
      (array_active ? 32'h42505232 : 32'h42504432) : // BPR2 / BPD2
      (array_active ? 32'h41525032 : 32'h41525232);  // ARP2 / ARR2
   result1[223:213]=array_completed;
   result1[212:202]=array_failures;
   result1[201:183]=array_total_pulses;
   result1[182:173]=array_index;
   result1[172]=array_set; result1[171]=array_reliable;
   result1[170:161]=array_start;
   result1[160:151]=array_end;
   result1[150:135]=array_last_current;
   result1[134:125]=array_last_pulses;
   result1[124]=array_last_met; result1[123]=array_last_clip;
   result1[122:121]=array_retry; result1[120:119]=array_retry_limit;
   if(bitmap_mode) begin
    result1[118:108]=bitmap_set_targets;
    result1[107:97]=bitmap_reset_targets;
    result1[96:86]=bitmap_set_failures;
    result1[85:75]=bitmap_reset_failures;
    result1[74:43]=bitmap_valid;
   end
  end
 end

 // A single registered write port plus synchronous read port infers one
 // 1024x32 block RAM instead of 32K individual result flip-flops.
 always @(posedge clk) begin
  if(array_write_enable) array_result_memory[array_write_addr]<=array_write_data;
  array_read_data<=array_result_memory[array_read_addr];
 end

 always @(posedge clk) begin
  array_write_enable<=0;
  // One synchronous trace-memory read per cycle.  A 28-cycle page transfer
  // replaces 28 parallel 96:1 muxes and keeps the 200 MHz path short.
  if(ramp_read_addr<96) ramp_read_data<=ramp_current_code[ramp_read_addr];
  else ramp_read_data<=0;
  if(!command[62]) begin
   wrapper_state<=WR_READY; host_seen<=command[63]; inner_command<=0;
   have_result<=0; ramp_result<=0; ramp_view<=0;
   array_active<=0; array_result<=0; array_view<=0;
   desired_bitmap<=0; bitmap_valid<=0; bitmap_mode<=0;
   bitmap_reset_phase<=0; bitmap_scan_index<=0;
  // Forward a newly toggled hold/abort from every non-ready state. In
  // particular this makes a pass-through command stuck in WR_WAIT recoverable
  // when an interlock was removed after it was submitted. The core gives op4
  // priority over its own busy state and cannot emit a DAC start for op4.
  end else if(wrapper_state!=WR_READY && command[63]!=host_seen &&
              command[61:58]==4) begin
   host_seen<=command[63]; have_result<=0; ramp_result<=0; ramp_view<=0;
   array_active<=0; array_result<=0; array_view<=0;
   bitmap_mode<=0;
   inner_command<={~inner_command[63],command[62:0]}; wrapper_state<=WR_ABORT;
  end else case(wrapper_state)
   WR_READY: if(command[63]!=host_seen) begin
    host_seen<=command[63]; ramp_view<=0; array_view<=0;
    if(command[61:58]==9 || command[61:58]==11) begin
     have_result<=0; ramp_result<=0; array_result<=0; ramp_set<=command[57];
     ramp_fast<=command[61:58]==11;
     ramp_row<=command[4:0]; ramp_col<=command[9:5]; ramp_hold<=command[24:10];
     ramp_max_vcc<=command[56:41]; ramp_max_wl<=command[40:25];
     ramp_index<=0; ramp_pulses<=0; ramp_confirm_count<=0;
     ramp_met<=0; ramp_clip_seen<=0;
     wrapper_state<=WR_ADVANCE;
    end else if(command[61:58]==10) begin
     ramp_view<=1; have_result<=0; saved0<=0; saved1<=0;
     saved0[23:16]<=ramp_pulses; saved0[24]<=ramp_met;
     saved0[25]<=ramp_clip_seen; saved0[27:26]<=command[1:0];
     saved1[255:224]<=32'h524D5032; // RMP2
     ramp_read_addr<={command[1:0],5'd0}-{command[1:0],2'd0}; // page*28
     ramp_page_cursor<=0; ramp_page_primed<=0; wrapper_state<=WR_PAGE;
    end else if(command[61:58]==14) begin
     // Bitmap word transaction layout:
     //   [57] clear-before-write, [56] read-only, [55:51] word index,
     //   [50:32] reserved (zero), [31:0] row-major target bits.
     // A read-only transaction lets the host verify all bits after loading;
     // its data field is ignored.  clear+read is intentionally invalid.
     have_result<=1; ramp_result<=0; array_result<=0; bitmap_mode<=0;
     saved0<=0; saved1<=0;
     saved0[20:16]<={command[55:51]};
     if(command[50:32]!=0 || (command[57] && command[56])) begin
      saved0[10]<=1; saved0[14:11]<=4'd8;
      saved1[255:224]<=32'h424D4532; // BME2: bitmap command error
      saved1[7:0]<=command[50:32]!=0 ? 8'd1 : 8'd2;
     end else begin
      saved1[255:224]<=32'h424D5032; // BMP2
      saved1[223]<=command[56]; saved1[222]<=command[57];
      saved1[221:217]<=command[55:51];
      if(command[56]) begin
       saved1[216]<=bitmap_valid[command[55:51]];
       saved1[215:184]<=bitmap_valid;
       saved1[183:152]<=desired_bitmap[{command[55:51],5'b0} +: 32];
      end else begin
       desired_bitmap[{command[55:51],5'b0} +: 32]<=command[31:0];
       if(command[57]) bitmap_valid<=32'h00000001<<command[55:51];
       else bitmap_valid[command[55:51]]<=1'b1;
       saved1[216]<=1'b1;
       saved1[215:184]<=command[57] ?
          (32'h00000001<<command[55:51]) :
          (bitmap_valid|(32'h00000001<<command[55:51]));
       saved1[183:152]<=command[31:0];
      end
     end
    end else if(command[61:58]==15 &&
                (bitmap_valid!=32'hFFFFFFFF ||
                 bitmap_command_end>=11'd1024 ||
                 command[36:22]<20 || command[36:22]>12000 ||
                 command[19:0]!=0)) begin
     have_result<=1; ramp_result<=0; array_active<=0; array_result<=0;
     bitmap_mode<=0; saved0<=0; saved1<=0;
     saved0[10]<=1; saved0[14:11]<=4'd8;
     saved1[255:224]<=32'h424D4532; // BME2
     saved1[31:0]<=bitmap_valid;
     if(bitmap_valid!=32'hFFFFFFFF) saved1[39:32]<=8'd3;
     else if(bitmap_command_end>=11'd1024) saved1[39:32]<=8'd4;
     else if(command[36:22]<20 || command[36:22]>12000)
      saved1[39:32]<=8'd5;
     else saved1[39:32]<=8'd6;
    end else if(command[61:58]==15) begin
     // Two-phase bitmap scheduler layout:
     // [57] reliable RESET, [56:47] start, [46:37] count-1,
     // [36:22] base hold clocks, [21:20] extra RESET sweeps,
     // [19:0] reserved zero.
     have_result<=0; ramp_result<=0; array_result<=0;
     array_active<=1; bitmap_mode<=1; array_reliable<=command[57];
     array_start<=command[56:47]; array_index<=command[56:47];
     array_end<=bitmap_command_end[9:0]; array_remaining<=bitmap_command_count;
     // Always begin with a SET-only scan.  WR_BITMAP_NEXT selects the first
     // matching target, so a range beginning with zero does not emit a RESET
     // until every requested SET target in the range has finished.
     array_set<=1'b1;
     array_completed<=0; array_failures<=0; array_total_pulses<=0;
     array_last_current<=0; array_last_pulses<=0;
     array_last_met<=0; array_last_clip<=0;
     bitmap_set_targets<=0; bitmap_reset_targets<=0;
     bitmap_set_failures<=0; bitmap_reset_failures<=0;
     bitmap_reset_phase<=0; bitmap_scan_index<=command[56:47];
     array_retry<=0; array_retry_pulses<=0; array_retry_limit<=command[21:20];
     ramp_set<=1'b1;
     ramp_fast<=1'b1;
     ramp_row<=command[56:52]; ramp_col<=command[51:47];
     ramp_hold<=command[36:22]; array_base_hold<=command[36:22];
     ramp_max_vcc<=16'd30147;
     ramp_max_wl<=16'd22938;
     ramp_index<=0; ramp_pulses<=0; ramp_confirm_count<=0;
     ramp_met<=0; ramp_clip_seen<=0;
     wrapper_state<=WR_BITMAP_NEXT;
    end else if(command[61:58]==12 && array_command_end<11'd1024) begin
     have_result<=0; ramp_result<=0; array_result<=0;
     bitmap_mode<=0;
     array_active<=1; array_set<=command[57]; array_reliable<=command[56];
     array_start<=command[55:46]; array_index<=command[55:46];
     array_end<=array_command_end[9:0]; array_remaining<=array_command_count;
     array_completed<=0; array_failures<=0; array_total_pulses<=0;
     array_last_current<=0; array_last_pulses<=0;
     array_last_met<=0; array_last_clip<=0;
     array_retry<=0; array_retry_pulses<=0; array_retry_limit<=command[20:19];
     ramp_set<=command[57]; ramp_fast<=command[57] || !command[56];
     ramp_row<=command[55:51]; ramp_col<=command[50:46];
     ramp_hold<=command[35:21]; array_base_hold<=command[35:21];
     ramp_max_vcc<=command[57] ? 16'd30147 : 16'd39321;
     ramp_max_wl<=command[57] ? 16'd22938 : 16'd37749;
     ramp_index<=0; ramp_pulses<=0; ramp_confirm_count<=0;
     ramp_met<=0; ramp_clip_seen<=0;
     issue_read(command[55:51],command[50:46]);
     wrapper_state<=WR_ARRAY_PRE;
    end else if(command[61:58]==12) begin
     array_active<=0; array_result<=0; have_result<=1;
     saved0<=0; saved1<=0; saved0[10]<=1; saved0[14:11]<=4'd7;
     saved1[255:224]<=32'h41524532; // ARE2: invalid physical range
    end else if(command[61:58]==13) begin
     array_view<=1; have_result<=0; saved0<=0; saved1<=0;
     saved0[31:16]<=({3'd0,command[6:0],4'd0}-{6'd0,command[6:0],1'b0}); // page*14
     saved1[255:224]<=32'h41524732; // ARG2
     array_read_addr<=({3'd0,command[6:0],4'd0}-{6'd0,command[6:0],1'b0});
     array_page_cursor<=0; array_page_primed<=0; wrapper_state<=WR_ARRAY_PAGE;
    end else begin
     have_result<=0; ramp_result<=0; array_result<=0;
     inner_command<={~inner_command[63],command[62:0]}; wrapper_state<=WR_WAIT;
    end
   end
   WR_WAIT: if(inner_complete) begin
    saved0<=inner_result0; saved1<=inner_result1; have_result<=1; wrapper_state<=WR_READY;
   end
   WR_ABORT: if(inner_complete) begin
    saved0<=inner_result0; saved1<=inner_result1; have_result<=1; wrapper_state<=WR_READY;
   end
   WR_ADVANCE: begin
    if(ramp_index>=(ramp_fast ? 3 : 96)) begin
     if(array_active) complete_array_sweep(1'b0,ramp_current_compact,ramp_pulses);
     else begin ramp_met<=0; ramp_result<=1; have_result<=1; wrapper_state<=WR_READY; end
    end else if(ramp_vcc_code(ramp_set,ramp_fast,ramp_index)<=ramp_max_vcc &&
                ramp_wl_code(ramp_set,ramp_fast,ramp_index)<=ramp_max_wl) begin
     issue_step(ramp_set,ramp_index,ramp_hold,ramp_row,ramp_col);
     wrapper_state<=WR_STEP;
    end else ramp_index<=ramp_index+1'b1;
   end
   WR_PAGE: begin
    if(!ramp_page_primed) begin
     // Prime the synchronous read and point at the following sample.
     ramp_page_primed<=1; ramp_read_addr<=ramp_read_addr+1'b1;
    end else begin
     if(ramp_page_cursor<14)
      saved0[255:32]<={ramp_read_data,saved0[255:48]};
     else
      saved1[223:0]<={ramp_read_data,saved1[223:16]};
     if(ramp_page_cursor==27) begin
      have_result<=1; wrapper_state<=WR_READY;
     end else begin
      ramp_page_cursor<=ramp_page_cursor+1'b1;
      ramp_read_addr<=ramp_read_addr+1'b1;
     end
    end
   end
   WR_ARRAY_PAGE: begin
    if(!array_page_primed) begin
     array_page_primed<=1; array_read_addr<=array_read_addr+1'b1;
    end else begin
     if(array_page_cursor<7)
      saved0[255:32]<={array_read_data,saved0[255:64]};
     else
      saved1[223:0]<={array_read_data,saved1[223:32]};
     if(array_page_cursor==13) begin
      have_result<=1; wrapper_state<=WR_READY;
     end else begin
      array_page_cursor<=array_page_cursor+1'b1;
      array_read_addr<=array_read_addr+1'b1;
     end
    end
   end
   WR_BITMAP_NEXT: begin
    // A sequential physical-index scan keeps this path tiny.  Candidate cells
    // are still written to result memory at their physical address, so op13's
    // row-major readout format is unchanged even though execution is phased.
    if(desired_bitmap[bitmap_scan_index]==!bitmap_reset_phase) begin
     array_index<=bitmap_scan_index;
     array_set<=!bitmap_reset_phase;
     ramp_set<=!bitmap_reset_phase;
     ramp_fast<=!bitmap_reset_phase || !array_reliable;
     ramp_row<=bitmap_scan_index[9:5]; ramp_col<=bitmap_scan_index[4:0];
     ramp_max_vcc<=!bitmap_reset_phase ? 16'd30147 : 16'd39321;
     ramp_max_wl<=!bitmap_reset_phase ? 16'd22938 : 16'd37749;
     issue_read(bitmap_scan_index[9:5],bitmap_scan_index[4:0]);
     wrapper_state<=WR_ARRAY_PRE;
    end else if(bitmap_scan_index==array_end) begin
     if(!bitmap_reset_phase) begin
      bitmap_reset_phase<=1;
      bitmap_scan_index<=array_start;
     end else begin
      // Reaching the end of both phases with work remaining indicates an
      // internal count/scanner inconsistency.  Stop without issuing a pulse.
      saved0<=0; saved1<=0; saved0[10]<=1; saved0[14:11]<=4'd8;
      saved1[255:224]<=32'h424D4532; saved1[39:32]<=8'd7;
      array_active<=0; array_result<=0; have_result<=1;
      wrapper_state<=WR_READY;
     end
    end else bitmap_scan_index<=bitmap_scan_index+1'b1;
   end
   WR_ARRAY_PRE: if(inner_complete) begin
    saved0<=inner_result0; saved1<=inner_result1;
    if(inner_result0[10] || inner_result0[37]) begin
     saved0[10]<=1; saved0[14:11]<=4'd1; array_active<=0;
     have_result<=1; wrapper_state<=WR_READY;
    end else if(array_initial_pass) begin
     ramp_confirm_count<=0; issue_read(ramp_row,ramp_col);
     wrapper_state<=WR_ARRAY_CONFIRM;
    end else begin
     ramp_index<=0; ramp_pulses<=0; ramp_confirm_count<=0;
     wrapper_state<=WR_ADVANCE;
    end
   end
   WR_ARRAY_CONFIRM: if(inner_complete) begin
    saved0<=inner_result0; saved1<=inner_result1;
    if(inner_result0[10] || inner_result0[37]) begin
     saved0[10]<=1; saved0[14:11]<=4'd1; array_active<=0;
     have_result<=1; wrapper_state<=WR_READY;
    end else if(array_initial_pass && ramp_confirm_count==9) begin
     finish_array_cell(1'b1,ramp_current_compact,8'd0);
    end else if(array_initial_pass) begin
     ramp_confirm_count<=ramp_confirm_count+1'b1;
     issue_read(ramp_row,ramp_col);
    end else begin
     ramp_index<=0; ramp_pulses<=0; ramp_confirm_count<=0;
     wrapper_state<=WR_ADVANCE;
    end
   end
   WR_STEP: if(inner_complete) begin
    saved0<=inner_result0; saved1<=inner_result1;
    ramp_clip_seen<=ramp_clip_seen|inner_result0[44];
    // Trace-only encoding: delta is 48000 times the average ADC-code
    // difference.  Store delta/2^14 exactly with a wire shift; the host
    // restores the 2^14/48000 scale.  This keeps <0.43 uA quantization while
    // avoiding a wide constant divider on the 200 MHz RAM write path.
    ramp_current_code[ramp_index]<=ramp_delta>>>14;
    ramp_pulses<=ramp_pulses+1'b1;
    if(inner_result0[10] || inner_result0[37]) begin
     saved0[10]<=1; saved0[14:11]<=4'd1;
     if(array_active) array_active<=0;
     have_result<=1; wrapper_state<=WR_READY;
    end else if(ramp_pass) begin
     ramp_confirm_count<=0; issue_read(ramp_row,ramp_col); wrapper_state<=WR_CONFIRM;
    end else if(ramp_index<(ramp_fast ? 2 : 95)) begin
     ramp_index<=ramp_index+1'b1; wrapper_state<=WR_ADVANCE;
    end else begin
     if(array_active) complete_array_sweep(1'b0,ramp_current_compact,ramp_pulses+1'b1);
     else begin ramp_met<=0; ramp_result<=1; have_result<=1; wrapper_state<=WR_READY; end
    end
   end
   WR_CONFIRM: if(inner_complete) begin
    saved0<=inner_result0; saved1<=inner_result1;
    if(inner_result0[10] || inner_result0[37]) begin
     saved0[10]<=1; saved0[14:11]<=4'd1;
     if(array_active) array_active<=0;
     have_result<=1; wrapper_state<=WR_READY;
    end else if(ramp_pass && ramp_confirm_count==9) begin
     if(array_active) complete_array_sweep(1'b1,ramp_current_compact,ramp_pulses);
     else begin
      ramp_met<=1; ramp_confirm_count<=10; ramp_result<=1; have_result<=1; wrapper_state<=WR_READY;
     end
    end else if(ramp_pass) begin
     ramp_confirm_count<=ramp_confirm_count+1'b1; issue_read(ramp_row,ramp_col);
    end else if(ramp_index<(ramp_fast ? 2 : 95)) begin
     ramp_confirm_count<=0; ramp_index<=ramp_index+1'b1;
     wrapper_state<=WR_ADVANCE;
    end else begin
     if(array_active) complete_array_sweep(1'b0,ramp_current_compact,ramp_pulses);
     else begin ramp_met<=0; ramp_result<=1; have_result<=1; wrapper_state<=WR_READY; end
    end
   end
   default: wrapper_state<=WR_READY;
  endcase
 end
endmodule
