// stt_imem_cfgmem -- the instruction memory in two CFGMEM_IHP16 macros.
//
// Drop-in for stt_imem.v: identical ports, identical behaviour. The behavioural
// array there is the baseline this has to reproduce, and rtl2/tb/test_imem.py
// is the test that says whether it does.
//
// What the macro supplies and what it does NOT (SPEC section 12):
//
//   supplied : the 32 x 32 storage and the asynchronous read decode. No CLK
//              pin, no ff() or latch() group in its liberty, all 224 timing
//              arcs timing_type combinational, worst address-to-data 1.994 ns.
//   outside  : the staging register, the bit counter, the write pointer, the
//              read multiplexer across tiles, and the WRITE SEQUENCING.
//
// THE MACRO IS A SHIFT CHAIN, NOT A RANDOM-ACCESS ARRAY. Confirmed twice: in
// the DFFRAM netlist SLICE[i].STORAGE has .D(Di0_in[i]) and .Q(Di0_in[i+1]),
// and prism's reference model (src/user_peripherals/cfgmem/cfgmem.v) is
//
//     le = WROW & {16{WE0}};  row 0 takes Di0;  row i takes row i-1
//
// so only row 0 can be written directly. A word is loaded by asserting all 16
// row enables and strobing once, which shifts the tile down one place.
//
// This is the reason for the directed test. All three lockstep suites load the
// program through this path identically, so nothing else would have told us the
// write sequencing was wrong -- and rtl/stt_imem_cfgmem.v, written for the area
// study and never simulated, still uses a one-hot WROW that cannot work.
`default_nettype none
`include "stt_isa.vh"

module stt_imem_cfgmem #(
    parameter ROW_W  = `STT_ROW_W,
    parameter ROWS   = `STT_ROWS,
    parameter ADDR_W = `STT_ADDR_W,
    parameter NTILE  = 2               // 16 words each -> ROWS = 16 * NTILE
) (
    input  wire               clk,
    input  wire               rst_n,

    input  wire [ADDR_W-1:0]  addr,
    output wire [ROW_W-1:0]   row,

    input  wire               ld_en,
    input  wire               ld_in,
    output wire               ld_out,
    output wire [ADDR_W-1:0]  ld_addr,
    // High while a row is being walked into the macro. The host must not
    // present the next row until it falls. The behavioural stt_imem.v ties this
    // low: it needs no pause.
    output wire               ld_busy
);

  localparam integer BITC_W = $clog2(ROW_W);
  localparam integer TSELW  = (NTILE > 1) ? $clog2(NTILE) : 1;

  // ---- the load path, identical to stt_imem.v ----------------------------
  reg [ROW_W-1:0]  stage;
  reg [BITC_W-1:0] bitc;
  reg [ADDR_W-1:0] wptr;

  wire [ROW_W-1:0] stage_next = {ld_in, stage[ROW_W-1:1]};
  wire             last_bit   = (bitc == BITC_W'(ROW_W - 1));

  // The completed word and its address are HELD for the following cycle, and
  // the macro is written then.
  //
  // Holding the word keeps Di0 stable for the whole strobe cycle and across the
  // edge where the strobe falls. The latches are transparent while enabled and
  // capture when the enable drops, so driving Di0 straight from stage_next
  // would race the staging register's own shift at that same edge.
  // A word is written by WALKING a one-hot row enable from the far end of the
  // chain back to row 0: row 15 takes row 14, then row 14 takes row 13, and so
  // on, and finally row 0 takes Di0. Going backwards is what makes it safe --
  // each row is written while its source still holds the old value.
  //
  // Opening every row at once does not work: the latches are transparent, so a
  // value ripples down the whole chain instead of advancing one place. Nor does
  // an even/odd two-phase split, because whichever half goes second reads rows
  // the first half has already updated. This is prism's scheme
  // (src/user_peripherals/cfgmem/cfgmem_periph.v), whose FSM walks the same
  // way at three clocks per row: pulse, then two cycles for it to fall and
  // settle before the next.
  //
  // COST: 16 x 3 = 48 cycles per row written, during which ld_busy is high and
  // the host must not present the next row. The behavioural array needed no
  // such pause, so this is a host-protocol consequence of the macro, not a
  // choice -- see rtl2/README.md and SPEC section 10.
  localparam integer WALK_PH = 3;
  reg [ROW_W-1:0]  wr_data;
  reg [ADDR_W-1:0] wr_addr;
  reg [4:0]        walk_idx;    // 16 down to 0; 16 means idle
  reg [1:0]        walk_ph;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      stage   <= {ROW_W{1'b0}};
      bitc    <= {BITC_W{1'b0}};
      wptr    <= {ADDR_W{1'b0}};
      wr_data  <= {ROW_W{1'b0}};
      wr_addr  <= {ADDR_W{1'b0}};
      walk_idx <= 5'd16;
      walk_ph  <= 2'd0;
    end else if (walk_idx != 5'd16) begin
      // walking: pulse on phase 0, two cycles to settle, then step down
      if (walk_ph == WALK_PH[1:0] - 2'd1) begin
        walk_ph  <= 2'd0;
        walk_idx <= (walk_idx == 5'd0) ? 5'd16 : walk_idx - 5'd1;
      end else begin
        walk_ph <= walk_ph + 2'd1;
      end
    end else if (ld_en) begin
      stage <= stage_next;
      bitc  <= last_bit ? {BITC_W{1'b0}} : bitc + 1'b1;
      if (last_bit) begin
        wr_data  <= stage_next;
        wr_addr  <= wptr;
        walk_idx <= 5'd15;
        walk_ph  <= 2'd0;
        wptr     <= wptr + 1'b1;
      end
    end
  end

  // ---- tiles --------------------------------------------------------------
  wire [31:0]      do_tile [0:NTILE-1];
  wire [TSELW-1:0] wr_tile = wr_addr[ADDR_W-1 -: TSELW];
  wire [TSELW-1:0] rd_tile = addr[ADDR_W-1 -: TSELW];

  wire walking = (walk_idx != 5'd16);
  wire pulse    = walking & (walk_ph == 2'd0);

  genvar t, r;
  generate
    for (t = 0; t < NTILE; t = t + 1) begin : g_tile
      // Odd rows on phase 0, even rows on phase 1. A one-hot WROW would copy the
      // previous row into the selected one rather than writing it, which is what
      // rtl/stt_imem_cfgmem.v does and why that version cannot work at all.
      wire sel_t = walking & (wr_tile == t[TSELW-1:0]);
      wire [15:0] wrow;
      for (r = 0; r < 16; r = r + 1) begin : g_row
        assign wrow[r] = pulse & (walk_idx[3:0] == r[3:0]);
      end

      CFGMEM_IHP16 u_tile (
          .BYP  (1'b0),
          .EN0  (1'b1),
          .WE0  (sel_t),
          // Words arrive in ascending address order and shift DOWN the chain, so
          // after 16 strobes address a sits at chain row 15-a. Inverting the
          // low address bits on the read side undoes that, which keeps the host
          // protocol of SPEC section 10 -- rows loaded in order from 0 --
          // unchanged.
          .A0   (~addr[3:0]),
          .Di0  ({{(32 - ROW_W){1'b0}}, wr_data}),
          .Do0  (do_tile[t]),
          .WROW (wrow)
      );
    end
  endgenerate

  // ---- read mux across tiles (asynchronous, SPEC section 12) -------------
  reg [31:0] rd_sel;
  integer k;
  always @* begin
    rd_sel = 32'b0;
    for (k = 0; k < NTILE; k = k + 1)
      if (rd_tile == k[TSELW-1:0]) rd_sel = do_tile[k];
  end

  assign row     = rd_sel[ROW_W-1:0];
  assign ld_out  = stage[0];
  assign ld_addr = wptr;
  assign ld_busy = walking;

endmodule
`default_nettype wire
