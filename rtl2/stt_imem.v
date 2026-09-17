// stt_imem -- 32 rows of 32 bits with an ASYNCHRONOUS read, plus the serial
// load path that surrounds it.
//
// SPEC section 12: the read is asynchronous, which is what allows one row per
// cycle with no fetch stage (section 8.1). Confirmed from the macro's own
// liberty rather than from how RTL models it: CFGMEM_IHP16 has no CLK pin, no
// ff() or latch() groups, and all 224 timing arcs are timing_type
// combinational, with the data outputs driven combinationally from the address.
// Worst address-to-data delay in the typical tables is 1.994 ns.
//
// This pass uses a behavioural array rather than two CFGMEM_IHP16 macros. The
// load path is NOT behavioural -- the staging register, bit counter and write
// pointer are exactly the logic section 12 says the tiles do not provide, so
// they are built here and swapping the array for the macros must not change
// behaviour.
//
// Load protocol: hold `ld_en` and present one bit per cycle on `ld_in`, LSB of
// the row first. Every 32 bits completes a row, which is written at the write
// pointer, and the pointer advances. The pointer is ADDR_W bits and wraps, so a
// 33rd row overwrites row 0 (SPEC section 12, CURRENT BEHAVIOUR).
`default_nettype none
`include "stt_isa.vh"

module stt_imem #(
    parameter ROW_W  = `STT_ROW_W,
    parameter ROWS   = `STT_ROWS,
    parameter ADDR_W = `STT_ADDR_W
) (
    input  wire               clk,
    input  wire               rst_n,

    input  wire [ADDR_W-1:0]  addr,
    output wire [ROW_W-1:0]   row,

    input  wire               ld_en,
    input  wire               ld_in,
    output wire               ld_out,
    output wire [ADDR_W-1:0]  ld_addr,
    // Tied low: the behavioural array writes in one cycle and needs no pause.
    // The CFGMEM version has to walk a one-hot enable down the chain and does.
    output wire               ld_busy
);

  localparam integer BITC_W = $clog2(ROW_W);

  reg [ROW_W-1:0] mem [0:ROWS-1];
  reg [ROW_W-1:0] stage;
  reg [BITC_W-1:0] bitc;
  reg [ADDR_W-1:0] wptr;

  wire [ROW_W-1:0] stage_next = {ld_in, stage[ROW_W-1:1]};
  wire             last_bit   = (bitc == BITC_W'(ROW_W - 1));

  integer i;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      stage <= {ROW_W{1'b0}};
      bitc  <= {BITC_W{1'b0}};
      wptr  <= {ADDR_W{1'b0}};
      for (i = 0; i < ROWS; i = i + 1)
        mem[i] <= {ROW_W{1'b0}};
    end else if (ld_en) begin
      stage <= stage_next;
      bitc  <= last_bit ? {BITC_W{1'b0}} : bitc + 1'b1;
      if (last_bit) begin
        mem[wptr] <= stage_next;
        wptr      <= wptr + 1'b1;
      end
    end
  end

  // SPEC section 12: asynchronous read.
  assign row     = mem[addr];
  assign ld_out  = stage[0];
  assign ld_addr = wptr;
  assign ld_busy = 1'b0;

endmodule
`default_nettype wire
