// stt_fifo -- one byte FIFO, parameterized depth.
//
// Depth is a parameter because the right value depends on how fast a host can
// service it, and that is not yet measurable -- there is no host. SPEC section 9
// pins the default at 4 and records the arithmetic behind it.
//
// OVERFLOW AND UNDERFLOW ARE NOT ERRORS, THEY ARE NO-OPS. A push onto a full
// FIFO leaves it unchanged and drops the byte; a pop from an empty one leaves it
// unchanged and returns nothing. That is the same rule SPEC section 9 already
// gives for `load` from an empty TX FIFO -- an action that cannot be performed
// is not performed -- rather than two special cases. Stalling is not available:
// SPEC section 8.1 says a row costs exactly one cycle and a machine never
// stalls. Dropping the OLDEST instead would silently corrupt an in-order byte
// stream, which is worse than losing the newest and saying so.
//
// Both events set a sticky flag so the loss is detectable rather than silent.
// The flags clear on reset only.
`default_nettype none

module stt_fifo #(
    parameter WIDTH = 8,
    parameter DEPTH = 4                 // must be a power of two
) (
    input  wire              clk,
    input  wire              rst_n,

    input  wire              wr_en,
    input  wire [WIDTH-1:0]  wr_data,
    input  wire              rd_en,
    output wire [WIDTH-1:0]  rd_data,

    output wire              empty,
    output wire              full,
    output wire              ovf,       // sticky: a push was dropped
    output wire              unf        // sticky: a pop found it empty
);

  localparam integer AW = (DEPTH > 1) ? $clog2(DEPTH) : 1;

  reg [WIDTH-1:0] mem [0:DEPTH-1];
  reg [AW:0]      wptr, rptr;           // one extra bit distinguishes full/empty
  reg             ovf_q, unf_q;

  wire [AW-1:0] wa = wptr[AW-1:0];
  wire [AW-1:0] ra = rptr[AW-1:0];

  assign empty = (wptr == rptr);
  assign full  = (wa == ra) && (wptr[AW] != rptr[AW]);

  wire do_wr = wr_en & ~full;
  wire do_rd = rd_en & ~empty;

  integer i;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wptr  <= {(AW+1){1'b0}};
      rptr  <= {(AW+1){1'b0}};
      ovf_q <= 1'b0;
      unf_q <= 1'b0;
      for (i = 0; i < DEPTH; i = i + 1)
        mem[i] <= {WIDTH{1'b0}};
    end else begin
      if (do_wr) begin
        mem[wa] <= wr_data;
        wptr    <= wptr + 1'b1;
      end
      if (do_rd) rptr <= rptr + 1'b1;
      if (wr_en & full)  ovf_q <= 1'b1;
      if (rd_en & empty) unf_q <= 1'b1;
    end
  end

  assign rd_data = mem[ra];
  assign ovf     = ovf_q;
  assign unf     = unf_q;

endmodule
`default_nettype wire
