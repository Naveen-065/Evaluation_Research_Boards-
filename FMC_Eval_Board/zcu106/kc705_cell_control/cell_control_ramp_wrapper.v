`timescale 1ns/1ps

// VIO command scheduler around the validated single-step controller.
// Operation 9 executes the complete bounded SET/RESET grid in fabric.
// Operation 11 executes a measured three-point min/mean/max grid.  Every
// inner operation remains a one-cell PROGRAM_STEP (operation 8), including
// rail restoration and a clean post-pulse read.  A passing read is followed
// by ten ordinary confirmation reads before success is reported.
// Operation 10 pages out the compact signed ADC-code trace, 28 points/page.
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
            WR_ADVANCE=5, WR_PAGE=6;
 localparam signed [39:0] SET_THRESHOLD=40'sd1348731;
 localparam signed [39:0] RESET_THRESHOLD=40'sd192676;

 reg [2:0] wrapper_state=WR_READY;
 reg host_seen=0, have_result=0, ramp_result=0, ramp_view=0;
 reg [63:0] inner_command=0;
 reg [255:0] saved0=0, saved1=0;
 reg ramp_set=0, ramp_fast=0, ramp_met=0, ramp_clip_seen=0;
 reg [4:0] ramp_row=0, ramp_col=0;
 reg [14:0] ramp_hold=2400;
 reg [15:0] ramp_max_vcc=0, ramp_max_wl=0;
 reg [6:0] ramp_index=0;
 reg [7:0] ramp_pulses=0;
 reg [3:0] ramp_confirm_count=0;
 reg signed [15:0] ramp_current_code[0:95];
 reg [6:0] ramp_read_addr=0;
 reg [4:0] ramp_page_cursor=0;
 reg signed [15:0] ramp_read_data=0;
 reg ramp_page_primed=0;
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
 wire ramp_pass=ramp_set ? ramp_delta>=SET_THRESHOLD : ramp_delta<=RESET_THRESHOLD;

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
 end

 always @(posedge clk) begin
  // One synchronous trace-memory read per cycle.  A 28-cycle page transfer
  // replaces 28 parallel 96:1 muxes and keeps the 200 MHz path short.
  if(ramp_read_addr<96) ramp_read_data<=ramp_current_code[ramp_read_addr];
  else ramp_read_data<=0;
  if(!command[62]) begin
   wrapper_state<=WR_READY; host_seen<=command[63]; inner_command<=0;
   have_result<=0; ramp_result<=0; ramp_view<=0;
  end else if((wrapper_state==WR_STEP || wrapper_state==WR_CONFIRM) &&
              command[63]!=host_seen && command[61:58]==4) begin
   host_seen<=command[63]; have_result<=0; ramp_result<=0; ramp_view<=0;
   inner_command<={~inner_command[63],command[62:0]}; wrapper_state<=WR_ABORT;
  end else case(wrapper_state)
   WR_READY: if(command[63]!=host_seen) begin
    host_seen<=command[63]; ramp_view<=0;
    if(command[61:58]==9 || command[61:58]==11) begin
     have_result<=0; ramp_result<=0; ramp_set<=command[57];
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
    end else begin
     have_result<=0; ramp_result<=0;
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
     ramp_met<=0; ramp_result<=1; have_result<=1; wrapper_state<=WR_READY;
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
     saved0[10]<=1; saved0[14:11]<=4'd1; have_result<=1; wrapper_state<=WR_READY;
    end else if(ramp_pass) begin
     ramp_confirm_count<=0; issue_read(ramp_row,ramp_col); wrapper_state<=WR_CONFIRM;
    end else if(ramp_index<(ramp_fast ? 2 : 95)) begin
     ramp_index<=ramp_index+1'b1; wrapper_state<=WR_ADVANCE;
    end else begin
     ramp_met<=0; ramp_result<=1; have_result<=1; wrapper_state<=WR_READY;
    end
   end
   WR_CONFIRM: if(inner_complete) begin
    saved0<=inner_result0; saved1<=inner_result1;
    if(inner_result0[10] || inner_result0[37]) begin
     saved0[10]<=1; saved0[14:11]<=4'd1; have_result<=1; wrapper_state<=WR_READY;
    end else if(ramp_pass && ramp_confirm_count==9) begin
     ramp_met<=1; ramp_confirm_count<=10; ramp_result<=1; have_result<=1; wrapper_state<=WR_READY;
    end else if(ramp_pass) begin
     ramp_confirm_count<=ramp_confirm_count+1'b1; issue_read(ramp_row,ramp_col);
    end else if(ramp_index<(ramp_fast ? 2 : 95)) begin
     ramp_confirm_count<=0; ramp_index<=ramp_index+1'b1;
     wrapper_state<=WR_ADVANCE;
    end else begin
     ramp_met<=0; ramp_result<=1; have_result<=1; wrapper_state<=WR_READY;
    end
   end
   default: wrapper_state<=WR_READY;
  endcase
 end
endmodule
