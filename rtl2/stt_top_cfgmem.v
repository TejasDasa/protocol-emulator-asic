// stt_top_cfgmem -- stt_top with the instruction memory in CFGMEM_IHP16 macros.
//
// Same ports as stt_top so the lockstep testbenches drive it unchanged: the
// whole point is that swapping the memory changes nothing observable.
`default_nettype none
`include "stt_isa.vh"

module stt_top_cfgmem #(
    parameter ROW_W   = `STT_ROW_W,
    parameter ROWS    = `STT_ROWS,
    parameter ADDR_W  = `STT_ADDR_W,
    parameter SR_W    = 8,
    parameter CNT_W   = 8,
    parameter TIMER_W = 16,
    parameter NSLOT   = 3,
    parameter NIN     = 2
) (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               en,
    input  wire               imem_ld_en,
    input  wire               cfg_ld_en,
    input  wire               ld_in,
    output wire               imem_ld_out,
    output wire               cfg_ld_out,
    output wire [ADDR_W-1:0]  imem_ld_addr,
    output wire               imem_ld_busy,
    input  wire [SR_W-1:0]    tx_data,
    input  wire               tx_ne,
    output wire               tx_pop,
    output wire [SR_W-1:0]    rx_data,
    output wire               rx_push,
    input  wire [NIN-1:0]     pin_in,
    output wire [NSLOT-1:0]   pin_out,
    output wire [NSLOT-1:0]   pin_oe,
    output wire [ADDR_W-1:0]  dbg_row,
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

  wire [ROW_W-1:0]   row;
  wire [TIMER_W-1:0] cfg_period;
  wire               cfg_shift_left;
  wire [1:0]         cfg_fill;
  wire [3:0]         cfg_sr_width;
  wire [CNT_W-1:0]   cfg_cload_a, cfg_cload_b, cfg_cload_c, cfg_c2load;
  wire [SR_W-1:0]    cfg_loadk;
  wire [NSLOT-1:0]   cfg_init_pins, cfg_od_mask;
  wire [15:0]        cfg_crc16_poly;
  wire [4:0]         cfg_crc16_width;
  wire               cfg_crc16_reflect, cfg_crc16_seed_ones;
  wire [3:0]         cfg_stuff_n;
  wire               cfg_stuff_ones;
  wire [NSLOT-1:0]   cfg_stuff_slots;

  stt_config #(.TIMER_W(TIMER_W), .SR_W(SR_W), .CNT_W(CNT_W), .NSLOT(NSLOT))
  u_cfg (
      .clk(clk), .rst_n(rst_n), .ld_en(cfg_ld_en), .ld_in(ld_in),
      .ld_out(cfg_ld_out),
      .cfg_period(cfg_period), .cfg_shift_left(cfg_shift_left),
      .cfg_fill(cfg_fill), .cfg_sr_width(cfg_sr_width),
      .cfg_cload_a(cfg_cload_a), .cfg_cload_b(cfg_cload_b),
      .cfg_cload_c(cfg_cload_c), .cfg_c2load(cfg_c2load),
      .cfg_loadk(cfg_loadk), .cfg_init_pins(cfg_init_pins),
      .cfg_od_mask(cfg_od_mask),
      .cfg_crc16_poly(cfg_crc16_poly), .cfg_crc16_width(cfg_crc16_width),
      .cfg_crc16_reflect(cfg_crc16_reflect),
      .cfg_crc16_seed_ones(cfg_crc16_seed_ones),
      .cfg_stuff_n(cfg_stuff_n), .cfg_stuff_ones(cfg_stuff_ones),
      .cfg_stuff_slots(cfg_stuff_slots)
  );

  stt_imem_cfgmem #(.ROW_W(ROW_W), .ROWS(ROWS), .ADDR_W(ADDR_W))
  u_imem (
      .clk(clk), .rst_n(rst_n),
      .addr(dbg_row), .row(row),
      .ld_en(imem_ld_en), .ld_in(ld_in),
      .ld_out(imem_ld_out), .ld_addr(imem_ld_addr), .ld_busy(imem_ld_busy)
  );

  stt_core #(.ROW_W(ROW_W), .ADDR_W(ADDR_W), .SR_W(SR_W), .CNT_W(CNT_W),
             .TIMER_W(TIMER_W), .NSLOT(NSLOT), .NIN(NIN))
  u_core (
      .clk(clk), .rst_n(rst_n), .en(en),
      .row_addr(dbg_row), .row(row),
      .cfg_period(cfg_period), .cfg_shift_left(cfg_shift_left),
      .cfg_fill(cfg_fill), .cfg_sr_width(cfg_sr_width),
      .cfg_cload_a(cfg_cload_a), .cfg_cload_b(cfg_cload_b),
      .cfg_cload_c(cfg_cload_c), .cfg_c2load(cfg_c2load),
      .cfg_loadk(cfg_loadk), .cfg_init_pins(cfg_init_pins),
      .cfg_od_mask(cfg_od_mask),
      .cfg_crc16_poly(cfg_crc16_poly), .cfg_crc16_width(cfg_crc16_width),
      .cfg_crc16_reflect(cfg_crc16_reflect),
      .cfg_crc16_seed_ones(cfg_crc16_seed_ones),
      .cfg_stuff_n(cfg_stuff_n), .cfg_stuff_ones(cfg_stuff_ones),
      .cfg_stuff_slots(cfg_stuff_slots),
      .tx_data(tx_data), .tx_ne(tx_ne), .tx_pop(tx_pop),
      .rx_data(rx_data), .rx_push(rx_push),
      .pin_in(pin_in), .pin_out(pin_out), .pin_oe(pin_oe),
      .dbg_sr(dbg_sr), .dbg_cnt(dbg_cnt), .dbg_c2(dbg_c2), .dbg_crc(dbg_crc),
      .dbg_tcount(dbg_tcount), .dbg_link(dbg_link), .dbg_pinv(dbg_pinv),
      .dbg_crc16(dbg_crc16), .dbg_stuff_run(dbg_stuff_run),
      .dbg_stuff_last(dbg_stuff_last), .dbg_stuff_valid(dbg_stuff_valid)
  );

endmodule
`default_nettype wire
