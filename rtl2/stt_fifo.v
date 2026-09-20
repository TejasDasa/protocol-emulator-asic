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
`ifdef BREAK_P4A
  // Negative test only: `full` without the wrap-bit check, so an empty FIFO
  // also reports full. This is the classic single-pointer-bit mistake.
  assign full  = (wa == ra);
`else
  assign full  = (wa == ra) && (wptr[AW] != rptr[AW]);
`endif

`ifdef BREAK_P4B
  // Negative test only: a push is accepted even when full, so the FIFO holds
  // more than its depth and overwrites an unread entry.
  wire do_wr = wr_en;
`else
  wire do_wr = wr_en & ~full;
`endif
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
`ifdef BREAK_P4C
      // Negative test only: the overflow flag tracks the current cycle instead
      // of latching, so a host that polls a cycle late never sees the loss.
      ovf_q <= wr_en & full;
`else
      if (wr_en & full)  ovf_q <= 1'b1;
`endif
      if (rd_en & empty) unf_q <= 1'b1;
    end
  end

  assign rd_data = mem[ra];
  assign ovf     = ovf_q;
  assign unf     = unf_q;

// ---------------------------------------------------------------------------
// Formal properties. Guarded so synthesis never parses them. See docs/formal.md.
// ---------------------------------------------------------------------------
`ifdef FORMAL

  reg f_past_valid = 1'b0;
  always @(posedge clk) f_past_valid <= 1'b1;
  always @(posedge clk) if (!f_past_valid) assume (!rst_n);

`ifdef P4_COMMON
  // P4 -- FIFO state consistency (SPEC section 9).
  //
  // The occupancy is not a signal in the design; the pointers are, and the
  // whole point of the extra pointer bit is that their difference is the
  // occupancy. Computing it here is what lets the flags be checked against
  // something rather than against themselves.
  wire [AW:0] f_count = wptr - rptr;

`endif

`ifdef P4_A
  // (a) it never holds more than it has room for.
  //
  // Checked from the first clock edge, not before it. These are claims about
  // REACHABLE states; at time zero the pointers hold whatever the flops
  // powered up with and no reset has run yet, so an unguarded combinational
  // assertion here fails on a state the design can never be in during
  // operation. That is not the same as weakening it: every state after the
  // first edge is still checked, and the first edge applies reset.
  always @(posedge clk) if (f_past_valid) assert (f_count <= DEPTH);
`endif

`ifdef P4_B
  // (b) the flags say exactly what it holds -- the "never reports not-empty
  //     when empty, never not-full when full" claim, in both directions, so a
  //     flag that is merely conservative also fails.
  always @(posedge clk) if (f_past_valid) begin
    assert (empty == (f_count == 0));
    assert (full  == (f_count == DEPTH));
    assert (!(empty && full));
  end
`endif

`ifdef P4_C
  // (c) overflow and underflow are no-ops that set a flag, not errors.
  always @(posedge clk) if (f_past_valid && rst_n && $past(rst_n)
                            && $past(wr_en) && $past(full) && !$past(rd_en)) begin
    assert (wptr == $past(wptr));
    assert (f_count == $past(f_count));
    assert (ovf);
  end
  always @(posedge clk) if (f_past_valid && rst_n && $past(rst_n)
                            && $past(rd_en) && $past(empty) && !$past(wr_en)) begin
    assert (rptr == $past(rptr));
    assert (f_count == $past(f_count));
    assert (unf);
  end

`endif

`ifdef P4_D
  // (d) the flags are sticky: nothing but reset clears them.
  always @(posedge clk) if (f_past_valid && rst_n && $past(rst_n)) begin
    if ($past(ovf)) assert (ovf);
    if ($past(unf)) assert (unf);
  end
`endif

`endif
endmodule
`default_nettype wire
