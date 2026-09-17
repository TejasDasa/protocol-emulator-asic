// stt_array -- NSM independent state machines.
//
// Replication and nothing else. Each machine has its own imem, its own
// configuration register and its own core, and the only thing they share is the
// clock, the reset and the serial load data. There is deliberately no iomux, no
// run flag and no shared host FIFO yet: pins and host bytes come out per
// machine, flattened, so this can be proven independent before anything is
// shared. Those come next.
//
// SPEC section 10: the load enables address ONE machine at a time, selected by
// `sm_sel`. That is not only an interface convenience. Without a per-machine
// select every instance receives the same serial stream, ends up holding
// identical state, and synthesis merges them -- a real measurement error found
// and documented in docs/area-study.md. rtl2/tb/test_multi.py is the functional
// counterpart: it loads a DIFFERENT program into every machine and checks all of
// them against their own models on every cycle, so merged or cross-talking
// instances cannot pass.
`default_nettype none
`include "stt_isa.vh"

// Which machine to replicate. The two have identical port lists by
// construction, so only the name changes; -DIMEM_MACRO selects the CFGMEM one.
`ifdef IMEM_MACRO
  `define STT_MACHINE stt_top_cfgmem
`else
  `define STT_MACHINE stt_top
`endif

module stt_array #(
    parameter NSM     = 5,
    parameter ROW_W   = `STT_ROW_W,
    parameter ROWS    = `STT_ROWS,
    parameter ADDR_W  = `STT_ADDR_W,
    parameter SR_W    = 8,
    parameter CNT_W   = 8,
    parameter TIMER_W = 16,
    parameter NSLOT   = 3,
    parameter NIN     = 2,
    parameter SELW    = 3
) (
    input  wire                  clk,
    input  wire                  rst_n,
    input  wire                  en,

    // serial load, addressed one machine at a time
    input  wire [SELW-1:0]       sm_sel,
    input  wire                  imem_ld_en,
    input  wire                  cfg_ld_en,
    input  wire                  ld_in,
    output wire                  imem_ld_busy,   // of the SELECTED machine

    // host byte interface, per machine
    input  wire [NSM*SR_W-1:0]   tx_data,
    input  wire [NSM-1:0]        tx_ne,
    output wire [NSM-1:0]        tx_pop,
    output wire [NSM*SR_W-1:0]   rx_data,
    output wire [NSM-1:0]        rx_push,

    // pins, per machine
    input  wire [NSM*NIN-1:0]    pin_in,
    output wire [NSM*NSLOT-1:0]  pin_out,
    output wire [NSM*NSLOT-1:0]  pin_oe,

    // observability, per machine
    output wire [NSM*ADDR_W-1:0]  dbg_row,
    output wire [NSM*SR_W-1:0]    dbg_sr,
    output wire [NSM*CNT_W-1:0]   dbg_cnt,
    output wire [NSM*CNT_W-1:0]   dbg_c2,
    output wire [NSM*5-1:0]       dbg_crc,
    output wire [NSM*TIMER_W-1:0] dbg_tcount,
    output wire [NSM*ADDR_W-1:0]  dbg_link,
    output wire [NSM*NSLOT-1:0]   dbg_pinv,
    output wire [NSM*16-1:0]      dbg_crc16,
    output wire [NSM*4-1:0]       dbg_stuff_run,
    output wire [NSM-1:0]         dbg_stuff_last,
    output wire [NSM-1:0]         dbg_stuff_valid
);

  wire [NSM-1:0] busy;

  genvar g;
  generate
    for (g = 0; g < NSM; g = g + 1) begin : g_sm
      wire sel_g = (sm_sel == g[SELW-1:0]);

      `STT_MACHINE #(.ROW_W(ROW_W), .ROWS(ROWS), .ADDR_W(ADDR_W), .SR_W(SR_W),
                .CNT_W(CNT_W), .TIMER_W(TIMER_W), .NSLOT(NSLOT), .NIN(NIN))
      u_sm (
          .clk(clk), .rst_n(rst_n), .en(en),
          .imem_ld_en (imem_ld_en & sel_g),
          .cfg_ld_en  (cfg_ld_en  & sel_g),
          .ld_in      (ld_in),
          .imem_ld_out(),                     // per-machine chain output unused
          .cfg_ld_out (),
          .imem_ld_addr(),
          .imem_ld_busy(busy[g]),
          .tx_data (tx_data[g*SR_W +: SR_W]),
          .tx_ne   (tx_ne[g]),
          .tx_pop  (tx_pop[g]),
          .rx_data (rx_data[g*SR_W +: SR_W]),
          .rx_push (rx_push[g]),
          .pin_in  (pin_in[g*NIN   +: NIN]),
          .pin_out (pin_out[g*NSLOT +: NSLOT]),
          .pin_oe  (pin_oe[g*NSLOT  +: NSLOT]),
          .dbg_row   (dbg_row[g*ADDR_W  +: ADDR_W]),
          .dbg_sr    (dbg_sr[g*SR_W     +: SR_W]),
          .dbg_cnt   (dbg_cnt[g*CNT_W   +: CNT_W]),
          .dbg_c2    (dbg_c2[g*CNT_W    +: CNT_W]),
          .dbg_crc   (dbg_crc[g*5       +: 5]),
          .dbg_tcount(dbg_tcount[g*TIMER_W +: TIMER_W]),
          .dbg_link  (dbg_link[g*ADDR_W +: ADDR_W]),
          .dbg_pinv  (dbg_pinv[g*NSLOT  +: NSLOT]),
          .dbg_crc16 (dbg_crc16[g*16   +: 16]),
          .dbg_stuff_run  (dbg_stuff_run[g*4 +: 4]),
          .dbg_stuff_last (dbg_stuff_last[g]),
          .dbg_stuff_valid(dbg_stuff_valid[g])
      );
    end
  endgenerate

  // Only the selected machine is being loaded, so its busy is the one the host
  // must honour.
  assign imem_ld_busy = busy[sm_sel[SELW-1:0]];

endmodule
`default_nettype wire
