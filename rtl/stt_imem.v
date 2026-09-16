// stt_imem -- the row array plus the load-from-host shift-in path.
//
// Load: the host clocks rows in one bit at a time (LSB first, matching
// rowenc.pack()).  A ROW_W-bit staging register assembles a row; when the bit
// counter wraps the row is written to the array and the write pointer advances.
// Read: asynchronous, one row per cycle -- the STT model fetches and decodes a
// row in the same cycle, so a registered-output macro would need an extra
// pipeline stage.  See docs/area-study.md.
//
// Row width and row count are parameters, as required.
`default_nettype none

module stt_imem #(
    parameter ROW_W  = 21,
    parameter ROWS   = 32,
    parameter ADDR_W = 5
) (
    input  wire               clk,
    input  wire               rst_n,

    input  wire [ADDR_W-1:0]  addr,      // read address, from stt_decode
    output wire [ROW_W-1:0]   row,

    input  wire               ld_en,     // host shift-in enable
    input  wire               ld_in,     // host serial data
    output wire               ld_out,    // top of the staging register
    output wire [ADDR_W-1:0]  ld_addr    // current write pointer (observable)
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

  localparam integer BITC_W = clog2(ROW_W);

  reg [ROW_W-1:0]  mem [0:ROWS-1];
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
      stage <= {ld_in, stage[ROW_W-1:1]};       // LSB-first, like rowenc.pack()
      if (last_bit) begin
        bitc <= {BITC_W{1'b0}};
        wptr <= wptr + {{(ADDR_W-1){1'b0}}, 1'b1};
      end else begin
        bitc <= bitc + {{(BITC_W-1){1'b0}}, 1'b1};
      end
    end
  end

  // row write: the completed staging word, including the bit arriving now
  wire [ROW_W-1:0] stage_full = {ld_in, stage[ROW_W-1:1]};

  always @(posedge clk) begin
    if (ld_en && last_bit) mem[wptr] <= stage_full;
  end

  assign row     = mem[addr];
  assign ld_out  = stage[0];
  assign ld_addr = wptr;

endmodule
`default_nettype wire
