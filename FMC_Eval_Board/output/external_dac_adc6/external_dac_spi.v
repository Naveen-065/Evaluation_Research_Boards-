`timescale 1ns/1ps
// Standalone service image for the external AX7020 DAC, not the KC705 PCB DAC.
// No automatic DAC writes. The 50 MHz onboard oscillator drives a 500 kHz
// mode-1 SPI engine. Other Zynq I/O pins are unused, with no weak pulls.
module external_dac_spi(
    input wire sys_clk_50m_i,
    input wire dac_sdo_i,
    output wire dac_sclk_o, dac_sdi_o, dac_cs_n_o,
    output wire dac_ldac_n_o
);
    wire [63:0] command, status;
    vio_runtime_command runtime_vio(.clk(sys_clk_50m_i),
        .probe_out0(command), .probe_in0(status));
    dac_spi_service service(.clk(sys_clk_50m_i), .command(command), .status(status),
        .sdo(dac_sdo_i), .sclk(dac_sclk_o), .sdi(dac_sdi_o), .ncs(dac_cs_n_o));
    assign dac_ldac_n_o = 1'b1;
endmodule

module dac_spi_service #(
    parameter integer HALF_CYCLES=50
)(input wire clk, input wire [63:0] command, input wire sdo,
  output reg [63:0] status=64'hDAC8000000000000,
  output reg sclk=0, sdi=0, ncs=1);
    reg [2:0] state=0;
    reg [7:0] token=0;
    reg [23:0] tx=0, rx=0;
    reg [4:0] bit_index=23;
    reg [15:0] delay_count=0;
    // command[63:56] is a new nonzero token, command[23:0] a raw SPI frame.
    // status[63:48]=DAC8, [40]=busy, [39:32]=completed token, [23:0]=SDO frame.
    always @(posedge clk) begin
        case(state)
        0: begin
            if(command[63:56] != token && command[63:56] != 0) begin
                token<=command[63:56]; tx<=command[23:0]; rx<=0;
                bit_index<=23; delay_count<=0; ncs<=0; sclk<=0; sdi<=0;
                status[40]<=1; state<=1;
            end
        end
        1: begin
            if(delay_count==HALF_CYCLES-1) begin
                delay_count<=0; sclk<=1; sdi<=tx[bit_index]; state<=2;
            end else delay_count<=delay_count+1;
        end
        2: begin
            if(delay_count==HALF_CYCLES-1) begin
                delay_count<=0; sclk<=0; rx<={rx[22:0],sdo};
                if(bit_index==0) state<=3;
                else begin bit_index<=bit_index-1; state<=1; end
            end else delay_count<=delay_count+1;
        end
        3: begin
            if(delay_count==HALF_CYCLES-1) begin
                delay_count<=0; ncs<=1; sdi<=0; state<=4;
            end else delay_count<=delay_count+1;
        end
        4: begin
            if(delay_count==HALF_CYCLES-1) begin
                delay_count<=0; status<={16'hDAC8,8'h00,token,8'h00,rx}; state<=0;
            end else delay_count<=delay_count+1;
        end
        default: begin ncs<=1; sclk<=0; sdi<=0; state<=0; end
        endcase
    end
endmodule
