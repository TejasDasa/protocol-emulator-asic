// crc_lfsr16 -- 16-bit programmable-polynomial CRC / LFSR.
//
// Priced separately from the STT core (docs/area-study.md): we need to know
// whether this is affordable before the row width is frozen, because a CRC
// engine wide enough for CRC-16 would justify extra action-group codes.
//
// One Galois-form register with a loadable polynomial.  Both bit orders are
// supported because USB CRC5/CRC16 are reflected (right-shifting) while
// CCITT-style CRCs are not.
//
// Narrower CRCs (the CRC5 the STT core already has in stt_datapath) run in the
// low bits with the polynomial zero-extended.
`default_nettype none

module crc_lfsr16 #(
    parameter W = 16
) (
    input  wire          clk,
    input  wire          rst_n,

    // configuration
    input  wire [W-1:0]  poly_in,
    input  wire          poly_we,
    input  wire          reflect_in,    // 1 = right-shifting (reflected)
    input  wire          reflect_we,

    // operation
    input  wire          en,
    input  wire          seed,          // load the seed instead of stepping
    input  wire          seed_ones,     // 1 -> all ones, 0 -> all zeros
    input  wire          data_bit,

    output wire [W-1:0]  crc,
    output wire          crc_bit        // the bit leaving the register
);

  reg [W-1:0] poly;
  reg [W-1:0] state;
  reg         reflect;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)          poly <= {W{1'b0}};
    else if (poly_we)    poly <= poly_in;
  end

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)          reflect <= 1'b0;
    else if (reflect_we) reflect <= reflect_in;
  end

  // reflected: feedback out of bit 0, shift right
  wire        fb_r = state[0]   ^ data_bit;
  wire [W-1:0] nx_r = {1'b0, state[W-1:1]} ^ (fb_r ? poly : {W{1'b0}});

  // non-reflected: feedback out of the top bit, shift left
  wire        fb_l = state[W-1] ^ data_bit;
  wire [W-1:0] nx_l = {state[W-2:0], 1'b0} ^ (fb_l ? poly : {W{1'b0}});

  wire [W-1:0] nx = reflect ? nx_r : nx_l;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)       state <= {W{1'b0}};
    else if (en) begin
      if (seed)       state <= seed_ones ? {W{1'b1}} : {W{1'b0}};
      else            state <= nx;
    end
  end

  assign crc     = state;
  assign crc_bit = reflect ? fb_r : fb_l;

endmodule
`default_nettype wire
