// stt_core -- one STT state machine: decode + palette + datapath + imem.
//
// Every input of every submodule is driven either from a top-level port or from
// another submodule; nothing is tied off, so Yosys cannot constant-propagate a
// block away.  Check with the cell counts in the hierarchical run.
`default_nettype none

module stt_core #(
    parameter ROW_W   = 21,
    parameter ROWS    = 32,
    parameter ADDR_W  = 5,
    parameter ENTRY_W = 13,
    parameter NFIXED  = 24,
    parameter NLOAD   = 8,
    parameter SR_W    = 8,
    parameter CNT_W   = 8,
    parameter TIMER_W = 16,
    parameter NSLOT   = 3,
    parameter NIN     = 2
) (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               en,

    // program / palette / config load
    input  wire               imem_ld_en,
    input  wire               pal_ld_en,
    input  wire               cfg_ld_en,
    input  wire               ld_in,
    output wire               imem_ld_out,
    output wire               pal_ld_out,
    output wire               cfg_ld_out,
    output wire [ADDR_W-1:0]  imem_ld_addr,

    // host byte interface
    input  wire [SR_W-1:0]    tx_data,
    input  wire               tx_ne,        // TX FIFO not empty -> the `fifo` test
    output wire               tx_pop,
    output wire [SR_W-1:0]    rx_data,
    output wire               rx_push,

    // pins
    input  wire [NIN-1:0]     pin_in,
    output wire [NSLOT-1:0]   pin_out,
    output wire [NSLOT-1:0]   pin_oe,

    // observability
    output wire [ADDR_W-1:0]  row_addr
);

  // ---- interconnect ----------------------------------------------------
  wire [ROW_W-1:0] row;
  wire [4:0]       act_index;
  wire [1:0]       pin_slot;
  wire [2:0]       pin_op;
  wire             fire;

  wire tmr_tick, cz, c2z, srbit, in0_s, in1_s;

  wire act_load, act_loadk, act_loadcrc, act_clr, act_shift, act_push;
  wire act_cload, act_cload_b, act_cload_c, act_cdec;
  wire act_c2load, act_c2dec, act_trst, act_thalf;
  wire act_crcrst, act_crcstep, act_call;

  wire [ENTRY_W-1:0] pal_entry;

  // ---- instruction memory ---------------------------------------------
  stt_imem #(.ROW_W(ROW_W), .ROWS(ROWS), .ADDR_W(ADDR_W)) u_imem (
      .clk     (clk),
      .rst_n   (rst_n),
      .addr    (row_addr),
      .row     (row),
      .ld_en   (imem_ld_en),
      .ld_in   (ld_in),
      .ld_out  (imem_ld_out),
      .ld_addr (imem_ld_addr)
  );

  // ---- decode -----------------------------------------------------------
  stt_decode #(.ROW_W(ROW_W), .ROWS(ROWS), .ADDR_W(ADDR_W)) u_decode (
      .clk       (clk),
      .rst_n     (rst_n),
      .en        (en),
      .row       (row),
      .tmr_tick  (tmr_tick),
      .fifo_ne   (tx_ne),
      .cz        (cz),
      .c2z       (c2z),
      .srbit     (srbit),
      .in0_s     (in0_s),
      .in1_s     (in1_s),
      .act_call  (act_call),
      .row_addr  (row_addr),
      .act_index (act_index),
      .pin_slot  (pin_slot),
      .pin_op    (pin_op),
      .fire      (fire)
  );

  // ---- action-set palette ----------------------------------------------
  stt_palette #(.ENTRY_W(ENTRY_W), .NFIXED(NFIXED), .NLOAD(NLOAD)) u_palette (
      .clk         (clk),
      .rst_n       (rst_n),
      .index       (act_index),
      .ld_en       (pal_ld_en),
      .ld_in       (ld_in),
      .ld_out      (pal_ld_out),
      .entry       (pal_entry),
      .act_load    (act_load),
      .act_loadk   (act_loadk),
      .act_loadcrc (act_loadcrc),
      .act_clr     (act_clr),
      .act_shift   (act_shift),
      .act_push    (act_push),
      .act_cload   (act_cload),
      .act_cload_b (act_cload_b),
      .act_cload_c (act_cload_c),
      .act_cdec    (act_cdec),
      .act_c2load  (act_c2load),
      .act_c2dec   (act_c2dec),
      .act_trst    (act_trst),
      .act_thalf   (act_thalf),
      .act_crcrst  (act_crcrst),
      .act_crcstep (act_crcstep),
      .act_call    (act_call)
  );

  // ---- datapath ---------------------------------------------------------
  stt_datapath #(
      .SR_W(SR_W), .CNT_W(CNT_W), .TIMER_W(TIMER_W), .NSLOT(NSLOT), .NIN(NIN)
  ) u_datapath (
      .clk         (clk),
      .rst_n       (rst_n),
      .en          (en),
      .fire        (fire),
      .act_load    (act_load),
      .act_loadk   (act_loadk),
      .act_loadcrc (act_loadcrc),
      .act_clr     (act_clr),
      .act_shift   (act_shift),
      .act_push    (act_push),
      .act_cload   (act_cload),
      .act_cload_b (act_cload_b),
      .act_cload_c (act_cload_c),
      .act_cdec    (act_cdec),
      .act_c2load  (act_c2load),
      .act_c2dec   (act_c2dec),
      .act_trst    (act_trst),
      .act_thalf   (act_thalf),
      .act_crcrst  (act_crcrst),
      .act_crcstep (act_crcstep),
      .pin_slot    (pin_slot),
      .pin_op      (pin_op),
      .tx_data     (tx_data),
      .tx_pop      (tx_pop),
      .rx_data     (rx_data),
      .rx_push     (rx_push),
      .cfg_ld_en   (cfg_ld_en),
      .cfg_ld_in   (ld_in),
      .cfg_ld_out  (cfg_ld_out),
      .pin_in      (pin_in),
      .pin_out     (pin_out),
      .pin_oe      (pin_oe),
      .tmr_tick    (tmr_tick),
      .cz          (cz),
      .c2z         (c2z),
      .srbit       (srbit),
      .in0_s       (in0_s),
      .in1_s       (in1_s)
  );

endmodule
`default_nettype wire
