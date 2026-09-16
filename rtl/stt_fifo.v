// stt_fifo -- parameterized synchronous FIFO, flop-based storage.
//
// Structural size model for the A6 question: does the TX/RX buffering live
// inside each state machine (replicated per SM) or once at the chip boundary?
// Storage is a DEPTH x W flop array with head/tail pointers and a level
// counter, which is what a small FIFO at this depth actually synthesizes to.
`default_nettype none

module stt_fifo #(
    parameter W     = 8,
    parameter DEPTH = 4
) (
    input  wire         clk,
    input  wire         rst_n,

    input  wire         wr_en,
    input  wire [W-1:0] wr_data,
    input  wire         rd_en,
    output wire [W-1:0] rd_data,

    output wire         ne,        // not empty -> drives the `fifo` test
    output wire         full,
    output wire [W-1:0] level_o    // observable, keeps the counter alive
);

  function integer clog2;
    input integer value;
    integer v;
    begin
      v = value - 1;
      clog2 = 0;
      while (v > 0) begin
        clog2 = clog2 + 1;
        v = v >> 1;
      end
    end
  endfunction

  localparam integer AW = clog2(DEPTH);

  reg [W-1:0]  mem [0:DEPTH-1];
  reg [AW-1:0] head;          // read pointer
  reg [AW-1:0] tail;          // write pointer
  reg [AW:0]   level;

  wire do_wr = wr_en && !full;
  wire do_rd = rd_en && ne;

  integer i;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      head  <= {AW{1'b0}};
      tail  <= {AW{1'b0}};
      level <= {(AW+1){1'b0}};
      for (i = 0; i < DEPTH; i = i + 1)
        mem[i] <= {W{1'b0}};
    end else begin
      if (do_wr) begin
        mem[tail] <= wr_data;
        tail      <= (tail == (DEPTH-1)) ? {AW{1'b0}} : (tail + 1'b1);
      end
      if (do_rd)
        head <= (head == (DEPTH-1)) ? {AW{1'b0}} : (head + 1'b1);

      case ({do_wr, do_rd})
        2'b10:   level <= level + 1'b1;
        2'b01:   level <= level - 1'b1;
        default: level <= level;
      endcase
    end
  end

  assign rd_data = mem[head];
  assign ne      = (level != {(AW+1){1'b0}});
  assign full    = (level == DEPTH[AW:0]);
  assign level_o = {{(W-AW-1){1'b0}}, level};

endmodule
`default_nettype wire
