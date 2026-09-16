// stt_core_fifo -- stt_core with the TX/RX byte buffering brought inside the
// state machine, for the A6 measurement.
//
// This is the "FIFOs replicate per SM" variant.  Comparing its flat area with
// core_flat gives the per-SM cost of in-core buffering; the difference is what
// moving the FIFOs to one shared host block would save per additional SM.
//
// Every submodule input is driven from a top-level port or another block.
`default_nettype none

module stt_core_fifo #(
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
    parameter FIFO_DEPTH = 4
) (
    input  wire               clk,
    input  wire               rst_n,
    input  wire               en,

    input  wire               imem_ld_en,
    input  wire               pal_ld_en,
    input  wire               cfg_ld_en,
    input  wire               ld_in,
    output wire               imem_ld_out,
    output wire               pal_ld_out,
    output wire               cfg_ld_out,
    output wire [ADDR_W-1:0]  imem_ld_addr,

    // host side of the in-core FIFOs
    input  wire               host_tx_wr_en,
    input  wire [SR_W-1:0]    host_tx_wr_data,
    output wire               host_tx_full,
    output wire [SR_W-1:0]    host_tx_level,

    input  wire               host_rx_rd_en,
    output wire [SR_W-1:0]    host_rx_rd_data,
    output wire               host_rx_ne,
    output wire [SR_W-1:0]    host_rx_level,

    input  wire [NIN-1:0]     pin_in,
    output wire [NSLOT-1:0]   pin_out,
    output wire [NSLOT-1:0]   pin_oe,

    output wire [ADDR_W-1:0]  row_addr
);

  // ---- core <-> FIFO interconnect --------------------------------------
  wire [SR_W-1:0] tx_data;
  wire            tx_ne;
  wire            tx_pop;
  wire [SR_W-1:0] rx_data;
  wire            rx_push;
  wire            tx_ne_unused_full;

  // ---- TX FIFO: host writes, the core pops on `load` -------------------
  stt_fifo #(.W(SR_W), .DEPTH(FIFO_DEPTH)) u_tx_fifo (
      .clk     (clk),
      .rst_n   (rst_n),
      .wr_en   (host_tx_wr_en),
      .wr_data (host_tx_wr_data),
      .rd_en   (tx_pop),
      .rd_data (tx_data),
      .ne      (tx_ne),
      .full    (host_tx_full),
      .level_o (host_tx_level)
  );

  // ---- RX FIFO: the core pushes on `push`, host reads ------------------
  stt_fifo #(.W(SR_W), .DEPTH(FIFO_DEPTH)) u_rx_fifo (
      .clk     (clk),
      .rst_n   (rst_n),
      .wr_en   (rx_push),
      .wr_data (rx_data),
      .rd_en   (host_rx_rd_en),
      .rd_data (host_rx_rd_data),
      .ne      (host_rx_ne),
      .full    (tx_ne_unused_full),
      .level_o (host_rx_level)
  );

  // ---- the state machine ------------------------------------------------
  stt_core #(
      .ROW_W(ROW_W), .ROWS(ROWS), .ADDR_W(ADDR_W), .ENTRY_W(ENTRY_W),
      .NFIXED(NFIXED), .NLOAD(NLOAD), .SR_W(SR_W), .CNT_W(CNT_W),
      .TIMER_W(TIMER_W), .NSLOT(NSLOT), .NIN(NIN)
  ) u_core (
      .clk          (clk),
      .rst_n        (rst_n),
      .en           (en),
      .imem_ld_en   (imem_ld_en),
      .pal_ld_en    (pal_ld_en),
      .cfg_ld_en    (cfg_ld_en),
      .ld_in        (ld_in),
      .imem_ld_out  (imem_ld_out),
      .pal_ld_out   (pal_ld_out),
      .cfg_ld_out   (cfg_ld_out),
      .imem_ld_addr (imem_ld_addr),
      .tx_data      (tx_data),
      .tx_ne        (tx_ne),
      .tx_pop       (tx_pop),
      .rx_data      (rx_data),
      .rx_push      (rx_push),
      .pin_in       (pin_in),
      .pin_out      (pin_out),
      .pin_oe       (pin_oe),
      .row_addr     (row_addr)
  );

endmodule
`default_nettype wire
