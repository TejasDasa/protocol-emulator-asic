// stt_hostport -- SPEC section 11.2. The host byte port, serialized.
//
// A byte reaches the host one bit per clock, because the boundary leaves no
// choice: there are 8 ui_in bits and section 11.1 already spends seven of them
// while `run` = 0. One transaction is 16 clocks of `stb`, MSB first, carrying
// traffic both ways:
//
//   in   [15:13] sel   [12] wr   [11:4] data   [3:0] pad
//   out  [15:12] 0     [11:4] rxdata        [3:0] {rx_ne, tx_full, rx_ovf, tx_unf}
//
// `sel` arrives first so that the chip knows which machine's RX FIFO to read
// before the data field has to go out; `status` goes out last, when everything
// it reports is known. The four leading output bits are 0 because `sel` has
// not arrived yet.
//
// Effects land on the sixteenth clock, never during the frame, so a frame the
// host abandons by dropping `stb` does nothing at all.
`default_nettype none

module stt_hostport #(
    parameter SR_W = 8,
    parameter NSM  = 5
) (
    input  wire               clk,
    input  wire               rst_n,

    // pins, after the iomux has selected them (SPEC section 11.2)
    input  wire               host_en,
    input  wire               stb,
    input  wire               din,
    output wire               dout,

    // stt_hostbuf
    output wire [2:0]         host_sel,
    output wire               host_tx_we,
    output wire [SR_W-1:0]    host_tx_data,
    input  wire               host_tx_full,
    output wire               host_rx_re,
    input  wire [SR_W-1:0]    host_rx_data,
    input  wire               host_rx_ne,
    input  wire [NSM-1:0]     rx_ovf,
    input  wire [NSM-1:0]     tx_unf
);

  reg  [3:0]  cnt;          // counts 15 down to 0 across one frame
  reg  [15:0] shin;
  reg  [2:0]  selr;
  reg         wrr;
  reg  [7:0]  rxcap;
  reg  [3:0]  statcap;

  wire active = host_en & stb;
  wire last   = active & (cnt == 4'd0);

  // The machine the frame names, valid from the cycle after its third bit.
  assign host_sel = selr;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      cnt     <= 4'd15;
      shin    <= 16'd0;
      selr    <= 3'd0;
      wrr     <= 1'b0;
      rxcap   <= 8'd0;
      statcap <= 4'd0;
    end else if (!active) begin
      // Dropping stb abandons the frame. Nothing has been committed, because
      // every effect is on the last clock.
      cnt <= 4'd15;
    end else begin
      shin <= {shin[14:0], din};
      // sel completes on this clock: two bits are already in shin, this is the
      // third. Registering it here makes host_sel valid for the next clock,
      // which is when the capture below needs it.
      if (cnt == 4'd13) selr <= {shin[1:0], din};
      if (cnt == 4'd12) begin
        wrr     <= din;
        rxcap   <= host_rx_data;
        statcap <= {host_rx_ne, host_tx_full, rx_ovf[selr], tx_unf[selr]};
      end
      cnt <= (cnt == 4'd0) ? 4'd15 : cnt - 1'b1;
    end
  end

  // Frame bit n of a 16-bit MSB-first stream sits at shin[n] once the frame is
  // complete, so on the last clock data is shin[10:3] with `din` arriving.
  assign host_tx_data = shin[10:3];
  assign host_tx_we   = last & wrr;

  // Pop only what the host actually saw: statcap[3] is rx_ne as it was when
  // rxcap was captured. Using the live flag would pop a byte the host never
  // received if a machine pushed mid-frame.
  assign host_rx_re   = last & statcap[3];

  assign dout = !host_en        ? 1'b0
              : (cnt >= 4'd12)  ? 1'b0
              : (cnt >= 4'd4)   ? rxcap[cnt - 4'd4]
                                : statcap[cnt[1:0]];

endmodule
`default_nettype wire
