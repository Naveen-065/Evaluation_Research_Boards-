`timescale 1ns/1ps

// Transactions occur only after an explicit nonzero VIO token change.
// No autonomous power-controller commands or recovery clocks are generated.
module kc705_vadj_bridge (
    input wire sysclk_p,
    input wire sysclk_n,
    inout wire pmbus_scl,
    inout wire pmbus_sda,
    output wire led0
);
    wire clk_raw, clk;
    wire [127:0] command, status;
    reg [4:0] reset_count = 0;
    reg [27:0] blink_count = 0;
    wire reset = !reset_count[4];
    IBUFDS clock_input (.I(sysclk_p), .IB(sysclk_n), .O(clk_raw));
    BUFG clock_global (.I(clk_raw), .O(clk));
    always @(posedge clk) begin
        if (!reset_count[4]) reset_count <= reset_count + 1'b1;
        blink_count <= blink_count + 1'b1;
    end
    assign led0 = blink_count[27];
    vadj_vio u_vio (.clk(clk), .probe_out0(command), .probe_in0(status));
    pmbus_transaction_bridge bridge (
        .clk(clk), .reset(reset), .command(command), .status(status),
        .scl(pmbus_scl), .sda(pmbus_sda)
    );
endmodule

module pmbus_transaction_bridge #(
    parameter integer CLK_HZ = 200000000,
    parameter integer BUS_HZ = 100000,
    parameter integer TIMEOUT_CYCLES = 2000000
) (
    input wire clk,
    input wire reset,
    input wire [127:0] command,
    output wire [127:0] status,
    inout wire scl,
    inout wire sda
);
    localparam integer HALF_CYCLES = CLK_HZ / (2 * BUS_HZ);
    localparam [4:0] IDLE=0, CHECK_BUS=1, START_HOLD=2,
        TX_LOW=3, TX_HIGH=4, ACK_LOW=5, ACK_HIGH=6,
        RESTART_LOW=7, RESTART_HIGH=8, RX_LOW=9, RX_HIGH=10,
        RX_ACK_LOW=11, RX_ACK_HIGH=12, STOP_LOW=13,
        STOP_HIGH=14, STOP_RELEASE=15, WAIT_RISE=16;
    localparam [5:0] ERR_LENGTH=1, ERR_BUSY=2, ERR_STRETCH=3,
        ERR_ADDRESS_W=4, ERR_WRITE=5, ERR_ADDRESS_R=6, ERR_ARBITRATION=7;

    reg scl_low = 0, sda_low = 0;
    (* ASYNC_REG = "TRUE" *) reg [1:0] scl_sync = 2'b11;
    (* ASYNC_REG = "TRUE" *) reg [1:0] sda_sync = 2'b11;
    assign scl = scl_low ? 1'b0 : 1'bz;
    assign sda = sda_low ? 1'b0 : 1'bz;
    always @(posedge clk) begin
        scl_sync <= {scl_sync[0], scl};
        sda_sync <= {sda_sync[0], sda};
    end

    reg [4:0] state = IDLE, after_rise = IDLE;
    reg [31:0] phase_count = 0, wait_count = 0;
    reg [7:0] last_seen = 0, active_token = 0, completed_token = 0;
    reg busy = 0;
    reg [5:0] error_code = 0;
    reg [6:0] address = 0;
    reg [3:0] write_length = 0, read_length = 0;
    reg [63:0] write_data = 0, read_data = 0;
    reg [7:0] acked_write_count = 0;
    reg [7:0] tx_byte = 0;
    reg [2:0] bit_index = 7;
    reg [3:0] write_index = 0, read_index = 0;
    // 0=write address, 1=write payload, 2=read address.
    reg [1:0] tx_kind = 0;
    assign status = {38'b0, sda_sync[1], scl_sync[1],
                     acked_write_count, read_data, error_code,
                     (error_code != 0), busy, completed_token};

    task finish;
        begin
            scl_low <= 0;
            sda_low <= 0;
            completed_token <= active_token;
            busy <= 0;
            state <= IDLE;
        end
    endtask

    // The only path into this task is after finishing an ACK clock low.
    task after_write;
        begin
            phase_count <= 0;
            if (read_length != 0) begin
                state <= RESTART_LOW;
                sda_low <= 0;
                tx_byte <= {address, 1'b1};
                tx_kind <= 2;
                bit_index <= 7;
            end else begin
                state <= STOP_LOW;
                sda_low <= 1;
            end
        end
    endtask

    always @(posedge clk) begin
        if (reset) begin
            state <= IDLE;
            after_rise <= IDLE;
            scl_low <= 0;
            sda_low <= 0;
            phase_count <= 0;
            wait_count <= 0;
            last_seen <= 0;
            active_token <= 0;
            completed_token <= 0;
            busy <= 0;
            error_code <= 0;
            address <= 0;
            write_length <= 0;
            read_length <= 0;
            write_data <= 0;
            read_data <= 0;
            acked_write_count <= 0;
            tx_byte <= 0;
            bit_index <= 7;
            write_index <= 0;
            read_index <= 0;
            tx_kind <= 0;
        end else begin
            case (state)
                IDLE: begin
                    scl_low <= 0;
                    sda_low <= 0;
                    if (command[7:0] != 0 && command[7:0] != last_seen) begin
                        active_token <= command[7:0];
                        last_seen <= command[7:0];
                        address <= command[14:8];
                        write_length <= command[18:15];
                        read_length <= command[22:19];
                        write_data <= command[86:23];
                        read_data <= 0;
                        acked_write_count <= 0;
                        error_code <= 0;
                        write_index <= 0;
                        read_index <= 0;
                        tx_byte <= {command[14:8], 1'b0};
                        tx_kind <= 0;
                        bit_index <= 7;
                        phase_count <= 0;
                        wait_count <= 0;
                        busy <= 1;
                        state <= CHECK_BUS;
                    end
                end
                CHECK_BUS: begin
                    // Remain entirely released until a full idle half-period.
                    if (write_length > 8 || read_length > 8) begin
                        error_code <= ERR_LENGTH;
                        finish;
                    end else if (wait_count >= TIMEOUT_CYCLES-1) begin
                        error_code <= ERR_BUSY;
                        finish;
                    end else if (scl_sync[1] && sda_sync[1]) begin
                        if (phase_count == HALF_CYCLES-1) begin
                            sda_low <= 1;
                            phase_count <= 0;
                            state <= START_HOLD;
                        end else phase_count <= phase_count + 1'b1;
                        wait_count <= wait_count + 1'b1;
                    end else begin
                        phase_count <= 0;
                        wait_count <= wait_count + 1'b1;
                    end
                end
                START_HOLD: begin
                    if (phase_count == HALF_CYCLES-1) begin
                        scl_low <= 1;
                        phase_count <= 0;
                        state <= TX_LOW;
                    end else phase_count <= phase_count + 1'b1;
                end
                TX_LOW: begin
                    sda_low <= !tx_byte[bit_index];
                    if (phase_count == HALF_CYCLES-1) begin
                        scl_low <= 0;
                        wait_count <= 0;
                        after_rise <= TX_HIGH;
                        state <= WAIT_RISE;
                    end else phase_count <= phase_count + 1'b1;
                end
                TX_HIGH: begin
                    if (phase_count == HALF_CYCLES-1) begin
                        phase_count <= 0;
                        if (tx_byte[bit_index] && !sda_sync[1]) begin
                            // Another device holds SDA low: relinquish the bus.
                            error_code <= ERR_ARBITRATION;
                            finish;
                        end else begin
                            scl_low <= 1;
                            if (bit_index == 0) state <= ACK_LOW;
                            else begin
                                bit_index <= bit_index - 1'b1;
                                state <= TX_LOW;
                            end
                        end
                    end else phase_count <= phase_count + 1'b1;
                end
                ACK_LOW: begin
                    sda_low <= 0;
                    if (phase_count == HALF_CYCLES-1) begin
                        scl_low <= 0;
                        wait_count <= 0;
                        after_rise <= ACK_HIGH;
                        state <= WAIT_RISE;
                    end else phase_count <= phase_count + 1'b1;
                end
                ACK_HIGH: begin
                    if (phase_count == HALF_CYCLES-1) begin
                        scl_low <= 1;
                        phase_count <= 0;
                        bit_index <= 7;
                        if (sda_sync[1]) begin
                            case (tx_kind)
                                0: error_code <= ERR_ADDRESS_W;
                                1: error_code <= ERR_WRITE;
                                2: error_code <= ERR_ADDRESS_R;
                            endcase
                            state <= STOP_LOW;
                        end else if (tx_kind == 0) begin
                            if (write_length != 0) begin
                                tx_byte <= write_data[7:0];
                                tx_kind <= 1;
                                state <= TX_LOW;
                            end else after_write;
                        end else if (tx_kind == 1) begin
                            acked_write_count <= acked_write_count + 1'b1;
                            if (write_index + 1 < write_length) begin
                                write_index <= write_index + 1'b1;
                                write_data <= write_data >> 8;
                                tx_byte <= write_data[15:8];
                                state <= TX_LOW;
                            end else after_write;
                        end else begin
                            state <= RX_LOW;
                            read_index <= 0;
                        end
                    end else phase_count <= phase_count + 1'b1;
                end
                RESTART_LOW: begin
                    sda_low <= 0;
                    if (phase_count == HALF_CYCLES-1) begin
                        scl_low <= 0;
                        wait_count <= 0;
                        after_rise <= RESTART_HIGH;
                        state <= WAIT_RISE;
                    end else phase_count <= phase_count + 1'b1;
                end
                RESTART_HIGH: begin
                    if (phase_count == HALF_CYCLES-1) begin
                        sda_low <= 1;
                        phase_count <= 0;
                        state <= START_HOLD;
                    end else phase_count <= phase_count + 1'b1;
                end
                RX_LOW: begin
                    sda_low <= 0;
                    if (phase_count == HALF_CYCLES-1) begin
                        scl_low <= 0;
                        wait_count <= 0;
                        after_rise <= RX_HIGH;
                        state <= WAIT_RISE;
                    end else phase_count <= phase_count + 1'b1;
                end
                RX_HIGH: begin
                    if (phase_count == HALF_CYCLES-1) begin
                        read_data[read_index*8 + bit_index] <= sda_sync[1];
                        scl_low <= 1;
                        phase_count <= 0;
                        if (bit_index == 0) state <= RX_ACK_LOW;
                        else begin
                            bit_index <= bit_index - 1'b1;
                            state <= RX_LOW;
                        end
                    end else phase_count <= phase_count + 1'b1;
                end
                RX_ACK_LOW: begin
                    sda_low <= (read_index + 1 < read_length);
                    if (phase_count == HALF_CYCLES-1) begin
                        scl_low <= 0;
                        wait_count <= 0;
                        after_rise <= RX_ACK_HIGH;
                        state <= WAIT_RISE;
                    end else phase_count <= phase_count + 1'b1;
                end
                RX_ACK_HIGH: begin
                    if (phase_count == HALF_CYCLES-1) begin
                        scl_low <= 1;
                        phase_count <= 0;
                        if (read_index + 1 < read_length) begin
                            read_index <= read_index + 1'b1;
                            bit_index <= 7;
                            state <= RX_LOW;
                        end else state <= STOP_LOW;
                    end else phase_count <= phase_count + 1'b1;
                end
                STOP_LOW: begin
                    scl_low <= 1;
                    sda_low <= 1;
                    if (phase_count == HALF_CYCLES-1) begin
                        scl_low <= 0;
                        wait_count <= 0;
                        after_rise <= STOP_HIGH;
                        state <= WAIT_RISE;
                    end else phase_count <= phase_count + 1'b1;
                end
                STOP_HIGH: begin
                    if (phase_count == HALF_CYCLES-1) begin
                        sda_low <= 0;
                        phase_count <= 0;
                        state <= STOP_RELEASE;
                    end else phase_count <= phase_count + 1'b1;
                end
                STOP_RELEASE: begin
                    if (phase_count == HALF_CYCLES-1) finish;
                    else phase_count <= phase_count + 1'b1;
                end
                WAIT_RISE: begin
                    if (scl_sync[1]) begin
                        phase_count <= 0;
                        state <= after_rise;
                    end else if (wait_count == TIMEOUT_CYCLES-1) begin
                        if (error_code == 0) error_code <= ERR_STRETCH;
                        if (after_rise == STOP_HIGH) finish;
                        else begin
                            // Attempt a STOP; a second timeout releases both pins.
                            scl_low <= 1;
                            sda_low <= 1;
                            phase_count <= 0;
                            state <= STOP_LOW;
                        end
                    end else wait_count <= wait_count + 1'b1;
                end
                default: begin
                    error_code <= ERR_BUSY;
                    finish;
                end
            endcase
        end
    end
endmodule
