`timescale 1ns/1ps
// command[63] toggle, [62] enable, [61:58] operation:
// 1 scan ([57] SET, [24:10] hold clocks, [9:5] col, [4:0] row);
// 2 DAC ([23:0] protected frame); 3 WB ([57] write,[39:32] tag,[31:0] packet);
 // 4 hold CPU reset / abort ([57] select WB pin ownership); 5 WB result index[3:0];
 // 6 ADC trace index; 7 MAC accumulator ([57] clear, [4:0] output column).
 // 8 compound PROGRAM_STEP: [57] SET/RESET, [56:41] VCC DAC code,
 // [40:25] WL DAC code, [24:10] hold clocks, [9:5] column, [4:0] row.
 // PROGRAM_STEP writes the programming rails, pulses the selected cell,
 // restores the changed read rails, and returns a clean READ capture.
 // Scan op 1 may also request a fabric MAC update with [56]=1 and signed
 // input[55:48]. The selected cell's ADC3 active-minus-baseline measurement is
 // multiplied by that input and accumulated for its packet column.
// Runtime DAC writes cannot change VDDA1/VCCD2, range or reference.
module cell_control_core #(
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
 output reg reset_low=0, tm=0, se=1, si=0,
 output wire scan_tristate, si_tristate,
 output reg dac_start=0, output reg [23:0] dac_frame=0, input wire dac_done,
 output reg [255:0] result0=0, result1=0
);
 localparam IDLE=0, RESET=1, READY=2, POST=3, SETUP=4, SHIFT=5,
  HOLD=6, FINISH=7, ERROR=8, HELD=9, DAC=10, DAC_SETTLE=11,
  WB_BOOT=12, WB_LOW=13, WB_SEPARATOR=14, WB_FINAL=15, WB_RESULT=16, TRACE_TAIL=17;
 reg [7:0] state=IDLE;
 (* ASYNC_REG="TRUE" *) reg [2:0] fb_sync=0, ready_sync=0, rst_sync=0;
 reg fb_previous=0, seen_toggle=0, done=0, fault=0, saw_ready_low=0, wb_mode=0;
 reg [3:0] fault_code=0;
 reg ready_fallback_used=0;
 reg [4:0] clip_mask=0;
 reg [15:0] packet=0, base_count=0, active_count=0, hold_cycles=2400;
 reg [31:0] ticks=0, reset_ticks=0, no_clock=0;
 reg [63:0] watchdog=0;
 reg [6:0] bit_index=0;
 reg [31:0] baseline[0:4], active[0:4], wb_words[0:14];
 reg signed [55:0] mac_accum[0:31];
 reg signed [7:0] mac_input=0;
reg signed [39:0] mac_delta_reg=0;
reg signed [47:0] mac_product_reg=0;
 reg [4:0] mac_selected=0;
 reg mac_accumulate=0, mac_view=0;
reg [1:0] mac_stage=0;
 reg program_active=0, program_set=0, program_clip_seen=0;
 reg [2:0] program_phase=0;
 reg [4:0] program_row=0, program_col=0;
 reg [15:0] program_vcc_code=0, program_wl_code=0, program_hold=2400;
 reg [63:0] wb_frame=0;
 reg [7:0] base_tag=8'h80;
 reg [14:0] wb_mask=0;
 reg [3:0] selected=0;
 reg wb_boot_ready=0, ready_at_edge=0, wb_release=0;
 reg [31:0] echo_value=0, diagnostic=0;
 reg echo_seen=0, protocol_error=0;
 reg [15:0] uart_error_count=0;
 wire falling=fb_previous && !fb_sync[2];
 wire scan_busy=((state>=RESET && state<=FINISH) || state==TRACE_TAIL) && !wb_mode;
 wire busy=(state!=IDLE && state!=ERROR && state!=HELD);
 // A hold/abort (op4) is the one command that must remain available while
 // the runtime DAC interlock is deliberately off. It only takes ownership
 // of the digital Caravel pins and asserts reset; it cannot launch a DAC
 // transaction or an array pulse. Every operation that can touch the array
 // remains fail-closed behind dac_ready.
 wire hold_or_abort=command[61:58]==4'd4;
 assign interface_enable=command[62] && (dac_ready || hold_or_abort);
 // Caravel's functional WB FSM requires both SE and TM low. Floating SE
 // rises through U17's pull-up, so retain ownership in WB (GPIO21 is input).
 assign scan_tristate=!interface_enable;
 assign si_tristate=!interface_enable || (wb_mode && wb_release);
 wire [7:0] rx_byte;
 wire rx_valid, rx_error;
 uart_rx_8n1 #(.CLOCK_HZ(200000000)) rx(
  .clk_i(clk),.reset_i(reset_low || !interface_enable),.rx_i(uart_rx),
  .byte_o(rx_byte),.byte_valid_o(rx_valid),.framing_error_o(rx_error));
 reg [3:0] rx_pos=0;
 reg [7:0] rx_tag=0, rx_xor=0;
 reg [31:0] rx_data=0;
 // Measured, decimated ADC snapshots: three 12-bit current paths, elapsed
 // sample periods at 10 MSPS, and controller phase. No synthetic waveform.
 reg [63:0] trace_mem[0:255];
 reg [8:0] trace_count=0;
 reg [7:0] trace_selected=0;
 reg [19:0] trace_sample=0;
 reg [8:0] trace_div=100, trace_decimate=0;
 reg trace_mode=0;
 wire [8:0] trace_next1={1'b0,trace_selected}+9'd1;
 wire [8:0] trace_next2={1'b0,trace_selected}+9'd2;
 wire [33:0] mac_active_times4={active[2],2'b00};
 wire [38:0] mac_base_times75=baseline[2]*7'd75;
 wire signed [39:0] mac_delta=$signed({6'd0,mac_active_times4})-
                                $signed({1'b0,mac_base_times75});
 integer j;
 function [11:0] reverse12;
  input [11:0] v; integer k;
  begin for(k=0;k<12;k=k+1) reverse12[k]=v[11-k]; end
 endfunction
 function dac_allowed;
  input [23:0] f;
  begin
   dac_allowed=((f[23:16]==8'h12 || f[23:16]==8'h13 ||
                 f[23:16]==8'h14 || f[23:16]==8'h15 ||
                 (f[23:16]>=8'h19 && f[23:16]<=8'h1D)) && f[15:0]<=16'h999A)
                 // Scan: 4/6/7/8 off. WB: physical VCC_SET on DAC2
                 // and WL_SET on DAC3 off; 6/7/8 remain unused/off.
                 // Supply channels DAC14/15 remain enabled in both masks.
                 || f==24'h0901D0 || f==24'h0901CC;
  end
 endfunction
 function [63:0] make_wb_frame;
  input [63:0] c; reg [7:0] flags, check;
  begin
   flags={7'd0,c[57]};
   check=8'hA7 ^ flags ^ c[39:32] ^ c[31:24] ^ c[23:16] ^ c[15:8] ^ c[7:0];
   make_wb_frame={8'hA7,flags,c[39:32],c[31:0],check};
  end
 endfunction
 initial begin
  for(j=0;j<5;j=j+1) begin baseline[j]=0; active[j]=0; end
  for(j=0;j<15;j=j+1) wb_words[j]=0;
  for(j=0;j<32;j=j+1) mac_accum[j]=0;
 end
 always @(posedge clk) begin
  fb_sync<={fb_sync[1:0],feedback_clk}; fb_previous<=fb_sync[2];
  ready_sync<={ready_sync[1:0],ready_i}; rst_sync<={rst_sync[1:0],reset_i};
  if(falling) no_clock<=0; else if(no_clock<2000000) no_clock<=no_clock+1;
  dac_start<=0;
  result0<=0;
  result0[7:0]<=state;
  result0[8]<=busy; result0[9]<=done; result0[10]<=fault;
  result0[14:11]<=fault_code; result0[15]<=seen_toggle;
  result0[31:16]<=packet;
  result0[32]<=interface_enable; result0[33]<=ready_sync[2]; result0[34]<=rst_sync[2];
  result0[35]<=(no_clock<CLOCK_MISSING); result0[36]<=adc_healthy;
  result0[37]<=|clip_mask[2:0]; result0[38]<=wb_mode; result0[43:39]<=clip_mask;
  result0[44]<=program_clip_seen;
  // A scan packet always receives a fresh Caravel reset.  This flag only
  // reports that the proven Kintex-compatible 1-ms post-release bound was
  // used instead of observing READY low then high; it is not a persistent
  // or continuous-packet mode.
  result0[45]<=ready_fallback_used;
  result0[63:48]<=uart_error_count;
  result0[79:64]<=base_count; result0[95:80]<=active_count;
  for(j=0;j<5;j=j+1) result0[96+32*j+:32]<=baseline[j];
  result1<={32'h53435232,4'd0,samples,active[4],active[3],active[2],active[1],active[0]};
  if(wb_mode) begin
   result1[159:0]<=0;
   result1[31:0]<=selected<15 ? wb_words[selected] : 0;
   result1[39:32]<=base_tag+selected;
   result1[54:40]<=wb_mask;
   result1[55]<=echo_seen; result1[56]<=protocol_error;
   result1[95:64]<=echo_value; result1[127:96]<=diagnostic;
   result1[131:128]<=selected;
  end
  if(trace_mode) begin
   result1<=0;
   result1[255:224]<=32'h54524332;
   result1[200:192]<=trace_count;
   result1[208:201]<=trace_selected;
   result1[217:209]<=trace_div;
   result1[63:0]<=trace_selected<trace_count ? trace_mem[trace_selected] : 0;
   result1[127:64]<=trace_next1<trace_count ? trace_mem[trace_next1[7:0]] : 0;
   result1[191:128]<=trace_next2<trace_count ? trace_mem[trace_next2[7:0]] : 0;
  end
  if(mac_view) begin
   result1<=0;
   result1[255:224]<=32'h4D414332; // "MAC2"
   result1[55:0]<=mac_accum[mac_selected];
   result1[60:56]<=mac_selected;
   // mac_delta = 48000 * (active-average - baseline-average) when the
   // nominal 12000/640 sample windows are present.
   result1[95:64]<=32'd48000;
  end
  // Binary result frames coexist with ASCII diagnostics. Only checksum-checked
  // tag-matched results enter the bank. All fifteen results survive JTAG polling.
  if(reset_low || !interface_enable) rx_pos<=0;
  else begin
   if(rx_error) begin uart_error_count<=uart_error_count+1; rx_pos<=0; end
   if(rx_valid) case(rx_pos)
    0: if(rx_byte==8'hA5) rx_pos<=1;
    1: if(rx_byte==8'h5A) rx_pos<=2; else rx_pos<=rx_byte==8'hA5 ? 1 : 0;
    2: begin rx_tag<=rx_byte; rx_xor<=rx_byte; rx_pos<=3; end
    3,4,5,6: begin rx_data<={rx_data[23:0],rx_byte}; rx_xor<=rx_xor^rx_byte; rx_pos<=rx_pos+1; end
    7: begin
     rx_pos<=0;
     if(rx_byte!=rx_xor) uart_error_count<=uart_error_count+1;
     else if(wb_mode) begin
      if(rx_tag==8'hF1 && rx_data==1) wb_boot_ready<=1;
      if(rx_tag==8'hF2) begin echo_seen<=1; echo_value<=rx_data; end
      if(rx_tag==8'hF3 || rx_data==32'hBAD0C0DE) begin protocol_error<=1; diagnostic<=rx_data; end
      if(rx_tag>=base_tag && rx_tag<base_tag+15) begin
       wb_words[rx_tag-base_tag]<=rx_data;
       wb_mask[rx_tag-base_tag]<=1;
      end
     end
    end
    default: rx_pos<=0;
   endcase
  end
  if(!interface_enable) begin
    state<=IDLE; reset_low<=0; tm<=0; se<=1; si<=0; wb_mode<=0; wb_release<=0;
    done<=0; fault<=0; seen_toggle<=command[63]; watchdog<=0; trace_mode<=0;
    mac_accumulate<=0; mac_view<=0; mac_stage<=0; program_active<=0;
  end else if(command[63]!=seen_toggle && command[61:58]==4) begin
   // Abort/prepare is accepted even when busy, without waiting for clock edges.
   seen_toggle<=command[63]; state<=HELD; reset_low<=1; tm<=0; se<=!command[57];
   wb_mode<=command[57]; si<=command[57]; wb_release<=0;
   done<=1; fault<=0; fault_code<=0; watchdog<=0; trace_mode<=0;
   mac_accumulate<=0; mac_view<=0; mac_stage<=0; program_active<=0;
  end else if(busy && ((scan_busy && !adc_healthy) ||
             (state!=DAC && state!=DAC_SETTLE && no_clock>=CLOCK_MISSING) ||
             watchdog>=WATCHDOG_CYCLES || (wb_mode && protocol_error))) begin
   state<=ERROR; reset_low<=1; tm<=0; se<=!wb_mode; wb_release<=1; done<=1; fault<=1;
   mac_accumulate<=0; mac_stage<=0; program_active<=0;
   fault_code<=protocol_error ? 7 : ((scan_busy && !adc_healthy) ? 1 : (no_clock>=CLOCK_MISSING ? 2 : 3));
  end else begin
   // The ADC normalization, signed multiply and selected-column add are split
   // across fabric clocks. A scan stays busy for the much longer TRACE_TAIL,
   // so this pipeline completes before the command can report done.
   if(mac_stage==1) begin
    mac_product_reg<=mac_delta_reg*mac_input;
    mac_stage<=2;
   end else if(mac_stage==2) begin
    mac_accum[packet[9:5]]<=mac_accum[packet[9:5]]+
                            {{8{mac_product_reg[47]}},mac_product_reg};
    mac_accumulate<=0; mac_stage<=0;
   end
   if(busy) watchdog<=watchdog+1;
   if(!busy && command[63]!=seen_toggle) begin
    seen_toggle<=command[63];
    mac_view<=0;
    if(command[61:58]==5) begin selected<=command[3:0]; trace_mode<=0; end
    else if(command[61:58]==6) begin trace_selected<=command[7:0]; trace_mode<=1; end
    else begin
     done<=0; fault<=0; fault_code<=0; watchdog<=0; trace_mode<=0;
     case(command[61:58])
      1: begin
       if(command[24:10]<1 || command[24:10]>12000 || !adc_healthy) begin
        state<=ERROR; fault<=1; done<=1; fault_code<=4; reset_low<=1;
       end else begin
        packet<={command[57],command[4:0],command[9:5],command[4:0]};
        mac_accumulate<=command[56]; mac_input<=$signed(command[55:48]); mac_stage<=0;
        hold_cycles<={1'b0,command[24:10]}; clip_mask<=0; base_count<=0; active_count<=0;
        for(j=0;j<5;j=j+1) begin baseline[j]<=0; active[j]<=0; end
        ticks<=0; reset_ticks<=0; saw_ready_low<=0; wb_mode<=0; wb_release<=0;
        trace_count<=0; trace_sample<=0; trace_decimate<=0; ready_fallback_used<=0;
        trace_div<=command[24:10]<=4000 ? 100 : 250;
        tm<=0; se<=1; si<=0; reset_low<=1; state<=RESET;
       end
      end
      2: begin
       reset_low<=1; tm<=0; se<=!wb_mode;
       if(!dac_allowed(command[23:0])) begin state<=ERROR; fault<=1; done<=1; fault_code<=5; end
       else begin dac_frame<=command[23:0]; dac_start<=1; state<=DAC; end
      end
      3: begin
       wb_frame<=make_wb_frame(command); base_tag<=command[39:32];
       wb_mask<=0; selected<=0; echo_seen<=0; echo_value<=0; diagnostic<=0;
       protocol_error<=0; wb_boot_ready<=0; uart_error_count<=0;
       wb_mode<=1; wb_release<=0; tm<=0; se<=0; si<=1;
       reset_low<=1; reset_ticks<=0; state<=RESET; ticks<=0;
      end
       7: begin
        if(command[57]) for(j=0;j<32;j=j+1) mac_accum[j]<=0;
        mac_selected<=command[4:0]; mac_view<=1; state<=IDLE; done<=1;
       end
       8: begin
        if(command[24:10]<20 || command[24:10]>12000 ||
           command[56:41]>16'h999A || command[40:25]>16'h999A || !adc_healthy) begin
         state<=ERROR; fault<=1; done<=1; fault_code<=4; reset_low<=1;
        end else begin
         program_active<=1; program_set<=command[57]; program_phase<=0;
         program_row<=command[4:0]; program_col<=command[9:5];
         program_vcc_code<=command[56:41]; program_wl_code<=command[40:25];
         program_hold<={1'b0,command[24:10]}; program_clip_seen<=0;
         packet<={command[57],command[4:0],command[9:5],command[4:0]};
         reset_low<=1; tm<=0; se<=1; si<=0; wb_mode<=0; wb_release<=0;
         // Both polarities use the established DAC2/DAC3 scan-programming
         // pair; OP_SET in the scan packet selects SET versus RESET.
         dac_frame<=24'h0901D0;
         dac_start<=1; state<=DAC;
        end
       end
      default: begin state<=ERROR; fault<=1; done<=1; fault_code<=6; reset_low<=1; end
     endcase
    end
   end
   // Prefer a real READY low/high phase, which proves the Caravel firmware
   // has booted and owns the scan pads.  The READY state below also retains
   // the working Kintex controller's bounded post-reset fallback; RESET_B is
   // still asserted afresh for every individual packet.
   if(scan_busy && !ready_sync[2]) saw_ready_low<=1;
   if(sample_valid && state==POST) begin
    base_count<=base_count+1;
    for(j=0;j<5;j=j+1) begin
     baseline[j]<=baseline[j]+reverse12(samples[j*12+:12]);
     if(reverse12(samples[j*12+:12])==0 || reverse12(samples[j*12+:12])==4095) clip_mask[j]<=1;
    end
   end
   if(sample_valid && ((state>=POST && state<=FINISH) || state==TRACE_TAIL)) begin
    trace_sample<=trace_sample+1;
    if(trace_decimate==0) begin
     trace_decimate<=trace_div-1;
     if(trace_count<256) begin
      trace_mem[trace_count[7:0]]<={state,trace_sample,
          reverse12(samples[35:24]),reverse12(samples[23:12]),reverse12(samples[11:0])};
      trace_count<=trace_count+1;
     end
    end else trace_decimate<=trace_decimate-1;
   end
   if(sample_valid && state==HOLD && se) begin
    active_count<=active_count+1;
    for(j=0;j<5;j=j+1) begin
     active[j]<=active[j]+reverse12(samples[j*12+:12]);
     if(reverse12(samples[j*12+:12])==0 || reverse12(samples[j*12+:12])==4095) clip_mask[j]<=1;
    end
   end
   if(state==RESET) begin
    if(reset_ticks==RESET_SYS-1) begin reset_low<=0; state<=wb_mode ? WB_BOOT : READY; end
    else reset_ticks<=reset_ticks+1;
   end
   if(state==DAC && dac_done) begin ticks<=0; state<=DAC_SETTLE; end
   if(state==DAC_SETTLE) begin
    if(ticks==DAC_SETTLE_CYCLES) begin
     ticks<=0;
     if(program_active) case(program_phase)
      0: begin
       program_phase<=1;
       dac_frame<={8'h12,program_vcc_code};
       dac_start<=1; state<=DAC;
      end
      1: begin
       program_phase<=2;
       dac_frame<={8'h13,program_wl_code};
       dac_start<=1; state<=DAC;
      end
      2: begin
       program_phase<=3; hold_cycles<=program_hold;
       clip_mask<=0; base_count<=0; active_count<=0;
       for(j=0;j<5;j=j+1) begin baseline[j]<=0; active[j]<=0; end
       reset_ticks<=0; saw_ready_low<=0; trace_count<=0; trace_sample<=0; trace_decimate<=0;
       ready_fallback_used<=0;
       trace_div<=program_hold<=4000 ? 100 : 250;
       tm<=0; se<=1; si<=0; reset_low<=1; state<=RESET;
      end
      4: begin
       program_phase<=5;
       dac_frame<=24'h138000;
       dac_start<=1; state<=DAC;
      end
      5: begin
       program_phase<=7; packet<={1'b0,program_row,program_col,program_row};
       hold_cycles<=16'd2400; clip_mask<=0; base_count<=0; active_count<=0;
       for(j=0;j<5;j=j+1) begin baseline[j]<=0; active[j]<=0; end
       reset_ticks<=0; saw_ready_low<=0; trace_count<=0; trace_sample<=0; trace_decimate<=0;
       ready_fallback_used<=0;
       trace_div<=100; tm<=0; se<=1; si<=0; reset_low<=1; state<=RESET;
      end
      6: begin
       program_phase<=7; packet<={1'b0,program_row,program_col,program_row};
       hold_cycles<=16'd2400; clip_mask<=0; base_count<=0; active_count<=0;
       for(j=0;j<5;j=j+1) begin baseline[j]<=0; active[j]<=0; end
       reset_ticks<=0; saw_ready_low<=0; trace_count<=0; trace_sample<=0; trace_decimate<=0;
       ready_fallback_used<=0;
       trace_div<=100; tm<=0; se<=1; si<=0; reset_low<=1; state<=RESET;
      end
      default: begin
       state<=ERROR; fault<=1; done<=1; fault_code<=6; reset_low<=1; program_active<=0;
      end
     endcase
     else begin state<=HELD; done<=1; end
    end else ticks<=ticks+1;
   end
   if(state==WB_RESULT && wb_mask==15'h7FFF && echo_seen) begin state<=IDLE; done<=1; end
   if(falling) case(state)
    READY: begin
     if(saw_ready_low && ready_sync[2] && rst_sync[2]) begin
      ticks<=0; state<=POST;
     end else if(READY_FALLBACK_CYCLES>0 &&
                 ticks>=READY_FALLBACK_CYCLES-1 && rst_sync[2]) begin
      // Match the working Kintex burst controller: the reset is mandatory,
      // while READY is advisory after a bounded 1-ms release interval.
      ready_fallback_used<=1; ticks<=0; state<=POST;
     end else ticks<=ticks+1;
    end
    POST: if(ticks==POST_CYCLES-1) begin ticks<=0; state<=SETUP; end else ticks<=ticks+1;
    SETUP: begin tm<=1; se<=1; si<=0; bit_index<=0; state<=SHIFT; end
    SHIFT: begin
     tm<=1; se<=0; si<=(bit_index>=1 && bit_index<=16) ? packet[bit_index-1] : 0;
     if(bit_index==17) begin ticks<=0; state<=HOLD; end else bit_index<=bit_index+1;
    end
    HOLD: begin
     se<=1; si<=0;
     if(ticks==hold_cycles-1) begin ticks<=0; state<=FINISH; end else ticks<=ticks+1;
    end
    FINISH: begin
     tm<=0; se<=1; si<=0; state<=TRACE_TAIL; ticks<=0;
    end
    TRACE_TAIL: begin
     // Capture on the next feedback edge, after any final active ADC sample.
     if(ticks==0 && mac_accumulate && mac_stage==0) begin
      mac_delta_reg<=mac_delta; mac_stage<=1;
     end
     if(ticks==POST_CYCLES-1) begin
      if(program_active && program_phase==3) begin
       program_clip_seen<=|clip_mask[2:0]; program_phase<=4;
       dac_frame<=24'h12199A;
       dac_start<=1; state<=DAC; ticks<=0; reset_low<=1; tm<=0; se<=1; si<=0;
      end else begin
       state<=IDLE; done<=1;
       if(program_active && program_phase==7) program_active<=0;
      end
     end else ticks<=ticks+1;
    end
    WB_BOOT: if(wb_boot_ready && rst_sync[2]) begin
     bit_index<=63; si<=0; ticks<=0; ready_at_edge<=ready_sync[2]; state<=WB_LOW;
    end
    WB_LOW: if(ticks==(wb_frame[bit_index] ? WB_ONE-1 : WB_ZERO-1)) begin
     si<=1; ticks<=0; state<=WB_SEPARATOR;
    end else ticks<=ticks+1;
    WB_SEPARATOR: if(ticks>=WB_HIGH-1 && ready_sync[2]!=ready_at_edge) begin
     ticks<=0; si<=0; ready_at_edge<=ready_sync[2];
     if(bit_index==0) state<=WB_FINAL; else begin bit_index<=bit_index-1; state<=WB_LOW; end
    end else if(ticks<32'hFFFFFFFE) ticks<=ticks+1;
    WB_FINAL: if(ticks==WB_END-1) begin wb_release<=1; state<=WB_RESULT; end else ticks<=ticks+1;
    default: begin end
   endcase
  end
 end
endmodule
