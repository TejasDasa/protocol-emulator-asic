// stt_core -- one state-table state machine, implementing docs/SPEC.md.
//
// The whole datapath is one cycle of SPEC section 8.1, in its seven steps:
//
//   1. sample the timer tick   (before anything else)
//   2. evaluate the test       (state as it was at the START of the cycle)
//   3. if the test passed, apply actions in the section 6.3 order
//   4. if the test passed, apply the pin op, which sees the sr AFTER step 3
//   5. select the next row     (section 5)
//   6. update the timer        (whether or not the test passed)
//   7. drive the output slots
//
// Steps 1-6 are the combinational block below and land in registers on the
// clock edge; step 7 is the continuous assignment at the bottom. A failing test
// changes nothing but the row pointer and the timer.
//
// Three orderings inside step 3 are observable and are what section 8.2 pins
// down. Written out because they are the easiest thing to get subtly wrong:
//
//   sr_pre   the shift register at the start of the cycle. The `srbit` TEST
//            reads this.
//   sr_mid   after load / loadk / loadcrc / clr, which precede crcstep in the
//            section 6.3 order. `crcstep` reads THIS, and `push` pushes it.
//   sr_next  after `shift`, which follows crcstep. The PIN OP reads this, so a
//            row that both shifts and drives `sr` emits the NEW serial bit.
//
// `loadcrc` reads the CRC before `crcrst`/`crcstep` touch it, for the same
// reason: it is earlier in the order.
`default_nettype none
`include "stt_isa.vh"

module stt_core #(
    parameter ROW_W   = `STT_ROW_W,
    parameter ADDR_W  = `STT_ADDR_W,
    parameter SR_W    = 8,
    parameter CNT_W   = 8,
    parameter TIMER_W = 16,
    parameter NSLOT   = 3,
    parameter NIN     = 2
) (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               en,          // low while loading; holds pins at init

    // instruction memory (asynchronous read, SPEC section 12)
    output wire [ADDR_W-1:0]  row_addr,
    input  wire [ROW_W-1:0]   row,

    // configuration (SPEC section 2)
    input  wire [TIMER_W-1:0] cfg_period,
    input  wire               cfg_shift_left,
    input  wire [1:0]         cfg_fill,
    input  wire [3:0]         cfg_sr_width,
    input  wire [CNT_W-1:0]   cfg_cload_a,
    input  wire [CNT_W-1:0]   cfg_cload_b,
    input  wire [CNT_W-1:0]   cfg_cload_c,
    input  wire [CNT_W-1:0]   cfg_c2load,
    input  wire [SR_W-1:0]    cfg_loadk,
    input  wire [NSLOT-1:0]   cfg_init_pins,
    input  wire [NSLOT-1:0]   cfg_od_mask,

    // SPEC section 9 wider per-machine units. Both are configuration, not row
    // fields: a program picks a polynomial and a stuffing rule once, the way
    // it picks a period.
    input  wire [15:0]        cfg_crc16_poly,
    input  wire [4:0]         cfg_crc16_width,
    input  wire               cfg_crc16_reflect,
    input  wire               cfg_crc16_seed_ones,
    input  wire [3:0]         cfg_stuff_n,        // 0 disables the stuffer
    input  wire               cfg_stuff_ones,     // count 1s only (USB), not runs
    input  wire [NSLOT-1:0]   cfg_stuff_slots,    // which slots route through it

    // host byte interface
    input  wire [SR_W-1:0]    tx_data,
    input  wire               tx_ne,       // TX FIFO not empty -> the `fifo` test
    output wire               tx_pop,
    output wire [SR_W-1:0]    rx_data,
    output wire               rx_push,

    // pins
    input  wire [NIN-1:0]     pin_in,      // raw; synchronized below
    output wire [NSLOT-1:0]   pin_out,
    output wire [NSLOT-1:0]   pin_oe,

    // observability for the lockstep testbench
    output wire [SR_W-1:0]    dbg_sr,
    output wire [CNT_W-1:0]   dbg_cnt,
    output wire [CNT_W-1:0]   dbg_c2,
    output wire [4:0]         dbg_crc,
    output wire [TIMER_W-1:0] dbg_tcount,
    output wire [ADDR_W-1:0]  dbg_link,
    output wire [NSLOT-1:0]   dbg_pinv
,
    output wire [15:0]        dbg_crc16,
    output wire [3:0]         dbg_stuff_run,
    output wire               dbg_stuff_last,
    output wire               dbg_stuff_valid
);

  // ---- architectural state (SPEC section 2) ------------------------------
  reg [ADDR_W-1:0]  rowp;
  reg [ADDR_W-1:0]  link;
  reg [SR_W-1:0]    sr;
  reg [CNT_W-1:0]   cnt;
  reg [CNT_W-1:0]   c2;
  reg [4:0]         crc;
  reg [TIMER_W-1:0] tcount;
  reg [NSLOT-1:0]   pinv;
  reg [15:0]        crc16;
  // The model's stuffer holds `stuff_last = None` before the first bit, which
  // is a third state, not a value. `stuff_valid` is that None.
  reg [3:0]         stuff_run;
  reg               stuff_last;
  reg               stuff_valid;

  // ---- input synchronizer (SPEC section 8.3): two cycles ----------------
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
  wire [NIN-1:0] in_s = sync1;

  // ---- row fields -------------------------------------------------------
  wire [3:0] f_test  = row[`STT_F_TEST];
  wire [1:0] f_mode  = row[`STT_F_MODE];
  wire [7:0] f_tgt   = row[`STT_F_TARGET];
  wire [1:0] f_slot  = row[`STT_F_PIN_SLOT];
  wire [2:0] f_pinop = row[`STT_F_PIN_OP];
  wire [2:0] a_sr    = row[`STT_F_ACT_SR];
  wire [2:0] a_c1    = row[`STT_F_ACT_C1];
  wire [1:0] a_c2    = row[`STT_F_ACT_C2];
  wire [1:0] a_tm    = row[`STT_F_ACT_TM];
  wire [2:0] a_xx    = row[`STT_F_ACT_XX];

  // ---- action flags, one per SPEC section 6 action ----------------------
  wire act_load    = (a_sr == `STT_ASR_LOAD);
  wire act_loadk   = (a_sr == `STT_ASR_LOADK);
  wire act_loadcrc = (a_sr == `STT_ASR_LOADCRC);
  wire act_clr     = (a_sr == `STT_ASR_CLR) || (a_sr == `STT_ASR_CLR_SHIFT);
  wire act_shift   = (a_sr == `STT_ASR_SHIFT) || (a_sr == `STT_ASR_CLR_SHIFT);
`ifdef BREAK_P2
  // Negative test only: `push` also decoded from the combined clr+shift code,
  // which is the shape a copy-paste of the act_clr/act_shift lines above would
  // produce. One row then asserts push, clr and shift together.
  wire act_push    = (a_sr == `STT_ASR_PUSH) || (a_sr == `STT_ASR_CLR_SHIFT);
`else
  wire act_push    = (a_sr == `STT_ASR_PUSH);
`endif

  wire act_cload   = (a_c1 == `STT_AC1_CLOAD);
  wire act_cload_b = (a_c1 == `STT_AC1_CLOAD_B);
  wire act_cload_c = (a_c1 == `STT_AC1_CLOAD_C);
  wire act_cdec    = (a_c1 == `STT_AC1_CDEC);
  wire act_c2load  = (a_c2 == `STT_AC2_C2LOAD);
  wire act_c2dec   = (a_c2 == `STT_AC2_C2DEC);
  wire act_trst    = (a_tm == `STT_ATM_TRST);
  wire act_thalf   = (a_tm == `STT_ATM_THALF);
  wire act_crcrst  = (a_xx == `STT_AXX_CRCRST) || (a_xx == `STT_AXX_CRCRST_CALL);
  wire act_crcstep = (a_xx == `STT_AXX_CRCSTEP);
  wire act_call    = (a_xx == `STT_AXX_CALL)   || (a_xx == `STT_AXX_CRCRST_CALL);
  wire act_crc16rst  = (a_xx == `STT_AXX_CRC16RST);
  wire act_crc16step = (a_xx == `STT_AXX_CRC16STEP);
  wire act_stuffrst  = (a_xx == `STT_AXX_STUFFRST);

  // ---- shift register width and serial bit ------------------------------
  wire [SR_W:0]   mask_ext = ({{SR_W{1'b0}}, 1'b1} << cfg_sr_width) - 1'b1;
  wire [SR_W-1:0] sr_mask  = mask_ext[SR_W-1:0];
  wire [3:0]      msb_idx  = cfg_sr_width - 4'd1;

  // Every dependency is an ARGUMENT, deliberately. Reading cfg_shift_left and
  // msb_idx from the enclosing scope instead is legal Verilog but leaves the
  // continuous assignments below sensitive only to `v`, so the result is
  // computed once with whatever the configuration register held at time 0 and
  // refreshed only when the shift register changes. The reference programs all
  // shift constantly, which hides it; a random program that leaves the shift
  // register alone for 33 cycles carried an X into the `srbit` test.
  function automatic srbit_of;
    input [SR_W-1:0] v;
    input            left;
    input [3:0]      idx;
    begin
      srbit_of = left ? v[idx] : v[0];
    end
  endfunction

  // ---- SPEC section 9 wider units: geometry -----------------------------
  // The wide CRC is a Galois LFSR of configurable width. `reflect` picks the
  // direction: reflected CRCs shift right and feed back from bit 0, MSB-first
  // CRCs shift left and feed back from the top bit of the configured width.
  wire [16:0]      c16_mask_ext = (17'd1 << cfg_crc16_width) - 1'b1;
  wire [15:0]      c16_mask     = c16_mask_ext[15:0];
  wire [3:0]       c16_msb      = cfg_crc16_width[3:0] - 4'd1;
  wire [15:0]      crc16_seed   = cfg_crc16_seed_ones ? c16_mask : 16'd0;

  function automatic [15:0] crc16_adv;
    input [15:0] c;
    input        b;
    input [15:0] poly;
    input [15:0] m;
    input [3:0]  msb;
    input        reflect;
    reg          fb;
    begin
      if (reflect) begin
        fb = c[0] ^ b;
        crc16_adv = fb ? (((c >> 1) ^ poly) & m) : ((c >> 1) & m);
      end else begin
        fb = c[msb] ^ b;
        crc16_adv = fb ? (((c << 1) ^ poly) & m) : ((c << 1) & m);
      end
    end
  endfunction

  // The stuffer will insert rather than accept when the run it has already
  // seen has reached the threshold. `stall_pre` is the TEST's view, on state
  // as it stands at the start of the cycle; `stall_mid` is the PIN OP's view,
  // after `stuffrst` has had its chance in step 3. They differ on exactly the
  // rows that reset the stuffer and drive a pin in the same cycle, which is
  // how a CAN trailer is sent.
  wire stall_pre = (cfg_stuff_n != 4'd0) && stuff_valid
                && !(cfg_stuff_ones && !stuff_last)
                && (stuff_run >= cfg_stuff_n);

  // ---- step 1: the timer tick, before anything else ---------------------
  wire tick = (tcount == {TIMER_W{1'b0}});

  // ---- step 2: the test, on state as it stands at the start of the cycle -
  wire srbit_pre = srbit_of(sr, cfg_shift_left, msb_idx);
  reg  test_pass;
  always @* begin
    case (f_test)
      `STT_T_ALWAYS: test_pass = 1'b1;
      `STT_T_TMR:    test_pass = tick;
      `STT_T_FIFO:   test_pass = tx_ne;
      `STT_T_CZ:     test_pass = (cnt == {CNT_W{1'b0}});
      `STT_T_C2Z:    test_pass = (c2  == {CNT_W{1'b0}});
      `STT_T_SRBIT:  test_pass = srbit_pre;
      `STT_T_IN0H:   test_pass =  in_s[0];
      `STT_T_IN0L:   test_pass = ~in_s[0];
      `STT_T_IN1H:   test_pass =  in_s[1];
      `STT_T_IN1L:   test_pass = ~in_s[1];
      `STT_T_STALL:  test_pass = stall_pre;
      default:       test_pass = 1'b0;   // codes 11-15 unassigned (SPEC section 4)
    endcase
  end
  wire fire = en & test_pass;

  // ---- step 3: actions, in the SPEC section 6.3 order --------------------
  // sr_mid: after load / loadk / loadcrc / clr, which precede crcstep.
  // `load` on an EMPTY TX FIFO. SPEC section 16.1 records this as unspecified:
  // the model calls w.error and leaves the shift register UNCHANGED, and what
  // hardware does is not defined. The models are authoritative (SPEC section 0),
  // so the shift register holds and no pop is issued. Found by the mutation
  // suite: `uart_tx/act_add/row START: add action load` drains the FIFO faster
  // than the program refills it and reaches this case at cycle 995.
  reg [SR_W-1:0] sr_mid;
  always @* begin
    if      (act_load)    sr_mid = tx_ne ? (tx_data & sr_mask) : sr;
    else if (act_loadk)   sr_mid = cfg_loadk & sr_mask;
    else if (act_loadcrc) sr_mid = {{(SR_W-5){1'b0}}, ~crc};
    else if (act_clr)     sr_mid = {SR_W{1'b0}};
    else                  sr_mid = sr;
  end
  wire srbit_mid = srbit_of(sr_mid, cfg_shift_left, msb_idx);

  // crc: crcrst then crcstep, both after the loads above.
  wire [4:0] crc_stepped = ((crc[0] ^ srbit_mid) ? ((crc >> 1) ^ 5'h14)
                                                 : (crc >> 1));
  reg [4:0] crc_next;
  always @* begin
    if      (act_crcrst)  crc_next = 5'h1F;
    else if (act_crcstep) crc_next = crc_stepped;
    else                  crc_next = crc;
  end

  // crc16: crc16rst then crc16step, both after the loads and before `shift`,
  // so crc16step sees the same serial bit crcstep does (SPEC section 8.2).
  reg [15:0] crc16_mid;
  always @* begin
    if      (act_crc16rst)  crc16_mid = crc16_seed;
    else if (act_crc16step) crc16_mid = crc16_adv(crc16, srbit_mid,
                                                  cfg_crc16_poly, c16_mask,
                                                  c16_msb, cfg_crc16_reflect);
    else                    crc16_mid = crc16;
  end

  // `stuffrst` is an ACTION, so it lands before the pin op sees the stuffer.
  wire [3:0] stuff_run_mid   = act_stuffrst ? 4'd0 : stuff_run;
  wire       stuff_last_mid  = act_stuffrst ? 1'b0 : stuff_last;
  wire       stuff_valid_mid = act_stuffrst ? 1'b0 : stuff_valid;
  wire stall_mid = (cfg_stuff_n != 4'd0) && stuff_valid_mid
                && !(cfg_stuff_ones && !stuff_last_mid)
                && (stuff_run_mid >= cfg_stuff_n);
  // The model's run counter is a Python int and never wraps. Saturating here
  // is observationally identical, because nothing reads the count except the
  // comparison against cfg_stuff_n, which is at most 15.
  wire [3:0] stuff_run_inc = (stuff_run_mid == 4'hF) ? 4'hF
                                                    : stuff_run_mid + 1'b1;

  // shift, after crcstep.
  wire fill_bit = (cfg_fill == 2'd0) ? 1'b0
                : (cfg_fill == 2'd1) ? 1'b1
                                     : in_s[0];
  wire [SR_W-1:0] sr_shifted = cfg_shift_left
        ? (((sr_mid << 1) | {{(SR_W-1){1'b0}}, fill_bit}) & sr_mask)
        : ((sr_mid >> 1) | ({{(SR_W-1){1'b0}}, fill_bit} << msb_idx));
  wire [SR_W-1:0] sr_next = act_shift ? sr_shifted : sr_mid;

  // push writes the value as it stands after the loads, before any shift --
  // push and shift are in the same group, so they never both occur.
  assign rx_data = sr_mid;
  assign rx_push = fire & act_push;
  assign tx_pop  = fire & act_load & tx_ne;

  // counters
  reg [CNT_W-1:0] cnt_next;
  always @* begin
    if      (act_cload)   cnt_next = cfg_cload_a;
    else if (act_cload_b) cnt_next = cfg_cload_b;
    else if (act_cload_c) cnt_next = cfg_cload_c;
    else if (act_cdec)    cnt_next = cnt - 1'b1;
    else                  cnt_next = cnt;
  end
  reg [CNT_W-1:0] c2_next;
  always @* begin
    if      (act_c2load) c2_next = cfg_c2load;
    else if (act_c2dec)  c2_next = c2 - 1'b1;
    else                 c2_next = c2;
  end

  // ---- step 4: the pin op, which sees sr_next ---------------------------
  // This is also where the bit stuffer sits. A slot named in cfg_stuff_slots
  // does not necessarily emit the bit the row asked for: when the stuffer is
  // stalling it substitutes the complement of the last bit and consumes
  // nothing. That is the whole reason the `stall` test exists -- the program
  // asks first, and holds its shift register if the answer is yes.
  wire srbit_post = srbit_of(sr_next, cfg_shift_left, msb_idx);

  // crcb drives a pin from the wide CRC and advances it, so the shift-out is
  // part of the pin op rather than of step 3.
  wire        crc16_out_bit = cfg_crc16_reflect ? crc16_mid[0]
                                                : crc16_mid[c16_msb];
  wire [15:0] crc16_shifted = cfg_crc16_reflect ? ((crc16_mid >> 1) & c16_mask)
                                                : ((crc16_mid << 1) & c16_mask);

  reg [NSLOT-1:0] pinv_next;
  reg             crcb_used;
  reg             want, has_want, emit;
  reg [3:0]       stuff_run_next;
  reg             stuff_last_next, stuff_valid_next;
  always @* begin
    pinv_next        = pinv;
    crcb_used        = 1'b0;
    want             = 1'b0;
    has_want         = 1'b0;
    emit             = 1'b0;
    stuff_run_next   = stuff_run_mid;
    stuff_last_next  = stuff_last_mid;
    stuff_valid_next = stuff_valid_mid;
    if (f_slot == `STT_SLOT_PAIR) begin
      // The pair is differential and does not route through the stuffer,
      // matching SttCore.step.
      case (f_pinop)
        `STT_P_LO:   begin pinv_next[0] = 1'b0;        pinv_next[1] = 1'b0;        end
        `STT_P_HI:   begin pinv_next[0] = 1'b1;        pinv_next[1] = 1'b1;        end
        `STT_P_SR:   begin pinv_next[0] = srbit_post;  pinv_next[1] = ~srbit_post; end
        `STT_P_TGL:  begin pinv_next[0] = ~pinv[0];    pinv_next[1] = ~pinv[1];    end
        `STT_P_D0:   begin pinv_next[0] = 1'b0;        pinv_next[1] = 1'b1;        end
        `STT_P_D1:   begin pinv_next[0] = 1'b1;        pinv_next[1] = 1'b0;        end
        `STT_P_CRCB: begin pinv_next[0] = crc16_out_bit;
                           pinv_next[1] = crc16_out_bit;
                           crcb_used    = 1'b1;                                   end
        default:     ;                                 // hold
      endcase
    end else begin
      has_want = 1'b1;
      case (f_pinop)
        `STT_P_LO:   want = 1'b0;
        `STT_P_HI:   want = 1'b1;
        `STT_P_SR:   want = srbit_post;
        `STT_P_TGL:  want = ~pinv[f_slot];
        `STT_P_CRCB: begin want = crc16_out_bit; crcb_used = 1'b1; end
        // hold, and d0/d1 on a single slot: no write (SPEC section 7).
        default:     has_want = 1'b0;
      endcase
      if (has_want) begin
        if (cfg_stuff_slots[f_slot]) begin
          if (stall_mid) begin
            emit             = ~stuff_last_mid;
            stuff_run_next   = 4'd1;
            stuff_last_next  = emit;
            stuff_valid_next = 1'b1;
          end else begin
            emit             = want;
            stuff_run_next   = (stuff_valid_mid && (want == stuff_last_mid))
                                 ? stuff_run_inc : 4'd1;
            stuff_last_next  = want;
            stuff_valid_next = 1'b1;
          end
        end else begin
          emit = want;
        end
        pinv_next[f_slot] = emit;
      end
    end
  end

  wire [15:0] crc16_next = crcb_used ? crc16_shifted : crc16_mid;

  // ---- step 5: the next row (SPEC section 5) ----------------------------
  // `next` wraps mod 32 from row 31.
  wire [ADDR_W-1:0] next_seq = (rowp == {ADDR_W{1'b1}}) ? {ADDR_W{1'b0}}
                                                        : rowp + 1'b1;
  wire [ADDR_W-1:0] tgt_row  = f_tgt[ADDR_W-1:0];
  wire              tgt_ret  = (f_tgt == `STT_RET);

  // Which exit each mode takes, and whether that exit came from the target
  // field -- RET applies only to an exit fed by the target field.
  reg [ADDR_W-1:0] exit_t, exit_f;
  reg              t_from_tgt, f_from_tgt;
  always @* begin
    case (f_mode)
      `STT_M_WAIT:   begin exit_t = tgt_row;  exit_f = rowp;     t_from_tgt = 1'b1; f_from_tgt = 1'b0; end
      `STT_M_BRANCH: begin exit_t = tgt_row;  exit_f = next_seq; t_from_tgt = 1'b1; f_from_tgt = 1'b0; end
`ifdef BREAK_P1B
      // Negative test only: SKIP's exits swapped, so it behaves like BRANCH.
      `STT_M_SKIP:   begin exit_t = tgt_row;  exit_f = next_seq; t_from_tgt = 1'b1; f_from_tgt = 1'b0; end
`else
      `STT_M_SKIP:   begin exit_t = next_seq; exit_f = tgt_row;  t_from_tgt = 1'b0; f_from_tgt = 1'b1; end
`endif

      default:       begin exit_t = next_seq; exit_f = rowp;     t_from_tgt = 1'b0; f_from_tgt = 1'b0; end
    endcase
  end

  // `call` writes the row's FALSE exit, and RET resolves against the value the
  // link register holds AFTER this row's own call, matching SttCore.step.
  wire [ADDR_W-1:0] link_next = (fire & act_call) ? exit_f : link;

  reg [ADDR_W-1:0] row_next;
  always @* begin
    if (!en)             row_next = rowp;
`ifdef BREAK_P1
    // Negative test only: RET resolved on the TRUE exit whatever fed it,
    // which is what SttCore did until 2026-09-16. A SKIP row with target 255
    // then returns when its test passes instead of when it fails.
    else if (test_pass)  row_next = tgt_ret ? link_next : exit_t;
    else                 row_next = exit_f;
`else
    else if (test_pass)  row_next = (t_from_tgt & tgt_ret) ? link_next : exit_t;
    else                 row_next = (f_from_tgt & tgt_ret) ? link_next : exit_f;
`endif
  end

  // ---- step 6: the timer, which updates whether or not the test passed --
  wire [TIMER_W-1:0] period_m1 = cfg_period - 1'b1;
  wire [TIMER_W-1:0] half_m1   = (cfg_period >> 1) - 1'b1;
  reg  [TIMER_W-1:0] tcount_next;
  always @* begin
    if      (fire & act_trst)  tcount_next = period_m1;
    else if (fire & act_thalf) tcount_next = half_m1;
    else if (tick)             tcount_next = period_m1;
    else                       tcount_next = tcount - 1'b1;
  end

  // ---- registers --------------------------------------------------------
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      rowp   <= {ADDR_W{1'b0}};
      link   <= {ADDR_W{1'b0}};
      sr     <= {SR_W{1'b0}};
      cnt    <= {CNT_W{1'b0}};
      c2     <= {CNT_W{1'b0}};
      crc    <= 5'h1F;
      tcount <= {TIMER_W{1'b0}};
      pinv   <= {NSLOT{1'b1}};
      // Cleared, not seeded: before the host has loaded the configuration
      // there is no seed to load. The seed arrives in the !en branch below,
      // which is synchronous and runs for the whole load. Resetting to
      // crc16_seed here instead makes this the only register in the design
      // with a non-constant asynchronous reset, which yosys maps to 16
      // $_ALDFFE_PNP_ async-load flops that the sg13cmos5l library has no
      // cell for.
      crc16       <= 16'd0;
      stuff_run   <= 4'd0;
      stuff_last  <= 1'b0;
      stuff_valid <= 1'b0;
    end else if (!en) begin
      // Held in reset-like state while the host loads. The timer takes its
      // reset value of P-1 from the configuration as it arrives.
      rowp   <= {ADDR_W{1'b0}};
      link   <= {ADDR_W{1'b0}};
      sr     <= {SR_W{1'b0}};
      cnt    <= {CNT_W{1'b0}};
      c2     <= {CNT_W{1'b0}};
      crc    <= 5'h1F;
      tcount <= period_m1;
      pinv   <= cfg_init_pins;
      crc16       <= crc16_seed;
      stuff_run   <= 4'd0;
      stuff_last  <= 1'b0;
      stuff_valid <= 1'b0;
    end else begin
      rowp   <= row_next;
      link   <= link_next;
      sr     <= test_pass ? sr_next   : sr;
      cnt    <= test_pass ? cnt_next  : cnt;
      c2     <= test_pass ? c2_next   : c2;
      crc    <= test_pass ? crc_next  : crc;
      crc16       <= test_pass ? crc16_next        : crc16;
      stuff_run   <= test_pass ? stuff_run_next    : stuff_run;
      stuff_last  <= test_pass ? stuff_last_next   : stuff_last;
      stuff_valid <= test_pass ? stuff_valid_next  : stuff_valid;
      tcount <= tcount_next;
      pinv   <= test_pass ? pinv_next : pinv;
    end
  end

  // ---- step 7: drive the slots (SPEC sections 7 and 8.5) ----------------
  // Open drain: a 1 releases the net, a 0 drives it low.
  assign pin_out  = pinv & ~cfg_od_mask;
  assign pin_oe   = ~cfg_od_mask | ~pinv;
  assign row_addr = rowp;

  assign dbg_sr     = sr;
  assign dbg_cnt    = cnt;
  assign dbg_c2     = c2;
  assign dbg_crc    = crc;
  assign dbg_tcount = tcount;
  assign dbg_link   = link;
  assign dbg_pinv   = pinv;
  assign dbg_crc16       = crc16;
  assign dbg_stuff_run   = stuff_run;
  assign dbg_stuff_last  = stuff_last;
  assign dbg_stuff_valid = stuff_valid;

// ---------------------------------------------------------------------------
// Formal properties. Guarded so synthesis never parses them; `make formal`
// defines FORMAL and one P<n>. See docs/formal.md.
// ---------------------------------------------------------------------------
`ifdef FORMAL

  // Start from reset, once. Without this the proof also quantifies over
  // states no reset can produce, which is not what any of these claim.
  reg f_past_valid = 1'b0;
  always @(posedge clk) f_past_valid <= 1'b1;
  always @(posedge clk) if (!f_past_valid) assume (!rst_n);

`ifdef P1
  // P1 -- branch resolver totality (SPEC section 5).
  //
  // Transcribed from section 5's table as "which of the three sources does
  // each exit take", deliberately NOT as the implementation's exit_t/exit_f
  // pair. A copy of the implementation would agree with it by construction;
  // this agrees with it only if both read the table the same way, so a
  // priority slip or a swapped mode column in either one shows up.
  localparam [1:0] F_SRC_TGT = 2'd0, F_SRC_SELF = 2'd1, F_SRC_NEXT = 2'd2;
  reg [1:0] f_src_t, f_src_f;
  always @* begin
    case (f_mode)
      `STT_M_WAIT:   begin f_src_t = F_SRC_TGT;  f_src_f = F_SRC_SELF; end
      `STT_M_BRANCH: begin f_src_t = F_SRC_TGT;  f_src_f = F_SRC_NEXT; end
      `STT_M_SKIP:   begin f_src_t = F_SRC_NEXT; f_src_f = F_SRC_TGT;  end
      `STT_M_STEP:   begin f_src_t = F_SRC_NEXT; f_src_f = F_SRC_SELF; end
      default:       begin f_src_t = F_SRC_NEXT; f_src_f = F_SRC_SELF; end
    endcase
  end
  wire [1:0] f_src = test_pass ? f_src_t : f_src_f;

  // `next` = (row + 1) mod 32, written as the arithmetic the spec states
  // rather than as the implementation's compare-against-all-ones.
  wire [ADDR_W:0]   f_wide_next = {1'b0, rowp} + 1'b1;
  wire [ADDR_W-1:0] f_next_seq  = f_wide_next[ADDR_W-1:0];

  reg [ADDR_W-1:0] f_ref_row;
  always @* begin
    case (f_src)
      F_SRC_TGT:  f_ref_row = (f_tgt == `STT_RET) ? link_next
                                                  : f_tgt[ADDR_W-1:0];
      F_SRC_SELF: f_ref_row = rowp;
      default:    f_ref_row = f_next_seq;
    endcase
  end

  // The resolver agrees with section 5 for every (mode, target, row, outcome).
  always @* if (en) assert (row_next == f_ref_row);

  // A machine that is not enabled does not move.
  always @* if (!en) assert (row_next == rowp);

  // Totality. ADDR_W is 5, so this cannot fail in this implementation and is
  // reported as structural rather than as a result -- it is here so that
  // widening ADDR_W without widening the target handling fails loudly.
  always @* assert (row_next < `STT_ROWS);

  // RET is the target FIELD's property, not the true exit's: a SKIP row with
  // target 255 returns when its test FAILS. Stated separately because this is
  // the case that was wrong until 2026-09-16.
  always @* if (en && (f_mode == `STT_M_SKIP) && (f_tgt == `STT_RET) && !test_pass)
    assert (row_next == link_next);
  always @* if (en && (f_mode == `STT_M_SKIP) && (f_tgt == `STT_RET) && test_pass)
    assert (row_next == f_next_seq);
`endif

`ifdef P2
  // P2 -- action group mutual exclusion (SPEC section 6.1).
  //
  // Not a property of the encoder: a property of the decode, for every one of
  // the 2^32 row words a host can load. What it really checks is that the
  // generated constants in stt_isa.vh are distinct and that each flag's
  // comparison names the right ones -- a duplicated code, or a stray extra
  // term, makes two flags in a group fire at once and the if/else chains
  // downstream then silently drop one action.
  wire [3:0] f_n_sr = act_clr + act_load + act_loadcrc + act_loadk
                    + act_push + act_shift;
  wire [3:0] f_n_c1 = act_cload + act_cload_b + act_cload_c + act_cdec;
  wire [3:0] f_n_c2 = act_c2load + act_c2dec;
  wire [3:0] f_n_tm = act_trst + act_thalf;
  wire [3:0] f_n_xx = act_call + act_crcrst + act_crcstep
                    + act_crc16rst + act_crc16step + act_stuffrst;

  // at most one, except {clr, shift} may appear together
  always @* assert (f_n_sr <= 4'd1 || (act_clr && act_shift && f_n_sr == 4'd2));
  always @* assert (f_n_c1 <= 4'd1);
  always @* assert (f_n_c2 <= 4'd1);
  always @* assert (f_n_tm <= 4'd1);
  // at most one, except {crcrst, call} may appear together
  always @* assert (f_n_xx <= 4'd1 || (act_crcrst && act_call && f_n_xx == 4'd2));

  // Stated on its own because the datapath depends on this one specifically:
  // rx_data is sr_mid, the value before any shift, which is only the right
  // thing to push because a row cannot both push and shift.
  always @* assert (!(act_push && act_shift));
`endif

`endif
endmodule
`default_nettype wire
