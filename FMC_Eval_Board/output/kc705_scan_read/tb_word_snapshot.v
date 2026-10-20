`timescale 1ns/1ps
module tb_word_snapshot;
    reg source_clk=0, destination_clk=0, source_valid=0;
    reg [59:0] source_words=0;
    wire [59:0] destination_words;
    wire destination_valid;
    adc_word_snapshot dut(.*);
    always #8.333 source_clk=~source_clk;
    initial begin #1.25; forever #2.5 destination_clk=~destination_clk; end
    reg [59:0] expected[0:99];
    integer sent=0, received=0;
    integer k;
    always @(posedge source_clk) begin
        if (source_valid) begin expected[sent]=source_words; sent=sent+1; end
    end
    always @(negedge destination_clk) begin
        if (destination_valid) begin
            if(received >= sent || destination_words !== expected[received])
                $fatal(1,"Snapshot dropped, reordered, or mixed packet %d",received);
            received=received+1;
        end
    end
    initial begin
        #80;
        for(k=0;k<100;k=k+1) begin
            @(negedge source_clk);
            source_words={$random,$random}; source_valid=1;
            @(negedge source_clk); source_valid=0;
            repeat(4) @(negedge source_clk);
        end
        #200;
        if(received!=100 || destination_valid) $fatal(1,"Wrong final packet count");
        $display("ADC_WORD_SNAPSHOT_100_PACKETS_COHERENT_PASS");
        $finish;
    end
endmodule
