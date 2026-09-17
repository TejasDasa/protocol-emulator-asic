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
  wire act_push    = (a_sr == `STT_ASR_PUSH);
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

  // ---- shift register width and serial bit ------------------------------
  wire [SR_W:0]   mask_ext = ({{SR_W{1'b0}}, 1'b1} << cfg_sr_width) - 1'b1;
  wire [SR_W-1:0] sr_mask  = mask_ext[SR_W-1:0];
  wire [3:0]      msb_idx  = cfg_sr_width - 4'd1;

  function automatic srbit_of;
    input [SR_W-1:0] v;
    begin
      srbit_of = cfg_shift_left ? v[msb_idx] : v[0];
    end
  endfunction

  // ---- step 1: the timer tick, before anything else ---------------------
  wire tick = (tcount == {TIMER_W{1'b0}});

  // ---- step 2: the test, on state as it stands at the start of the cycle -
  wire srbit_pre = srbit_of(sr);
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
      default:       test_pass = 1'b0;   // codes 10-15 unassigned (SPEC section 4)
    endcase
  end
  wire fire = en & test_pass;

  // ---- step 3: actions, in the SPEC section 6.3 order --------------------
  // sr_mid: after load / loadk / loadcrc / clr, which precede crcstep.
  reg [SR_W-1:0] sr_mid;
  always @* begin
    if      (act_load)    sr_mid = tx_data  & sr_mask;
    else if (act_loadk)   sr_mid = cfg_loadk & sr_mask;
    else if (act_loadcrc) sr_mid = {{(SR_W-5){1'b0}}, ~crc};
    else if (act_clr)     sr_mid = {SR_W{1'b0}};
    else                  sr_mid = sr;
  end
  wire srbit_mid = srbit_of(sr_mid);

  // crc: crcrst then crcstep, both after the loads above.
  wire [4:0] crc_stepped = ((crc[0] ^ srbit_mid) ? ((crc >> 1) ^ 5'h14)
                                                 : (crc >> 1));
  reg [4:0] crc_next;
  always @* begin
    if      (act_crcrst)  crc_next = 5'h1F;
    else if (act_crcstep) crc_next = crc_stepped;
    else                  crc_next = crc;
  end

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
  assign tx_pop  = fire & act_load;

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
  wire srbit_post = srbit_of(sr_next);
  reg [NSLOT-1:0] pinv_next;
  always @* begin
    pinv_next = pinv;
    if (f_slot == `STT_SLOT_PAIR) begin
      case (f_pinop)
        `STT_P_LO:  begin pinv_next[0] = 1'b0;        pinv_next[1] = 1'b0;        end
        `STT_P_HI:  begin pinv_next[0] = 1'b1;        pinv_next[1] = 1'b1;        end
        `STT_P_SR:  begin pinv_next[0] = srbit_post;  pinv_next[1] = ~srbit_post; end
        `STT_P_TGL: begin pinv_next[0] = ~pinv[0];    pinv_next[1] = ~pinv[1];    end
        `STT_P_D0:  begin pinv_next[0] = 1'b0;        pinv_next[1] = 1'b1;        end
        `STT_P_D1:  begin pinv_next[0] = 1'b1;        pinv_next[1] = 1'b0;        end
        default:    ;                                 // hold
      endcase
    end else begin
      case (f_pinop)
        `STT_P_LO:  pinv_next[f_slot] = 1'b0;
        `STT_P_HI:  pinv_next[f_slot] = 1'b1;
        `STT_P_SR:  pinv_next[f_slot] = srbit_post;
        `STT_P_TGL: pinv_next[f_slot] = ~pinv[f_slot];
        // hold, and d0/d1 on a single slot: no write (SPEC section 7).
        default:    ;
      endcase
    end
  end

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
      `STT_M_SKIP:   begin exit_t = next_seq; exit_f = tgt_row;  t_from_tgt = 1'b0; f_from_tgt = 1'b1; end
      default:       begin exit_t = next_seq; exit_f = rowp;     t_from_tgt = 1'b0; f_from_tgt = 1'b0; end
    endcase
  end

  // `call` writes the row's FALSE exit, and RET resolves against the value the
  // link register holds AFTER this row's own call, matching SttCore.step.
  wire [ADDR_W-1:0] link_next = (fire & act_call) ? exit_f : link;

  reg [ADDR_W-1:0] row_next;
  always @* begin
    if (!en)             row_next = rowp;
    else if (test_pass)  row_next = (t_from_tgt & tgt_ret) ? link_next : exit_t;
    else                 row_next = (f_from_tgt & tgt_ret) ? link_next : exit_f;
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
    end else begin
      rowp   <= row_next;
      link   <= link_next;
      sr     <= test_pass ? sr_next   : sr;
      cnt    <= test_pass ? cnt_next  : cnt;
      c2     <= test_pass ? c2_next   : c2;
      crc    <= test_pass ? crc_next  : crc;
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

endmodule
`default_nettype wire
