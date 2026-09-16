// stt_chip -- NSM state machines plus everything they share, at the real
// Tiny Tapeout boundary.
//
// This exists to answer one question properly: how many state machines fit?
// Synthesising it at several NSM and fitting a line gives
//
//     area(NSM) = FIXED + NSM * PER_SM
//
// where FIXED is genuinely paid once (shared palette ROM, shared TX/RX FIFOs,
// shared CRC and bit stuffer, pin-select registers) and PER_SM is everything
// that replicates. Solving for NSM against the measured 6x4 core area is then
// a budget, not a ceiling with a caveat.
//
// Shared here, per the study's conclusions:
//   * stt_palette_fixed  -- 24 constant entries, one ROM for all SMs
//   * stt_hostbuf        -- one TX and one RX FIFO with round-robin arbitration
//   * crc_lfsr16         -- one programmable CRC unit
//   * bit_stuffer        -- one configurable stuffer
//   * stt_iomux          -- pin assignment onto ui/uo/uio
// Replicated: stt_decode, stt_datapath, stt_config, stt_imem, stt_palette_load.
`default_nettype none

module stt_chip #(
    parameter NSM        = 2,
    parameter ROW_W      = 21,
    parameter ROWS       = 32,
    parameter ADDR_W     = 5,
    parameter ENTRY_W    = 13,
    parameter NFIXED     = 24,
    parameter NLOAD      = 8,
    parameter SR_W       = 8,
    parameter CNT_W      = 8,
    parameter TIMER_W    = 16,
    parameter NSLOT      = 3,
    parameter NIN        = 2,
    parameter FIFO_DEPTH = 8
) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       ena,

    // Tiny Tapeout boundary
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,

    // Measurement scaffold, NOT part of the TT boundary.
    // Every status/observability signal below would otherwise dangle, and Yosys
    // would delete the logic that drives it -- understating the area we are
    // trying to measure. XOR-reducing them into one pin keeps that logic alive.
    // A real tapeout would instead read these back over uio; the reduction tree
    // itself is reported separately in docs/area-study.md so it can be
    // subtracted.
    output wire       obs
);

  // ui_in doubles as the control/load port while the chip is being programmed;
  // every one of these is driven from a real pin so nothing optimises away.
  wire imem_ld_en = ui_in[0];
  wire pal_ld_en  = ui_in[1];
  wire cfg_ld_en  = ui_in[2];
  wire sel_ld_en  = ui_in[3];
  wire ld_in      = ui_in[4];
  wire host_tx_we = ui_in[5];
  wire host_rx_re = ui_in[6];

  // ---- shared fixed palette ROM -----------------------------------------
  wire [4:0]         pal_index  [0:NSM-1];
  wire [ENTRY_W-1:0] fixed_entry;
  // All SMs index the one ROM. With a single ROM the SMs must agree on the
  // index in a given cycle; a real build would either replicate the ROM (it is
  // only 379 um2) or pipeline access. Structurally this is the shared case,
  // which is what we are pricing.
  wire [4:0] shared_index = pal_index[0];

  stt_palette_fixed #(.ENTRY_W(ENTRY_W)) u_shared_rom (
      .index (shared_index),
      .entry (fixed_entry)
  );

  // ---- per-SM signals ----------------------------------------------------
  wire [NSM-1:0]        tx_pop, rx_push, tx_ne;
  wire [SR_W-1:0]       tx_data;
  wire [NSM*SR_W-1:0]   rx_data_flat;
  wire [NSM*NSLOT-1:0]  sm_out, sm_oe;
  wire [NSM*NIN-1:0]    sm_in;
  wire [NSM-1:0]        imem_ld_out, pal_ld_out, cfg_ld_out;
  wire [NSM*ADDR_W-1:0] imem_ld_addr_flat, row_addr_flat;

  // Programming targets one state machine at a time: uio_in[7:5] names which.
  // Without this every SM would receive the same serial stream, end up holding
  // identical state, and Yosys would merge the instances after flatten --
  // understating the per-SM cost by roughly 180 flops. A real host programs
  // them one at a time anyway.
  wire [2:0] sm_sel = uio_in[7:5];

  genvar g;
  generate
    for (g = 0; g < NSM; g = g + 1) begin : g_sm
      wire sel_g = (sm_sel == g[2:0]);
      stt_core #(
          .ROW_W(ROW_W), .ROWS(ROWS), .ADDR_W(ADDR_W), .ENTRY_W(ENTRY_W),
          .NFIXED(NFIXED), .NLOAD(NLOAD), .SR_W(SR_W), .CNT_W(CNT_W),
          .TIMER_W(TIMER_W), .NSLOT(NSLOT), .NIN(NIN),
          .EXT_FIXED(1)
      ) u_core (
          .clk           (clk),
          .rst_n         (rst_n),
          .en            (ena),
          .imem_ld_en    (imem_ld_en & sel_g),
          .pal_ld_en     (pal_ld_en & sel_g),
          .cfg_ld_en     (cfg_ld_en & sel_g),
          .ld_in         (ld_in),
          .imem_ld_out   (imem_ld_out[g]),
          .pal_ld_out    (pal_ld_out[g]),
          .cfg_ld_out    (cfg_ld_out[g]),
          .imem_ld_addr  (imem_ld_addr_flat[g*ADDR_W +: ADDR_W]),
          .tx_data       (tx_data),
          .tx_ne         (tx_ne[g]),
          .tx_pop        (tx_pop[g]),
          .rx_data       (rx_data_flat[g*SR_W +: SR_W]),
          .rx_push       (rx_push[g]),
          .pin_in        (sm_in[g*NIN +: NIN]),
          .pin_out       (sm_out[g*NSLOT +: NSLOT]),
          .pin_oe        (sm_oe[g*NSLOT +: NSLOT]),
          .fixed_entry_i (fixed_entry),
          .pal_index_o   (pal_index[g]),
          .row_addr      (row_addr_flat[g*ADDR_W +: ADDR_W])
      );
    end
  endgenerate

  // ---- shared TX/RX buffering -------------------------------------------
  wire [SR_W-1:0] host_rx_rd_data, host_tx_level, host_rx_level;
  wire            host_tx_full, host_rx_ne;
  wire [NSM-1:0]  tx_grant, rx_grant;

  stt_hostbuf #(.NSM(NSM), .SR_W(SR_W), .FIFO_DEPTH(FIFO_DEPTH)) u_hostbuf (
      .clk (clk), .rst_n (rst_n),
      .tx_pop (tx_pop), .tx_data (tx_data), .tx_ne (tx_ne),
      .rx_push (rx_push), .rx_data_flat (rx_data_flat),
      .host_tx_wr_en (host_tx_we), .host_tx_wr_data (uio_in),
      .host_tx_full (host_tx_full),
      .host_rx_rd_en (host_rx_re), .host_rx_rd_data (host_rx_rd_data),
      .host_rx_ne (host_rx_ne),
      .host_tx_level (host_tx_level), .host_rx_level (host_rx_level),
      .tx_grant (tx_grant), .rx_grant (rx_grant)
  );

  // ---- shared CRC and bit stuffer ---------------------------------------
  wire [15:0] crc_q;
  wire        crc_bit;
  crc_lfsr16 #(.W(16)) u_crc (
      .clk (clk), .rst_n (rst_n),
      .poly_in    ({uio_in, ui_in}),
      .poly_we    (ui_in[7]),
      .reflect_in (ui_in[4]),
      .reflect_we (ui_in[7]),
      .en         (ena),
      .seed       (ui_in[3]),
      .seed_ones  (ui_in[2]),
      .data_bit   (sm_out[0]),
      .crc        (crc_q),
      .crc_bit    (crc_bit)
  );

  wire stuff_out, stuff_valid, stuff_in_ready, stuff_stuffed;
  bit_stuffer #(.CNT_W(4)) u_stuffer (
      .clk (clk), .rst_n (rst_n),
      .n_in           (uio_in[3:0]),
      .n_we           (ui_in[7]),
      .mode_insert_in (ui_in[6]),
      .mode_ones_in   (ui_in[5]),
      .mode_we        (ui_in[7]),
      .en             (ena),
      .flush          (ui_in[0]),
      .in_valid       (host_rx_ne),
      .in_bit         (crc_bit),
      .in_ready       (stuff_in_ready),
      .out_valid      (stuff_valid),
      .out_bit        (stuff_out),
      .out_stuffed    (stuff_stuffed)
  );

  // ---- pin assignment ----------------------------------------------------
  wire sel_ld_out;
  stt_iomux #(.NSM(NSM), .NSLOT(NSLOT), .NIN(NIN)) u_iomux (
      .clk (clk), .rst_n (rst_n),
      .sm_out (sm_out), .sm_oe (sm_oe), .sm_in (sm_in),
      .ui_in (ui_in), .uo_out (uo_out),
      .uio_in (uio_in), .uio_out (uio_out), .uio_oe (uio_oe),
      .sel_ld_en (sel_ld_en), .sel_ld_in (ld_in), .sel_ld_out (sel_ld_out)
  );

  // ---- keep observability logic alive (see the `obs` port comment) -------
  assign obs = ^{imem_ld_out, pal_ld_out, cfg_ld_out}
             ^ ^imem_ld_addr_flat ^ ^row_addr_flat
             ^ ^host_rx_rd_data ^ ^host_tx_level ^ ^host_rx_level
             ^ host_tx_full ^ host_rx_ne
             ^ ^tx_grant ^ ^rx_grant
             ^ ^crc_q
             ^ stuff_out ^ stuff_valid ^ stuff_in_ready ^ stuff_stuffed
             ^ sel_ld_out;

endmodule
`default_nettype wire
