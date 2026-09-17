// stt_config -- the per-state-machine configuration register, loaded serially.
//
// SPEC section 2 lists what is configuration rather than a row field. This holds
// exactly that list and nothing else. It is one shift register; the fields are
// slices of it, so the host loads a flat bit string and the bit order below is
// the contract.
//
// Shifted in LSB-first: the first bit presented on `ld_in` ends up in bit 0.
`default_nettype none
`include "stt_isa.vh"

module stt_config #(
    parameter TIMER_W = 16,
    parameter SR_W    = 8,
    parameter CNT_W   = 8,
    parameter NSLOT   = 3
) (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               ld_en,
    input  wire               ld_in,
    output wire               ld_out,

    output wire [TIMER_W-1:0] cfg_period,     // P
    output wire               cfg_shift_left, // 0 = right, 1 = left
    output wire [1:0]         cfg_fill,       // 0 = const 0, 1 = const 1, 2 = in0
    output wire [3:0]         cfg_sr_width,   // shift register width in bits
    output wire [CNT_W-1:0]   cfg_cload_a,
    output wire [CNT_W-1:0]   cfg_cload_b,
    output wire [CNT_W-1:0]   cfg_cload_c,
    output wire [CNT_W-1:0]   cfg_c2load,
    output wire [SR_W-1:0]    cfg_loadk,
    output wire [NSLOT-1:0]   cfg_init_pins,
    output wire [NSLOT-1:0]   cfg_od_mask     // 1 = open drain (SPEC section 7)
);

  localparam integer NBITS = TIMER_W + 1 + 2 + 4 + 4*CNT_W + SR_W + 2*NSLOT;

  reg [NBITS-1:0] cfg;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)     cfg <= {NBITS{1'b0}};
    else if (ld_en) cfg <= {ld_in, cfg[NBITS-1:1]};
  end
  assign ld_out = cfg[0];

  // Field map. Changing this changes the host's bit order, so it is stated once
  // here and mirrored in rtl2/tb/stt_lockstep.py.
  localparam integer O_PERIOD = 0;
  localparam integer O_SHIFT  = O_PERIOD + TIMER_W;
  localparam integer O_FILL   = O_SHIFT  + 1;
  localparam integer O_SRW    = O_FILL   + 2;
  localparam integer O_CA     = O_SRW    + 4;
  localparam integer O_CB     = O_CA     + CNT_W;
  localparam integer O_CC     = O_CB     + CNT_W;
  localparam integer O_C2     = O_CC     + CNT_W;
  localparam integer O_K      = O_C2     + CNT_W;
  localparam integer O_INIT   = O_K      + SR_W;
  localparam integer O_OD     = O_INIT   + NSLOT;

  assign cfg_period     = cfg[O_PERIOD +: TIMER_W];
  assign cfg_shift_left = cfg[O_SHIFT];
  assign cfg_fill       = cfg[O_FILL +: 2];
  assign cfg_sr_width   = cfg[O_SRW  +: 4];
  assign cfg_cload_a    = cfg[O_CA   +: CNT_W];
  assign cfg_cload_b    = cfg[O_CB   +: CNT_W];
  assign cfg_cload_c    = cfg[O_CC   +: CNT_W];
  assign cfg_c2load     = cfg[O_C2   +: CNT_W];
  assign cfg_loadk      = cfg[O_K    +: SR_W];
  assign cfg_init_pins  = cfg[O_INIT +: NSLOT];
  assign cfg_od_mask    = cfg[O_OD   +: NSLOT];

endmodule
`default_nettype wire
