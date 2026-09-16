// stt_hostbuf -- ONE TX and ONE RX byte FIFO shared by NSM state machines.
//
// This is the "share the buffering" arm of Ambiguity A6 (docs/area-study.md
// Appendix B). Sharing removes the per-SM FIFO cost but adds arbitration and
// N-wide data muxing, and that added logic grows with NSM -- which is exactly
// what the stt_chip sweep is measuring.
//
// Round-robin grant among the SMs asserting tx_pop / rx_push. One byte moves
// per cycle; a losing SM simply does not see its pop/push complete that cycle.
`default_nettype none

module stt_hostbuf #(
    parameter NSM        = 2,
    parameter SR_W       = 8,
    parameter FIFO_DEPTH = 8
) (
    input  wire                clk,
    input  wire                rst_n,

    // state-machine side
    input  wire [NSM-1:0]      tx_pop,        // per-SM request to pop a byte
    output wire [SR_W-1:0]     tx_data,       // broadcast: the head byte
    output wire [NSM-1:0]      tx_ne,         // per-SM "FIFO not empty" test
    input  wire [NSM-1:0]      rx_push,       // per-SM request to push
    input  wire [NSM*SR_W-1:0] rx_data_flat,  // per-SM push data

    // host side
    input  wire                host_tx_wr_en,
    input  wire [SR_W-1:0]     host_tx_wr_data,
    output wire                host_tx_full,
    input  wire                host_rx_rd_en,
    output wire [SR_W-1:0]     host_rx_rd_data,
    output wire                host_rx_ne,
    output wire [SR_W-1:0]     host_tx_level,
    output wire [SR_W-1:0]     host_rx_level,

    // observability: which SM won each arbiter this cycle
    output wire [NSM-1:0]      tx_grant,
    output wire [NSM-1:0]      rx_grant
);

  function integer clog2;
    input integer value;
    integer v;
    begin
      v = value - 1; clog2 = 0;
      while (v > 0) begin clog2 = clog2 + 1; v = v >> 1; end
    end
  endfunction

  localparam integer SELW = (NSM > 1) ? clog2(NSM) : 1;

  // ---- round-robin pointers ---------------------------------------------
  reg [SELW-1:0] tx_rr, rx_rr;

  // ---- grant: first requester at or after the round-robin pointer --------
  // Structural priority pick over a rotated request vector.
  reg [NSM-1:0] tx_g, rx_g;

  // Each combinational block owns its loop counter and its found flag.
  // Sharing them across always blocks makes them multiply driven.
  integer ti;
  reg     t_found;
  always @* begin
    tx_g    = {NSM{1'b0}};
    t_found = 1'b0;
    for (ti = 0; ti < NSM; ti = ti + 1) begin
      if (!t_found && tx_pop[(tx_rr + ti) % NSM]) begin
        tx_g[(tx_rr + ti) % NSM] = 1'b1;
        t_found = 1'b1;
      end
    end
  end

  integer ri;
  reg     r_found;
  always @* begin
    rx_g    = {NSM{1'b0}};
    r_found = 1'b0;
    for (ri = 0; ri < NSM; ri = ri + 1) begin
      if (!r_found && rx_push[(rx_rr + ri) % NSM]) begin
        rx_g[(rx_rr + ri) % NSM] = 1'b1;
        r_found = 1'b1;
      end
    end
  end

  assign tx_grant = tx_g;
  assign rx_grant = rx_g;

  // ---- winner's push data: N:1 mux --------------------------------------
  reg [SR_W-1:0] rx_sel;
  integer si;
  always @* begin
    rx_sel = {SR_W{1'b0}};
    for (si = 0; si < NSM; si = si + 1)
      if (rx_g[si]) rx_sel = rx_data_flat[si*SR_W +: SR_W];
  end

  wire tx_fifo_ne, rx_fifo_full;
  wire do_pop  = |tx_g;
  wire do_push = |rx_g;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      tx_rr <= {SELW{1'b0}};
      rx_rr <= {SELW{1'b0}};
    end else begin
      if (do_pop)  tx_rr <= (tx_rr == (NSM-1)) ? {SELW{1'b0}} : (tx_rr + 1'b1);
      if (do_push) rx_rr <= (rx_rr == (NSM-1)) ? {SELW{1'b0}} : (rx_rr + 1'b1);
    end
  end

  stt_fifo #(.W(SR_W), .DEPTH(FIFO_DEPTH)) u_tx (
      .clk (clk), .rst_n (rst_n),
      .wr_en (host_tx_wr_en), .wr_data (host_tx_wr_data),
      .rd_en (do_pop),        .rd_data (tx_data),
      .ne (tx_fifo_ne), .full (host_tx_full), .level_o (host_tx_level)
  );

  stt_fifo #(.W(SR_W), .DEPTH(FIFO_DEPTH)) u_rx (
      .clk (clk), .rst_n (rst_n),
      .wr_en (do_push), .wr_data (rx_sel),
      .rd_en (host_rx_rd_en), .rd_data (host_rx_rd_data),
      .ne (host_rx_ne), .full (rx_fifo_full), .level_o (host_rx_level)
  );

  // every SM sees the same not-empty condition
  assign tx_ne = {NSM{tx_fifo_ne}};

endmodule
`default_nettype wire
