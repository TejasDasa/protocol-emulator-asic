// tt_um_stt -- the Tiny Tapeout boundary, and nothing else.
//
// This is the submission top. Its port list is the eight signals Tiny Tapeout
// provides and no others: the host byte port reaches pins through the iomux
// (SPEC section 11.2) and the dbg_* observability that stt_chip carries for the
// lockstep testbench is terminated here rather than escaping to pads.
//
// Build with -DIMEM_MACRO to put the row array in CFGMEM_IHP16 macros, which is
// what the hardened design uses; without it the imem is flops, which is what
// the simulation testbenches use.
`default_nettype none
`include "stt_isa.vh"

// Machine count. A define rather than a parameter because the hardening flow
// sets it from outside and LibreLane has no way to override a top-level
// parameter, only to pass -D to synthesis.
`ifndef STT_NSM
  `define STT_NSM 5
`endif

module tt_um_stt (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);

  localparam integer NSM    = `STT_NSM;
  localparam integer SR_W   = 8;
  localparam integer CNT_W  = 8;
  localparam integer TIMER_W = 16;
  localparam integer NSLOT  = 3;
  localparam integer ADDR_W = `STT_ADDR_W;

  // Observability, terminated here. Left unconnected these would appear as
  // disconnected pins in a hardened design, which is the mistake section 16
  // records against rtl/stt_core's fixed_entry_i.
  wire [NSM*ADDR_W-1:0]  dbg_row;
  wire [NSM*SR_W-1:0]    dbg_sr;
  wire [NSM*CNT_W-1:0]   dbg_cnt;
  wire [NSM*CNT_W-1:0]   dbg_c2;
  wire [NSM*5-1:0]       dbg_crc;
  wire [NSM*TIMER_W-1:0] dbg_tcount;
  wire [NSM*ADDR_W-1:0]  dbg_link;
  wire [NSM*NSLOT-1:0]   dbg_pinv;
  wire [NSM*16-1:0]      dbg_crc16;
  wire [NSM*4-1:0]       dbg_stuff_run;
  wire [NSM-1:0]         dbg_stuff_last;
  wire [NSM-1:0]         dbg_stuff_valid;
  wire [NSM-1:0]         dbg_rx_ovf;
  wire [NSM-1:0]         dbg_tx_unf;
  wire                   dbg_run;
  wire                   dbg_en;

  stt_chip #(.NSM(NSM)) u_chip (
      .clk(clk), .rst_n(rst_n), .ena(ena),
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .dbg_rx_ovf(dbg_rx_ovf), .dbg_tx_unf(dbg_tx_unf),
      .dbg_row(dbg_row), .dbg_sr(dbg_sr), .dbg_cnt(dbg_cnt), .dbg_c2(dbg_c2),
      .dbg_crc(dbg_crc), .dbg_tcount(dbg_tcount), .dbg_link(dbg_link),
      .dbg_pinv(dbg_pinv), .dbg_crc16(dbg_crc16),
      .dbg_stuff_run(dbg_stuff_run), .dbg_stuff_last(dbg_stuff_last),
      .dbg_stuff_valid(dbg_stuff_valid),
      .dbg_run(dbg_run), .dbg_en(dbg_en)
  );

  // Keep the observability nets from being optimized into dangling pins while
  // making it explicit that nothing leaves the boundary through them.
  wire _unused = &{ena, 1'b0,
                   dbg_row, dbg_sr, dbg_cnt, dbg_c2, dbg_crc, dbg_tcount,
                   dbg_link, dbg_pinv, dbg_crc16, dbg_stuff_run,
                   dbg_stuff_last, dbg_stuff_valid, dbg_rx_ovf, dbg_tx_unf,
                   dbg_run, dbg_en};

endmodule
`default_nettype wire
