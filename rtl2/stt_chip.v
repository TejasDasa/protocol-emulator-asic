// stt_chip -- NSM machines behind the Tiny Tapeout boundary, with the pin
// assignment and the run flag of SPEC section 11.1.
//
// Still missing, and next: the shared host FIFOs. Until they exist the
// per-machine host byte interface is brought out as ports, which is not
// TT-legal -- the real top has only ui_in/uo_out/uio. They are marked below and
// `stt_hostbuf` replaces them.
//
// BRING-UP ORDER (SPEC section 10):
//   1. hold rst_n low, then release. `run` is 0, so ui_in[6:0] and uio_in[7:5]
//      are the host's.
//   2. for each machine: drive uio_in[7:5] with its index, shift in its
//      configuration (ui_in[1]) and its program (ui_in[0]), honouring
//      uo_out[0] = busy after every row, and loading all 32 rows.
//   3. shift in the pin assignment and, as the last bit, `run` (ui_in[2]).
//   4. `run` goes high. The machines start, every pin belongs to the iomux, and
//      nothing is reserved. Reprogramming means asserting rst_n.
//
// Inputs must have been stable for at least two cycles before the machines
// start (SPEC section 8.3). Step 2 takes thousands of cycles, so this is free.
`default_nettype none
`include "stt_isa.vh"

module stt_chip #(
    parameter NSM     = 5,
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
    input  wire               ena,

    // Tiny Tapeout boundary
    input  wire [7:0]         ui_in,
    output wire [7:0]         uo_out,
    input  wire [7:0]         uio_in,
    output wire [7:0]         uio_out,
    output wire [7:0]         uio_oe,

    // TEMPORARY: replaced by stt_hostbuf. Not part of the TT boundary.
    input  wire [NSM*SR_W-1:0] tx_data,
    input  wire [NSM-1:0]      tx_ne,
    output wire [NSM-1:0]      tx_pop,
    output wire [NSM*SR_W-1:0] rx_data,
    output wire [NSM-1:0]      rx_push,

    // observability for the lockstep testbench
    output wire [NSM*ADDR_W-1:0]  dbg_row,
    output wire [NSM*SR_W-1:0]    dbg_sr,
    output wire [NSM*CNT_W-1:0]   dbg_cnt,
    output wire [NSM*CNT_W-1:0]   dbg_c2,
    output wire [NSM*5-1:0]       dbg_crc,
    output wire [NSM*TIMER_W-1:0] dbg_tcount,
    output wire [NSM*ADDR_W-1:0]  dbg_link,
    output wire [NSM*NSLOT-1:0]   dbg_pinv,
    output wire                   dbg_run,
    output wire                   dbg_en
);

  wire run;
  wire imem_ld_busy;

  // Machines start TWO cycles after run, not on it.
  //
  // SPEC section 8.3 requires that a machine not be enabled until its inputs
  // have been stable for two cycles, because the input synchronizer reads low
  // until then. The host cannot satisfy that here: run is the last bit of the
  // pin-assignment chain, so ui_in is carrying chain data right up to the
  // moment it goes high, and the synchronizers are full of it. Releasing the
  // pins on run and starting the machines two cycles later lets the
  // synchronizers fill with real input first, so the requirement is met by
  // construction instead of being an obligation a host can forget.
  //
  // Found by rtl2/tb/test_chip.py: uart_rx took its start-bit branch on cycle 0
  // because its assigned ui_in pin had last carried a chain bit.
  reg [1:0] run_dly;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) run_dly <= 2'b00;
    else        run_dly <= {run_dly[0], run};
  end
  wire machines_en = ena & run_dly[1];

  // Control is decoded ONLY while run is low. Once the host sets run, a
  // protocol driving ui_in[0] high can no longer start an instruction-memory
  // load, which is the whole point of the flag.
  wire imem_ld_en = ~run & ui_in[0];
  wire cfg_ld_en  = ~run & ui_in[1];
  wire sel_ld_en  = ~run & ui_in[2];
  wire ld_in      =        ui_in[4];
  wire [2:0] sm_sel = uio_in[7:5];

  wire [NSM*NSLOT-1:0] sm_out, sm_oe;
  wire [NSM*NIN-1:0]   sm_in;

  stt_array #(.NSM(NSM), .ROW_W(ROW_W), .ROWS(ROWS), .ADDR_W(ADDR_W),
              .SR_W(SR_W), .CNT_W(CNT_W), .TIMER_W(TIMER_W), .NSLOT(NSLOT),
              .NIN(NIN))
  u_array (
      .clk(clk), .rst_n(rst_n),
      .en(machines_en),
      .sm_sel(sm_sel),
      .imem_ld_en(imem_ld_en), .cfg_ld_en(cfg_ld_en), .ld_in(ld_in),
      .imem_ld_busy(imem_ld_busy),
      .tx_data(tx_data), .tx_ne(tx_ne), .tx_pop(tx_pop),
      .rx_data(rx_data), .rx_push(rx_push),
      .pin_in(sm_in), .pin_out(sm_out), .pin_oe(sm_oe),
      .dbg_row(dbg_row), .dbg_sr(dbg_sr), .dbg_cnt(dbg_cnt), .dbg_c2(dbg_c2),
      .dbg_crc(dbg_crc), .dbg_tcount(dbg_tcount), .dbg_link(dbg_link),
      .dbg_pinv(dbg_pinv)
  );

  wire [7:0] mux_uo, mux_uio_out, mux_uio_oe;

  stt_iomux #(.NSM(NSM), .NSLOT(NSLOT), .NIN(NIN))
  u_iomux (
      .clk(clk), .rst_n(rst_n),
      .sel_ld_en(sel_ld_en), .sel_ld_in(ld_in), .sel_ld_out(), .run(run),
      .sm_out(sm_out), .sm_oe(sm_oe), .sm_in(sm_in),
      .ui_in(ui_in), .uo_out(mux_uo),
      .uio_in(uio_in), .uio_out(mux_uio_out), .uio_oe(mux_uio_oe)
  );

  // Before run the iomux outputs are meaningless -- no pin assignment has been
  // loaded -- so uo_out carries loader status instead. That is how the host
  // sees the busy flag SPEC section 10 requires it to honour, without spending
  // a pin that operation would need.
  assign uo_out  = run ? mux_uo : {7'b0, imem_ld_busy};
  assign uio_out = run ? mux_uio_out : 8'b0;
  assign uio_oe  = run ? mux_uio_oe  : 8'b0;

  assign dbg_run = run;
  assign dbg_en  = machines_en;

endmodule
`default_nettype wire
