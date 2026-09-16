// stt_imem_cfgmem -- the instruction memory with the row array replaced by
// tiled CFGMEM_IHP16 latch macros, keeping the identical external interface.
//
// Same ports as stt_imem, so the two are drop-in comparable. What the macro
// supplies and what it does NOT is the whole point of this module:
//
//   supplied by the macro : the ROW_W storage bits, the read address decode
//   still needed outside  : the serial staging register, the bit counter, the
//                           write pointer, the WROW one-hot write decode, and
//                           the read mux across tiles
//
// The earlier comparison in docs/area-study.md section 9 charged the CFGMEM
// side for none of that. Synthesising this module (with the macro as a
// blackbox) measures exactly that retained glue.
`default_nettype none

module stt_imem_cfgmem #(
    parameter ROW_W  = 21,
    parameter ROWS   = 32,
    parameter ADDR_W = 5,
    parameter NTILE  = 2      // 16 words each -> ROWS = 16 * NTILE
) (
    input  wire               clk,
    input  wire               rst_n,

    input  wire [ADDR_W-1:0]  addr,
    output wire [ROW_W-1:0]   row,

    input  wire               ld_en,
    input  wire               ld_in,
    output wire               ld_out,
    output wire [ADDR_W-1:0]  ld_addr
);

  function integer clog2;
    input integer value;
    integer v;
    begin
      v = value - 1; clog2 = 0;
      while (v > 0) begin clog2 = clog2 + 1; v = v >> 1; end
    end
  endfunction

  localparam integer BITC_W = clog2(ROW_W);
  localparam integer TSELW  = (NTILE > 1) ? clog2(NTILE) : 1;

  // ---- retained load path: identical to stt_imem --------------------------
  reg [ROW_W-1:0]  stage;
  reg [BITC_W-1:0] bitc;
  reg [ADDR_W-1:0] wptr;

  wire last_bit = (bitc == (ROW_W-1));

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      stage <= {ROW_W{1'b0}};
      bitc  <= {BITC_W{1'b0}};
      wptr  <= {ADDR_W{1'b0}};
    end else if (ld_en) begin
      stage <= {ld_in, stage[ROW_W-1:1]};
      if (last_bit) begin
        bitc <= {BITC_W{1'b0}};
        wptr <= wptr + {{(ADDR_W-1){1'b0}}, 1'b1};
      end else begin
        bitc <= bitc + {{(BITC_W-1){1'b0}}, 1'b1};
      end
    end
  end

  wire [ROW_W-1:0] stage_full = {ld_in, stage[ROW_W-1:1]};
  wire             wr_stb     = ld_en && last_bit;

  // ---- tiles --------------------------------------------------------------
  wire [31:0] do_tile [0:NTILE-1];
  wire [TSELW-1:0] wr_tile = wptr[ADDR_W-1 -: TSELW];
  wire [TSELW-1:0] rd_tile = addr[ADDR_W-1 -: TSELW];

  genvar t;
  generate
    for (t = 0; t < NTILE; t = t + 1) begin : g_tile
      // WROW is one-hot: the write-row decode is OUTSIDE the macro.
      wire sel_t = wr_stb && (wr_tile == t[TSELW-1:0]);
      wire [15:0] wrow;
      genvar r;
      for (r = 0; r < 16; r = r + 1) begin : g_row
        assign wrow[r] = sel_t && (wptr[3:0] == r[3:0]);
      end

      CFGMEM_IHP16 u_tile (
          .BYP  (1'b0),
          .EN0  (1'b1),
          .WE0  (sel_t),
          .A0   (addr[3:0]),
          .Di0  ({{(32-ROW_W){1'b0}}, stage_full}),
          .Do0  (do_tile[t]),
          .WROW (wrow)
      );
    end
  endgenerate

  // ---- read mux across tiles ---------------------------------------------
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

endmodule
`default_nettype wire
