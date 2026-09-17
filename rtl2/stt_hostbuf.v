// stt_hostbuf -- one TX and one RX byte FIFO PER MACHINE.
//
// Per machine, not shared, and that is a correctness decision rather than a
// preference. The authoritative models give every SttCore its own World with its
// own tx_fifo and rx_fifo. A shared buffer with round-robin arbitration -- which
// is what rtl/stt_hostbuf.v does, and what docs/area-study.md priced -- means a
// machine's `push` silently fails to complete on a cycle it loses the arbiter,
// and SPEC section 8.1 forbids stalling to retry. The byte is lost, timing
// dependently, and cycle-exact lockstep against a per-machine model could not
// hold. The whole rtl2 verification strategy rests on that lockstep.
//
// The cost is real: at DEPTH 4 this is 5 x 2 x 4 x 8 = 320 storage flops plus
// pointers, against roughly 100 for a shared buffer. It buys determinism.
//
// The host side is brought out as ports. Giving the host actual PINS needs the
// iomux to reserve some, which output select code 15 is free to express (there
// are 15 drivers, 0..14) -- that is the next step, not this one.
`default_nettype none

module stt_hostbuf #(
    parameter NSM   = 5,
    parameter SR_W  = 8,
    parameter DEPTH = 4
) (
    input  wire                clk,
    input  wire                rst_n,

    // machine side
    output wire [NSM*SR_W-1:0] tx_data,     // head byte, per machine
    output wire [NSM-1:0]      tx_ne,       // the `fifo` test
    input  wire [NSM-1:0]      tx_pop,
    input  wire [NSM*SR_W-1:0] rx_data,
    input  wire [NSM-1:0]      rx_push,

    // host side, one machine selected at a time
    input  wire [2:0]          host_sel,
    input  wire                host_tx_we,
    input  wire [SR_W-1:0]     host_tx_data,
    output wire                host_tx_full,
    input  wire                host_rx_re,
    output wire [SR_W-1:0]     host_rx_data,
    output wire                host_rx_ne,

    // sticky loss flags, per machine: a dropped push or a pop from empty
    output wire [NSM-1:0]      rx_ovf,
    output wire [NSM-1:0]      tx_unf
);

  wire [NSM-1:0] tx_full, tx_empty, rx_full, rx_empty;
  wire [NSM-1:0] tx_ovf_unused, rx_unf_unused;
  wire [NSM*SR_W-1:0] rx_out;

  genvar g;
  generate
    for (g = 0; g < NSM; g = g + 1) begin : g_sm
      wire sel_g = (host_sel == g[2:0]);

      // host -> machine
      stt_fifo #(.WIDTH(SR_W), .DEPTH(DEPTH)) u_tx (
          .clk(clk), .rst_n(rst_n),
          .wr_en(host_tx_we & sel_g), .wr_data(host_tx_data),
          .rd_en(tx_pop[g]), .rd_data(tx_data[g*SR_W +: SR_W]),
          .empty(tx_empty[g]), .full(tx_full[g]),
          .ovf(tx_ovf_unused[g]), .unf(tx_unf[g])
      );

      // machine -> host
      stt_fifo #(.WIDTH(SR_W), .DEPTH(DEPTH)) u_rx (
          .clk(clk), .rst_n(rst_n),
          .wr_en(rx_push[g]), .wr_data(rx_data[g*SR_W +: SR_W]),
          .rd_en(host_rx_re & sel_g), .rd_data(rx_out[g*SR_W +: SR_W]),
          .empty(rx_empty[g]), .full(rx_full[g]),
          .ovf(rx_ovf[g]), .unf(rx_unf_unused[g])
      );

      assign tx_ne[g] = ~tx_empty[g];
    end
  endgenerate

  assign host_tx_full = tx_full[host_sel];
  assign host_rx_ne   = ~rx_empty[host_sel];
  assign host_rx_data = rx_out[host_sel*SR_W +: SR_W];

endmodule
`default_nettype wire
