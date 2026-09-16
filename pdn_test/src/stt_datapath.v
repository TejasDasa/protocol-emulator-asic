// stt_datapath -- pin drivers, shift register, counters, timer, CRC5 and the
// input synchronizers.  Also instantiates stt_config, a separately measurable
// submodule holding the per-program configuration registers (period, shift
// direction, fill source, the three counter reload constants, c2 reload, K and
// the pin reset/open-drain masks).  ISA_NOTES.md section 7 lists them; they are
// real flops on the die even though isa_bench does not count them as program
// bits, so they are included here and kept separable.
//
// Ordering that matters (ISA_NOTES section 6): crcstep reads the shift register
// *before* shift; the `sr` pin op reads it *after*.
`default_nettype none
`include "stt_pkg.vh"

// ------------------------------------------------------- config registers
module stt_config #(
    parameter SR_W    = 8,
    parameter CNT_W   = 8,
    parameter TIMER_W = 16,
    parameter NSLOT   = 3
) (
    input  wire                clk,
    input  wire                rst_n,
    input  wire                ld_en,
    input  wire                ld_in,
    output wire                ld_out,

    output wire [TIMER_W-1:0]  cfg_period,
    output wire                cfg_shift_left,
    output wire [1:0]          cfg_fill_sel,     // 0 = '0', 1 = '1', 2 = in0
    output wire [CNT_W-1:0]    cfg_cload_a,
    output wire [CNT_W-1:0]    cfg_cload_b,
    output wire [CNT_W-1:0]    cfg_cload_c,
    output wire [CNT_W-1:0]    cfg_c2load,
    output wire [SR_W-1:0]     cfg_loadk,
    output wire [NSLOT-1:0]    cfg_init_pins,
    output wire [NSLOT-1:0]    cfg_od_mask
);
  localparam integer NBITS = TIMER_W + 1 + 2 + 4*CNT_W + SR_W + 2*NSLOT;

  reg [NBITS-1:0] cfg;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)     cfg <= {NBITS{1'b0}};
    else if (ld_en) cfg <= {cfg[NBITS-2:0], ld_in};
  end
  assign ld_out = cfg[NBITS-1];

  localparam integer O_PERIOD = 0;
  localparam integer O_SHIFT  = O_PERIOD + TIMER_W;
  localparam integer O_FILL   = O_SHIFT  + 1;
  localparam integer O_CA     = O_FILL   + 2;
  localparam integer O_CB     = O_CA     + CNT_W;
  localparam integer O_CC     = O_CB     + CNT_W;
  localparam integer O_C2     = O_CC     + CNT_W;
  localparam integer O_K      = O_C2     + CNT_W;
  localparam integer O_INIT   = O_K      + SR_W;
  localparam integer O_OD     = O_INIT   + NSLOT;

  assign cfg_period     = cfg[O_PERIOD +: TIMER_W];
  assign cfg_shift_left = cfg[O_SHIFT];
  assign cfg_fill_sel   = cfg[O_FILL +: 2];
  assign cfg_cload_a    = cfg[O_CA   +: CNT_W];
  assign cfg_cload_b    = cfg[O_CB   +: CNT_W];
  assign cfg_cload_c    = cfg[O_CC   +: CNT_W];
  assign cfg_c2load     = cfg[O_C2   +: CNT_W];
  assign cfg_loadk      = cfg[O_K    +: SR_W];
  assign cfg_init_pins  = cfg[O_INIT +: NSLOT];
  assign cfg_od_mask    = cfg[O_OD   +: NSLOT];
endmodule

// -------------------------------------------------------------- datapath
module stt_datapath #(
    parameter SR_W    = 8,
    parameter CNT_W   = 8,
    parameter TIMER_W = 16,
    parameter CRC_W   = 5,
    parameter NSLOT   = 3,
    parameter NIN     = 2
) (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               en,
    input  wire               fire,          // from stt_decode

    // action strobes from stt_palette
    input  wire               act_load,
    input  wire               act_loadk,
    input  wire               act_loadcrc,
    input  wire               act_clr,
    input  wire               act_shift,
    input  wire               act_push,
    input  wire               act_cload,
    input  wire               act_cload_b,
    input  wire               act_cload_c,
    input  wire               act_cdec,
    input  wire               act_c2load,
    input  wire               act_c2dec,
    input  wire               act_trst,
    input  wire               act_thalf,
    input  wire               act_crcrst,
    input  wire               act_crcstep,

    // pin field from stt_decode
    input  wire [1:0]         pin_slot,
    input  wire [2:0]         pin_op,

    // host data interface
    input  wire [SR_W-1:0]    tx_data,
    output wire               tx_pop,
    output wire [SR_W-1:0]    rx_data,
    output wire               rx_push,

    // config serial chain
    input  wire               cfg_ld_en,
    input  wire               cfg_ld_in,
    output wire               cfg_ld_out,

    // pins
    input  wire [NIN-1:0]     pin_in,
    output wire [NSLOT-1:0]   pin_out,
    output wire [NSLOT-1:0]   pin_oe,

    // conditions back to stt_decode
    output wire               tmr_tick,
    output wire               cz,
    output wire               c2z,
    output wire               srbit,
    output wire               in0_s,
    output wire               in1_s
);

  // ---- configuration ---------------------------------------------------
  wire [TIMER_W-1:0] cfg_period;
  wire               cfg_shift_left;
  wire [1:0]         cfg_fill_sel;
  wire [CNT_W-1:0]   cfg_cload_a, cfg_cload_b, cfg_cload_c, cfg_c2load;
  wire [SR_W-1:0]    cfg_loadk;
  wire [NSLOT-1:0]   cfg_init_pins, cfg_od_mask;

  stt_config #(.SR_W(SR_W), .CNT_W(CNT_W), .TIMER_W(TIMER_W), .NSLOT(NSLOT)) u_cfg (
      .clk(clk), .rst_n(rst_n),
      .ld_en(cfg_ld_en), .ld_in(cfg_ld_in), .ld_out(cfg_ld_out),
      .cfg_period(cfg_period), .cfg_shift_left(cfg_shift_left),
      .cfg_fill_sel(cfg_fill_sel),
      .cfg_cload_a(cfg_cload_a), .cfg_cload_b(cfg_cload_b), .cfg_cload_c(cfg_cload_c),
      .cfg_c2load(cfg_c2load), .cfg_loadk(cfg_loadk),
      .cfg_init_pins(cfg_init_pins), .cfg_od_mask(cfg_od_mask)
  );

  // ---- input synchronizers (2 cycles, isa_bench World.read_sync) -------
  reg [NIN-1:0] sync0, sync1;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      sync0 <= {NIN{1'b0}};
      sync1 <= {NIN{1'b0}};
    end else begin
      sync0 <= pin_in;
      sync1 <= sync0;
    end
  end
  assign in0_s = sync1[0];
  assign in1_s = sync1[1];

  // ---- shift register --------------------------------------------------
  reg  [SR_W-1:0]  sr;
  reg  [CRC_W-1:0] crc;

  wire fill = (cfg_fill_sel == 2'd0) ? 1'b0 :
              (cfg_fill_sel == 2'd1) ? 1'b1 : in0_s;

  assign srbit = cfg_shift_left ? sr[SR_W-1] : sr[0];     // pre-action: the test

  wire [SR_W-1:0] sr_base   = act_clr ? {SR_W{1'b0}} : sr;   // clr precedes shift
  wire [SR_W-1:0] sr_shift  = cfg_shift_left ? {sr_base[SR_W-2:0], fill}
                                             : {fill, sr_base[SR_W-1:1]};
  wire [SR_W-1:0] sr_crcinv = { {(SR_W-CRC_W){1'b0}}, ~crc };

  reg [SR_W-1:0] sr_next;
  always @* begin
    if      (act_load)    sr_next = tx_data;
    else if (act_loadk)   sr_next = cfg_loadk;
    else if (act_loadcrc) sr_next = sr_crcinv;
    else if (act_shift)   sr_next = sr_shift;
    else if (act_clr)     sr_next = {SR_W{1'b0}};
    else                  sr_next = sr;
  end

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)            sr <= {SR_W{1'b0}};
    else if (en && fire)   sr <= sr_next;
  end

  // post-action serial bit: what a `sr` pin op writes
  wire srbit_post = cfg_shift_left ? sr_next[SR_W-1] : sr_next[0];

  assign rx_data = sr;
  assign rx_push = en & fire & act_push;
  assign tx_pop  = en & fire & act_load;

  // ---- CRC5, reflected 0x14 (ISA_NOTES section 6) ----------------------
  wire              crc_fb   = crc[0] ^ srbit;            // pre-shift srbit
  wire [CRC_W-1:0]  crc_step = {1'b0, crc[CRC_W-1:1]} ^ (crc_fb ? 5'h14 : 5'h00);

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)                    crc <= {CRC_W{1'b1}};
    else if (en && fire) begin
      if      (act_crcrst)         crc <= {CRC_W{1'b1}};
      else if (act_crcstep)        crc <= crc_step;
    end
  end

  // ---- counters --------------------------------------------------------
  reg [CNT_W-1:0] cnt, c2;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)              cnt <= {CNT_W{1'b0}};
    else if (en && fire) begin
      if      (act_cload)    cnt <= cfg_cload_a;
      else if (act_cload_b)  cnt <= cfg_cload_b;
      else if (act_cload_c)  cnt <= cfg_cload_c;
      else if (act_cdec)     cnt <= cnt - {{(CNT_W-1){1'b0}}, 1'b1};
    end
  end

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)              c2 <= {CNT_W{1'b0}};
    else if (en && fire) begin
      if      (act_c2load)   c2 <= cfg_c2load;
      else if (act_c2dec)    c2 <= c2 - {{(CNT_W-1){1'b0}}, 1'b1};
    end
  end

  assign cz  = (cnt == {CNT_W{1'b0}});
  assign c2z = (c2  == {CNT_W{1'b0}});

  // ---- timer (free-running, ISA_NOTES section 6) -----------------------
  reg [TIMER_W-1:0] tcount;
  wire [TIMER_W-1:0] one   = {{(TIMER_W-1){1'b0}}, 1'b1};
  wire [TIMER_W-1:0] p_m1  = cfg_period - one;
  wire [TIMER_W-1:0] p_h   = {1'b0, cfg_period[TIMER_W-1:1]} - one;   // P/2 - 1

  assign tmr_tick = (tcount == {TIMER_W{1'b0}});

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)                       tcount <= {TIMER_W{1'b0}};
    else if (en) begin
      if      (fire && act_trst)      tcount <= p_m1;
      else if (fire && act_thalf)     tcount <= p_h;
      else if (tmr_tick)              tcount <= p_m1;
      else                            tcount <= tcount - one;
    end
  end

  // ---- pin drivers ------------------------------------------------------
  reg [NSLOT-1:0] pinv;

  // Per-slot next value.  One shared op decoder feeds all three slots; the slot
  // field selects which slot(s) take the write.  Written without a loop
  // variable so nothing is inferred as a latch.
  wire slot_is_pair = (pin_slot == `STT_SLOT_PAIR);

  // value a single-slot op would write, and whether it writes at all
  reg  single_val;
  reg  single_we;
  always @* begin
    case (pin_op)
      `STT_P_LO : begin single_val = 1'b0;       single_we = 1'b1; end
      `STT_P_HI : begin single_val = 1'b1;       single_we = 1'b1; end
      `STT_P_SR : begin single_val = srbit_post; single_we = 1'b1; end
      `STT_P_TGL: begin single_val = 1'b0;       single_we = 1'b1; end  // value from toggle path
      default   : begin single_val = 1'b0;       single_we = 1'b0; end  // hold / d0 / d1 / unassigned
    endcase
  end
  wire op_is_tgl = (pin_op == `STT_P_TGL);

  // pair op decode: writes slots 0 and 1 together
  reg  pair_v0, pair_v1;
  reg  pair_we;
  always @* begin
    case (pin_op)
      `STT_P_LO : begin pair_v0 = 1'b0;       pair_v1 = 1'b0;        pair_we = 1'b1; end
      `STT_P_HI : begin pair_v0 = 1'b1;       pair_v1 = 1'b1;        pair_we = 1'b1; end
      `STT_P_SR : begin pair_v0 = srbit_post; pair_v1 = ~srbit_post; pair_we = 1'b1; end
      `STT_P_TGL: begin pair_v0 = ~pinv[0];   pair_v1 = ~pinv[1];    pair_we = 1'b1; end
      `STT_P_D0 : begin pair_v0 = 1'b0;       pair_v1 = 1'b1;        pair_we = 1'b1; end
      `STT_P_D1 : begin pair_v0 = 1'b1;       pair_v1 = 1'b0;        pair_we = 1'b1; end
      default   : begin pair_v0 = 1'b0;       pair_v1 = 1'b0;        pair_we = 1'b0; end
    endcase
  end

  wire [NSLOT-1:0] slot_hit = { (pin_slot == 2'd2), (pin_slot == 2'd1), (pin_slot == 2'd0) };

  wire [NSLOT-1:0] pinv_next;
  wire s0_single = slot_hit[0] & single_we & ~slot_is_pair;
  wire s1_single = slot_hit[1] & single_we & ~slot_is_pair;
  wire s2_single = slot_hit[2] & single_we & ~slot_is_pair;

  assign pinv_next[0] = (slot_is_pair & pair_we) ? pair_v0
                      : s0_single ? (op_is_tgl ? ~pinv[0] : single_val)
                      : pinv[0];
  assign pinv_next[1] = (slot_is_pair & pair_we) ? pair_v1
                      : s1_single ? (op_is_tgl ? ~pinv[1] : single_val)
                      : pinv[1];
  assign pinv_next[2] = s2_single ? (op_is_tgl ? ~pinv[2] : single_val)
                      : pinv[2];

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)          pinv <= {NSLOT{1'b1}};
    else if (!en)        pinv <= cfg_init_pins;
    else if (fire)       pinv <= pinv_next;
  end

  // open-drain: drive 0, release for 1.  push-pull: drive the value.
  assign pin_out = pinv & ~cfg_od_mask;
  assign pin_oe  = ~cfg_od_mask | ~pinv;

endmodule
`default_nettype wire
