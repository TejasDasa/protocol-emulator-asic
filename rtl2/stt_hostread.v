// stt_hostread -- reads bytes out of a machine's RX FIFO over the SPEC 11.2
// host byte port, and says whether they are the byte we expect.
//
// FPGA BRING-UP INFRASTRUCTURE. Not part of the ASIC submission.
//
// The UART RX reference program declares no output slots: it reads in0 and
// pushes. So the received byte exists in exactly one place a pin can reach --
// the RX FIFO, via the host port -- and without this module a loopback test
// on hardware has nothing to look at.
//
// SPEC 11.2 frame, 16 clocks with the strobe held high:
//   in   [15:13] sel  [12] wr  [11:4] data  [3:0] pad
//   out  [15:12] 0    [11:4] rxdata        [3:0] {rx_ne, tx_full, rx_ovf, tx_unf}
//
// A read is wr=0. The chip pops only what the host actually saw, so a frame
// issued when the FIFO is empty returns rx_ne=0 and consumes nothing.
`default_nettype none

module stt_hostread #(
    parameter integer GAP = 8            // idle clocks between frames
) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       start,             // hold high once the loader is done
    input  wire [2:0] sel,               // which machine's RX FIFO
    input  wire [7:0] expect_byte,
    input  wire       dout,              // the host port's data-out pin

    output wire       stb,               // -> the pin the chain named host_stb
    output wire       din,               // -> the pin the chain named host_din
    output reg  [7:0] last_byte,
    output reg        last_valid,        // rx_ne of the last frame
    output reg  [3:0] last_status,
    output reg [31:0] good_count,        // frames that returned the right byte
    output reg [31:0] bad_count          // frames that returned a wrong one
);

    localparam [15:0] FRAME_PAD = 16'h0000;

    // sel occupies [15:13], wr is [12] and is 0 for a read, data [11:4] is
    // ignored on a read.
    wire [15:0] word = {sel, 1'b0, 8'h00, 4'h0} | FRAME_PAD;

    reg [4:0]  cnt;                      // 0..15 in a frame, then the gap
    reg        active;
    reg [15:0] resp;
    reg [7:0]  gapc;

    assign stb = active;
    assign din = word[15 - cnt[3:0]];

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt         <= 5'd0;
            active      <= 1'b0;
            resp        <= 16'd0;
            gapc        <= 8'd0;
            last_byte   <= 8'd0;
            last_valid  <= 1'b0;
            last_status <= 4'd0;
            good_count  <= 32'd0;
            bad_count   <= 32'd0;
        end else if (!start) begin
            active <= 1'b0;
            cnt    <= 5'd0;
            gapc   <= 8'd0;
        end else if (active) begin
            // The response bit for the step just presented arrives with this
            // edge, so shifting here keeps the frame and the reply aligned.
            resp <= {resp[14:0], dout};
            if (cnt == 5'd15) begin
                active <= 1'b0;
                cnt    <= 5'd0;
                gapc   <= GAP[7:0];
            end else begin
                cnt <= cnt + 5'd1;
            end
        end else if (gapc != 8'd0) begin
            gapc <= gapc - 8'd1;
            if (gapc == 8'd1) begin
                // resp holds the whole reply now: {4'b0, rxdata, status}.
                last_status <= resp[3:0];
                last_byte   <= resp[11:4];
                last_valid  <= resp[3];          // rx_ne
                if (resp[3]) begin
                    if (resp[11:4] == expect_byte) good_count <= good_count + 1;
                    else                           bad_count  <= bad_count + 1;
                end
            end
        end else begin
            active <= 1'b1;
            cnt    <= 5'd0;
        end
    end

endmodule

`default_nettype wire
