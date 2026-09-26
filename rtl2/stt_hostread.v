// stt_hostread -- drives the SPEC 11.2 host byte port: feeds one machine's TX
// FIFO and checks what comes out of another machine's RX FIFO.
//
// FPGA BRING-UP INFRASTRUCTURE. Not part of the ASIC submission.
//
// Two jobs, because two reference programs need them. A receive program
// declares no output slots -- it reads a pin and pushes -- so the only place
// a received byte can be seen is its RX FIFO. And `usb_ls_token_tx` takes
// three DIFFERENT bytes through `load`, which `loadk` cannot supply, so
// something has to write its TX FIFO.
//
// SPEC 11.2 frame, 16 clocks with the strobe held high:
//   in   [15:13] sel  [12] wr  [11:4] data  [3:0] pad
//   out  [15:12] 0    [11:4] rxdata        [3:0] {rx_ne, tx_full, rx_ovf, tx_unf}
//
// A write onto a full TX FIFO is dropped and the host is told in the same
// frame (SPEC 11.2), so tx_full means retry the same byte rather than advance.
// A read of an empty RX FIFO returns rx_ne = 0 and pops nothing.
`default_nettype none

module stt_hostread #(
    parameter integer GAP = 8,           // idle clocks between frames
    parameter integer NW  = 1,           // bytes in the write sequence
    parameter integer NR  = 1            // bytes in the expected read sequence
) (
    input  wire            clk,
    input  wire            rst_n,
    input  wire            start,        // hold high once the loader is done
    input  wire            wr_en,        // interleave writes with reads
    input  wire [2:0]      wr_sel,       // machine whose TX FIFO to feed
    input  wire [NW*8-1:0] wr_seq,
    input  wire [2:0]      rd_sel,       // machine whose RX FIFO to drain
    input  wire [NR*8-1:0] rd_seq,       // what its bytes should be, in order
    input  wire [15:0]     wr_gap,       // idle FRAMES after each full write
                                         // sequence -- frames, not clocks; a
                                         // frame is ~24 clocks here
    input  wire            relay_en,     // forward what was read to another machine
    input  wire [2:0]      relay_sel,    // whose TX FIFO to forward it into
    input  wire            dout,         // the host port's data-out pin

    output wire            stb,
    output wire            din,
    output reg  [7:0]      last_byte,
    output reg             last_valid,
    output reg  [3:0]      last_status,
    output reg  [31:0]     good_count,
    output reg  [31:0]     bad_count
);

    reg [4:0]  cnt;
    reg        active, is_wr;
    reg [15:0] resp;
    reg [7:0]  gapc;
    reg [3:0]  wi, ri;
    reg [15:0] pace;
    // One byte in flight from the read machine to the relay machine. The SPI
    // flash test needs this: the bytes the flash sends back arrive in machine
    // 0's RX FIFO and have to reach machine 1's TX FIFO to be printed.
    reg [7:0]  relay_byte;
    reg        relay_full;
    reg [1:0]  phase;

    wire [7:0] wr_byte = wr_seq[wi * 8 +: 8];
    wire [7:0] rd_want = rd_seq[ri * 8 +: 8];
    // Three kinds of frame: feed the write machine, drain the read machine,
    // and forward a drained byte on. `is_wr` selects write-vs-read; `is_rly`
    // makes that write go to the relay machine with the relayed byte.
    reg is_rly;
    wire [2:0] w_sel  = is_rly ? relay_sel  : wr_sel;
    wire [7:0] w_byte = is_rly ? relay_byte : wr_byte;
    wire [15:0] word = is_wr ? {w_sel, 1'b1, w_byte, 4'h0}
                             : {rd_sel, 1'b0, 8'h00, 4'h0};

    assign stb = active;
    assign din = word[15 - cnt[3:0]];

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt <= 5'd0; active <= 1'b0; is_wr <= 1'b0;
            resp <= 16'd0; gapc <= 8'd0; wi <= 4'd0; ri <= 4'd0;
            pace <= 16'd0;
            relay_byte <= 8'd0; relay_full <= 1'b0; phase <= 2'd0;
            is_rly <= 1'b0;
            last_byte <= 8'd0; last_valid <= 1'b0; last_status <= 4'd0;
            good_count <= 32'd0; bad_count <= 32'd0;
        end else if (!start) begin
            active <= 1'b0; cnt <= 5'd0; gapc <= 8'd0;
        end else if (active) begin
            // The reply bit for the step just presented arrives with this
            // edge, so shifting here keeps frame and reply aligned.
            resp <= {resp[14:0], dout};
            if (cnt == 5'd15) begin
                active <= 1'b0; cnt <= 5'd0; gapc <= GAP[7:0];
            end else begin
                cnt <= cnt + 5'd1;
            end
        end else if (gapc != 8'd0) begin
            gapc <= gapc - 8'd1;
            if (gapc == 8'd1) begin
                last_status <= resp[3:0];
                last_byte   <= resp[11:4];
                last_valid  <= resp[3];
                if (is_wr && is_rly) begin
                    // A relayed byte is dropped only if the destination FIFO is
                    // full; keep it and try again rather than losing it.
                    if (!resp[2]) relay_full <= 1'b0;
                end else if (is_wr) begin
                    // resp[2] is tx_full: the byte was dropped, send it again.
                    if (!resp[2]) begin
                        if (wi == NW[3:0] - 4'd1) begin
                            wi   <= 4'd0;
                            // A full sequence is one packet. Go quiet for a
                            // while so the transmitter's FIFO drains and the
                            // LINE GOES IDLE between packets. The USB receiver
                            // cannot see SE0 -- both its inputs are spent, one
                            // on D+ and one on the decoded-bit loopback -- so
                            // it ends a packet by noticing a run of ones longer
                            // than stuffing allows. Back to back there is one
                            // idle bit and that run never builds: the first
                            // packet decodes byte-exact and every one after it
                            // is garbage.
                            pace <= wr_gap;
                        end else begin
                            wi <= wi + 4'd1;
                        end
                    end
                end else if (resp[3]) begin
                    if (resp[11:4] == rd_want) good_count <= good_count + 1;
                    else                       bad_count  <= bad_count + 1;
                    ri <= (ri == NR[3:0] - 4'd1) ? 4'd0 : ri + 4'd1;
                    if (relay_en && !relay_full) begin
                        relay_byte <= resp[11:4];
                        relay_full <= 1'b1;
                    end
                end
            end
        end else if (pace != 16'd0) begin
            // Still pacing: no COMMAND writes, so the transmitter's FIFO drains
            // and its line goes idle. Reads continue, and so do RELAY writes --
            // a relay is draining, not feeding, and suppressing it here strands
            // every byte after the first: the relay slot stays full, and each
            // subsequent read is discarded for want of somewhere to put it.
            pace   <= pace - 16'd1;
            active <= 1'b1;
            cnt    <= 5'd0;
            if (relay_en && relay_full && !(is_wr && is_rly)) begin
                is_wr  <= 1'b1;
                is_rly <= 1'b1;
            end else begin
                is_wr  <= 1'b0;
                is_rly <= 1'b0;
            end
        end else begin
            active <= 1'b1;
            cnt    <= 5'd0;
            // Rotate: feed, drain, forward. A relay frame is only worth a slot
            // when there is a byte waiting, so it is skipped otherwise and the
            // rotation degenerates to the plain write/read alternation the
            // UART and USB tests use.
            if (relay_en && relay_full && !(is_wr && is_rly)) begin
                is_wr  <= 1'b1;
                is_rly <= 1'b1;
            end else begin
                is_rly <= 1'b0;
                is_wr  <= wr_en & ~(is_wr & ~is_rly);
            end
        end
    end

endmodule

`default_nettype wire
