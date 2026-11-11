`timescale 1ns/1ps
// Read-only scan protocol adapted from Evaluation_Research_Boards- v35.
// Data updates on the observed falling edge of Si5351 CLK1 (matched CLK0).
// 200 MHz sampling adds <=20 ns latency, against 250 ns half-cycle at 2 MHz.
// command: [63] toggle, [62] interface enable, [61] start read, [9:5] col, [4:0] row.
// OP_SET is hardwired zero. No programming-voltage or SET operation exists.
module scan_read_engine #(
    parameter RESET_CYCLES=24000, POST_CYCLES=128, HOLD_CYCLES=2400,
    parameter WATCHDOG_CYCLES=400000000
)(
    input wire clk, input wire feedback_clk, input wire ready_i, input wire reset_i,
    input wire dac_ready, input wire adc_healthy,
    input wire [63:0] command,
    input wire sample_valid, input wire [59:0] samples,
    output wire interface_enable,
    output reg reset_low=0, output reg tm=0, output reg se=1, output reg si=0,
    output reg [255:0] result0=0, output reg [255:0] result1=0
);
    localparam IDLE=0, RESET=1, READY=2, POST=3, SETUP=4, SHIFT=5, HOLD=6, FINISH=7, ERROR=8;
    reg [3:0] state=IDLE;
    (* ASYNC_REG="TRUE" *) reg [2:0] fb_sync=0, ready_sync=0, rst_sync=0;
    reg fb_previous=0, seen_toggle=0, done=0, fault=0, saw_ready_low=0, clipped=0;
    reg [3:0] fault_code=0;
    reg [15:0] packet=0, base_count=0, active_count=0;
    reg [31:0] ticks=0, watchdog=0, no_clock=0;
    reg [4:0] bit_index=0;
    reg [31:0] baseline[0:4], active[0:4];
    integer j;
    wire falling=fb_previous && !fb_sync[2];
    wire busy=(state>=RESET && state<=HOLD);
    assign interface_enable=command[62] && dac_ready;
    function [11:0] reverse12;
        input [11:0] v; integer k;
        begin for(k=0;k<12;k=k+1) reverse12[k]=v[11-k]; end
    endfunction
    initial for(j=0;j<5;j=j+1) begin baseline[j]=0; active[j]=0; end
    always @(posedge clk) begin
        fb_sync <= {fb_sync[1:0],feedback_clk}; fb_previous<=fb_sync[2];
        ready_sync <= {ready_sync[1:0],ready_i}; rst_sync <= {rst_sync[1:0],reset_i};
        if(falling) no_clock<=0; else if(no_clock<2000000) no_clock<=no_clock+1;
        // Registered, stable result vectors; snapshot after done before next command.
        result0 <= {baseline[4],baseline[3],baseline[2],baseline[1],baseline[0],active_count,base_count,
            26'd0,clipped,adc_healthy,(no_clock<2000),rst_sync[2],ready_sync[2],interface_enable,
            packet,seen_toggle,fault_code,fault,done,busy,4'd0,state};
        result1 <= {32'h53435231,4'd0,samples,active[4],active[3],active[2],active[1],active[0]};
        if(!interface_enable) begin
            state<=IDLE; reset_low<=0; tm<=0; se<=1; si<=0;
            done<=0; fault<=0; seen_toggle<=command[63]; watchdog<=0;
        end else if(busy && (!adc_healthy || no_clock>=2000 || watchdog>=WATCHDOG_CYCLES)) begin
            state<=ERROR; reset_low<=0; tm<=0; se<=1; si<=0; done<=1; fault<=1;
            fault_code<=!adc_healthy ? 1 : (no_clock>=2000 ? 2 : 3);
        end else begin
            if(busy) watchdog<=watchdog+1;
            if(!busy && command[63]!=seen_toggle) begin
                seen_toggle<=command[63];
                if(command[61]) begin
                    packet<={1'b0,command[4:0],command[9:5],command[4:0]};
                    done<=0; fault<=0; fault_code<=0; clipped<=0;
                    base_count<=0; active_count<=0;
                    for(j=0;j<5;j=j+1) begin baseline[j]<=0; active[j]<=0; end
                    ticks<=0; watchdog<=0; saw_ready_low<=0;
                    tm<=0; se<=1; si<=0; reset_low<=1; state<=RESET;
                end
            end
            if(busy && !ready_sync[2]) saw_ready_low<=1;
            if(sample_valid && state==POST) begin
                base_count<=base_count+1;
                for(j=0;j<5;j=j+1) baseline[j]<=baseline[j]+reverse12(samples[j*12+:12]);
            end
            // Exclude the final clock interval before TM falls. Nominal 1.2 ms
            // selection window; approximately 11,995 ADC packets are integrated.
            if(sample_valid && state==HOLD && se) begin
                active_count<=active_count+1;
                for(j=0;j<5;j=j+1) begin
                    active[j]<=active[j]+reverse12(samples[j*12+:12]);
                    if(j<3 && (reverse12(samples[j*12+:12])==0 || reverse12(samples[j*12+:12])==4095)) clipped<=1;
                end
            end
            if(falling) case(state)
                RESET: if(ticks==RESET_CYCLES-1) begin reset_low<=0; ticks<=0; state<=READY; end else ticks<=ticks+1;
                READY: if(saw_ready_low && ready_sync[2] && rst_sync[2]) begin ticks<=0; state<=POST; end
                POST: if(ticks==POST_CYCLES-1) begin ticks<=0; state<=SETUP; end else ticks<=ticks+1;
                SETUP: begin tm<=1; se<=1; si<=0; bit_index<=0; state<=SHIFT; end
                SHIFT: begin
                    tm<=1; se<=0;
                    si <= (bit_index>=1 && bit_index<=16) ? packet[bit_index-1] : 1'b0;
                    if(bit_index==17) begin ticks<=0; state<=HOLD; end else bit_index<=bit_index+1;
                end
                HOLD: begin
                    se<=1; si<=0;
                    if(ticks==HOLD_CYCLES-1) begin ticks<=0; state<=FINISH; end else ticks<=ticks+1;
                end
                FINISH: begin tm<=0; se<=1; si<=0; state<=IDLE; done<=1; end
                default: begin end
            endcase
        end
    end
endmodule
