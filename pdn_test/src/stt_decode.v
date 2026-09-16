// stt_decode -- row field extraction, test evaluation, branch/next-row logic,
// and the one-level call link register.
//
// Structurally faithful: the 16:1 test mux, the 4-way next-row mux, the RET
// substitution and the two 5-bit state registers are all the real design's.
// See rtl/ISA_NOTES.md sections 1-3.
`default_nettype none
`include "stt_pkg.vh"

module stt_decode #(
    parameter ROW_W  = 21,
    parameter ROWS   = 32,
    parameter ADDR_W = 5
) (
    input  wire                clk,
    input  wire                rst_n,
    input  wire                en,          // core running

    input  wire [ROW_W-1:0]    row,         // from stt_imem

    // condition inputs (from stt_datapath, except fifo_ne from the host)
    input  wire                tmr_tick,
    input  wire                fifo_ne,
    input  wire                cz,
    input  wire                c2z,
    input  wire                srbit,
    input  wire                in0_s,
    input  wire                in1_s,

    // action feedback (from stt_palette) -- needed for the link register
    input  wire                act_call,

    output wire [ADDR_W-1:0]   row_addr,    // to stt_imem
    output wire [4:0]          act_index,   // to stt_palette
    output wire [1:0]          pin_slot,    // to stt_datapath
    output wire [2:0]          pin_op,      // to stt_datapath
    output wire                fire         // test passed: actions + pin ops run
);

  // ---- field extraction -----------------------------------------------
  wire [3:0] f_test = row[`STT_TEST_LSB +: `STT_TEST_W];
  wire [1:0] f_mode = row[`STT_MODE_LSB +: `STT_MODE_W];
  wire [4:0] f_tgt  = row[`STT_TGT_LSB  +: `STT_TGT_W];

  assign pin_slot  = row[`STT_SLOT_LSB +: `STT_SLOT_W];
  assign pin_op    = row[`STT_POP_LSB  +: `STT_POP_W];
  assign act_index = row[`STT_ACT_LSB  +: `STT_ACT_W];

  // ---- test mux (10 defined codes; 10..15 read as false, ISA_NOTES A5) --
  reg test_q;
  always @* begin
    case (f_test)
      `STT_T_ALWAYS: test_q = 1'b1;
      `STT_T_C2Z   : test_q = c2z;
      `STT_T_CZ    : test_q = cz;
      `STT_T_FIFO  : test_q = fifo_ne;
      `STT_T_IN0H  : test_q = in0_s;
      `STT_T_IN0L  : test_q = ~in0_s;
      `STT_T_IN1H  : test_q = in1_s;
      `STT_T_IN1L  : test_q = ~in1_s;
      `STT_T_SRBIT : test_q = srbit;
      `STT_T_TMR   : test_q = tmr_tick;
      default      : test_q = 1'b0;
    endcase
  end

  assign fire = test_q & en;

  // ---- next-row computation -------------------------------------------
  reg  [ADDR_W-1:0] cur;
  reg  [ADDR_W-1:0] link;

  wire [ADDR_W-1:0] nxt_seq = (cur == (ROWS-1)) ? {ADDR_W{1'b0}}
                                                : cur + {{(ADDR_W-1){1'b0}}, 1'b1};
  // RET (target code 31) substitutes the link register, ISA_NOTES §3
  wire              is_ret  = (f_tgt == `STT_RET);
  wire [ADDR_W-1:0] tgt     = is_ret ? link : f_tgt[ADDR_W-1:0];

  reg [ADDR_W-1:0] nxt;
  always @* begin
    case (f_mode)
      `STT_M_WAIT  : nxt = test_q ? tgt     : cur;
      `STT_M_BRANCH: nxt = test_q ? tgt     : nxt_seq;
      `STT_M_SKIP  : nxt = test_q ? nxt_seq : tgt;
      default      : nxt = test_q ? nxt_seq : cur;   // STEP
    endcase
  end

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      cur  <= {ADDR_W{1'b0}};
      link <= {ADDR_W{1'b0}};
    end else if (en) begin
      cur <= nxt;
      // "A CALL links to next" -- rowenc.realize() requires f == nxt
      if (fire & act_call) link <= nxt_seq;
    end
  end

  assign row_addr = cur;

endmodule
`default_nettype wire
