`timescale 1ns/1ps
module tb_kc705_vadj_bridge;
    reg clk = 0;
    always #2.5 clk = !clk;
    reg reset = 1;
    reg [127:0] command = 0;
    wire [127:0] status;
    tri1 scl, sda;
    reg slave_sda_low = 0, slave_scl_low = 0;
    assign sda = slave_sda_low ? 1'b0 : 1'bz;
    assign scl = slave_scl_low ? 1'b0 : 1'bz;
    pmbus_transaction_bridge #(.TIMEOUT_CYCLES(4000)) dut (
        .clk(clk), .reset(reset), .command(command), .status(status),
        .scl(scl), .sda(sda)
    );
    integer starts = 0, stops = 0, failures = 0;
    integer starts_before, stops_before;
    always @(negedge sda) if (scl === 1'b1 && !reset) starts = starts + 1;
    always @(posedge sda) if (scl === 1'b1 && !reset) stops = stops + 1;

    task check;
        input condition;
        input [1023:0] description;
        begin
            if (!condition) begin
                $display("FAIL %0t: %0s", $time, description);
                failures = failures + 1;
            end else $display("PASS %0t: %0s", $time, description);
        end
    endtask

    task issue;
        input [7:0] token;
        input [3:0] wlen, rlen;
        input [63:0] payload;
        begin
            @(negedge clk);
            command = 0;
            command[7:0] = token;
            command[14:8] = 7'h52;
            command[18:15] = wlen;
            command[22:19] = rlen;
            command[86:23] = payload;
        end
    endtask
    task wait_done;
        input [7:0] token;
        input [5:0] expected_error;
        begin
            wait (status[7:0] == token && status[8] == 0);
            #100;
            check(status[15:10] == expected_error, "completion error code");
            check(status[9] == (expected_error != 0), "error flag consistent");
        end
    endtask
    task wait_start;
        begin : waiting_start
            forever begin
                @(negedge sda);
                if (scl === 1'b1) disable waiting_start;
            end
        end
    endtask
    task wait_stop;
        begin : waiting_stop
            forever begin
                @(posedge sda);
                if (scl === 1'b1) disable waiting_stop;
            end
        end
    endtask
    task receive_byte;
        input [7:0] expected;
        input ack;
        reg [7:0] received;
        integer bitn;
        begin
            for (bitn = 7; bitn >= 0; bitn = bitn - 1) begin
                @(posedge scl);
                #1 received[bitn] = sda;
            end
            check(received == expected, "slave received expected byte");
            @(negedge scl);
            #1 slave_sda_low = ack;
            @(posedge scl);
            @(negedge scl);
            #1 slave_sda_low = 0;
        end
    endtask
    task send_byte;
        input [7:0] value;
        input expected_ack;
        integer bitn;
        begin
            for (bitn = 7; bitn >= 0; bitn = bitn - 1) begin
                slave_sda_low = !value[bitn];
                @(posedge scl);
                @(negedge scl);
                #1;
            end
            slave_sda_low = 0;
            @(posedge scl);
            #1 check(sda == !expected_ack, "master ACK/NACK read byte");
            @(negedge scl);
            #1;
        end
    endtask

    initial begin
        #100 reset = 0;
        #50000;
        check(starts == 0 && stops == 0, "startup emits no bus transaction");
        check(scl === 1'b1 && sda === 1'b1 && !status[8], "startup bus released");

        // Read a Linear16-like two-byte value with a repeated START.
        starts_before = starts;
        stops_before = stops;
        fork
            begin
                wait_start;
                receive_byte(8'ha4, 1);
                receive_byte(8'h8b, 1);
                wait_start;
                receive_byte(8'ha5, 1);
                send_byte(8'hcd, 1);
                send_byte(8'hab, 0);
                wait_stop;
            end
            begin
                issue(1, 1, 2, 64'h8b);
                wait_done(1, 0);
            end
        join
        check(status[79:16] == 64'habcd, "read bytes packed least significant byte first");
        check(status[87:80] == 1, "only payload bytes counted as ACKed writes");
        check(starts-starts_before == 2 && stops-stops_before == 1, "combined read has repeated START and one STOP");
        #50000;
        check(starts-starts_before == 2, "unchanged token does not retrigger");

        // Eight-byte writes test the shift order and bound.
        fork
            begin
                wait_start;
                receive_byte(8'ha4, 1);
                receive_byte(8'h01, 1); receive_byte(8'h23, 1);
                receive_byte(8'h45, 1); receive_byte(8'h67, 1);
                receive_byte(8'h89, 1); receive_byte(8'hab, 1);
                receive_byte(8'hcd, 1); receive_byte(8'hef, 1);
                wait_stop;
            end
            begin
                issue(2, 8, 0, 64'hefcdab8967452301);
                wait_done(2, 0);
            end
        join
        check(status[87:80] == 8, "all eight payload writes ACKed");

        // NACK at address, write byte, and repeated read address.
        fork
            begin wait_start; receive_byte(8'ha4, 0); wait_stop; end
            begin issue(3, 1, 0, 64'h21); wait_done(3, 4); end
        join
        check(status[87:80] == 0, "address NACK does not count data ACKs");
        fork
            begin wait_start; receive_byte(8'ha4, 1); receive_byte(8'h21, 0); wait_stop; end
            begin issue(4, 1, 0, 64'h21); wait_done(4, 5); end
        join
        fork
            begin
                wait_start; receive_byte(8'ha4, 1); receive_byte(8'h8b, 1);
                wait_start; receive_byte(8'ha5, 0); wait_stop;
            end
            begin issue(5, 1, 2, 64'h8b); wait_done(5, 6); end
        join

        // Stretch a clock for longer than its nominal low period, below timeout.
        fork
            begin
                wait_start; receive_byte(8'ha4, 1); receive_byte(8'h79, 1); wait_stop;
            end
            begin
                wait_start;
                @(negedge scl);
                slave_scl_low = 1;
                #15000 slave_scl_low = 0;
            end
            begin issue(6, 1, 0, 64'h79); wait_done(6, 0); end
        join
        check(scl && sda, "clock stretch completes with released bus");

        // Stuck SCL during transaction: bounded failure, release both drivers.
        fork
            begin
                wait_start; @(negedge scl); slave_scl_low = 1;
            end
            begin issue(7, 1, 0, 64'h21); wait_done(7, 3); end
        join
        check(dut.scl_low == 0 && dut.sda_low == 0, "SCL timeout releases both master drivers");
        slave_scl_low = 0;
        #1000;

        // Initial bus busy must not drive the bus or produce recovery clocks.
        slave_sda_low = 1;
        #100;
        starts_before = starts;
        issue(8, 1, 0, 64'h21);
        wait_done(8, 2);
        check(dut.scl_low == 0 && dut.sda_low == 0, "bus-busy failure never drives lines");
        check(starts == starts_before, "busy bus produces no START");
        slave_sda_low = 0;
        #1000;
        starts_before = starts;
        issue(9, 9, 0, 0);
        wait_done(9, 1);
        check(starts == starts_before, "invalid length produces no START");
        issue(0, 1, 0, 64'h21);
        #50000;
        check(starts == starts_before, "token zero never executes");

        // Exact read and write command forms used for the controller audit.
        fork
            begin
                wait_start; receive_byte(8'ha4, 1); receive_byte(8'h21, 1);
                wait_start; receive_byte(8'ha5, 1);
                send_byte(8'h00, 1); send_byte(8'h28, 0); wait_stop;
            end
            begin issue(10, 1, 2, 64'h21); wait_done(10, 0); end
        join
        check(status[79:16] == 64'h2800, "VOUT_COMMAND word uses little-endian 0x2800");
        fork
            begin
                wait_start; receive_byte(8'ha4, 1);
                receive_byte(8'h00, 1); receive_byte(8'h03, 1); wait_stop;
            end
            begin issue(11, 2, 0, 64'h0300); wait_done(11, 0); end
        join
        check(status[87:80] == 2, "PAGE write 00 03 ACK count");
        fork
            begin
                wait_start; receive_byte(8'ha4, 1);
                receive_byte(8'h21, 1); receive_byte(8'hcd, 1);
                receive_byte(8'h1c, 1); wait_stop;
            end
            begin issue(12, 3, 0, 64'h1ccd21); wait_done(12, 0); end
        join
        check(status[87:80] == 3, "word write 21 cd 1c ACK count");
        fork
            begin
                wait_start; receive_byte(8'ha4, 1); receive_byte(8'h9a, 1);
                wait_start; receive_byte(8'ha5, 1);
                send_byte(8'h08, 1); send_byte(8'h01, 1);
                send_byte(8'h23, 1); send_byte(8'h45, 1);
                send_byte(8'h67, 1); send_byte(8'h89, 1);
                send_byte(8'hab, 1); send_byte(8'hcd, 0); wait_stop;
            end
            begin issue(13, 1, 8, 64'h9a); wait_done(13, 0); end
        join
        check(status[79:16] == 64'hcdab896745230108, "all eight read bytes packed in order");

        if (failures == 0) $display("ALL TESTS PASSED");
        else $display("TESTS FAILED: %0d", failures);
        $finish;
    end
    initial begin
        #10000000;
        $display("FAIL testbench timeout at %0t", $time);
        $finish;
    end
endmodule
