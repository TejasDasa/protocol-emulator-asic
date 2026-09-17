// stt_iomux -- SPEC section 11.1. Maps NSM machines onto the Tiny Tapeout
// boundary, and holds the `run` flag.
//
// The output side is PIN-CENTRIC: each of the 16 output-capable pins carries a
// select field naming the ONE driver that drives it, where a driver is
// (machine * NSLOT + slot). Two machines therefore cannot contend for a pin --
// a pin does not choose two drivers, so the question cannot arise and no
// arbitration exists. Several pins may select the same driver; a driver no pin
// selects is simply unobserved.
//
// The input side is the same shape: each machine input selects one of the 16
// input-capable pins.
//
// `run` separates configuration from operation. While it is low the host owns
// ui_in[6:0] and uio_in[7:5]; once set, nothing is reserved and all 16 pins are
// available. It is cleared only by reset, so reprogramming means asserting
// rst_n. It is load-bearing, not a convenience: without it those pins stay
// consumed, leaving 13 output-capable pins for 15 drivers, and five machines
// with three slots would not fit on the boundary at all.
`default_nettype none
`include "stt_isa.vh"

module stt_iomux #(
    parameter NSM   = 5,
    parameter NSLOT = 3,
    parameter NIN   = 2,
    parameter NOUT  = 16,          // uo_out[8] + uio[8]
    parameter NPIN  = 16           // ui_in[8]  + uio[8]
) (
    input  wire                   clk,
    input  wire                   rst_n,

    // serial load of the pin assignment and the run flag
    input  wire                   sel_ld_en,
    input  wire                   sel_ld_in,
    output wire                   sel_ld_out,
    output wire                   run,

    // SPEC section 11.2 host byte port. Pin-selected, not reserved: with
    // host_en low nothing here consumes a pin and all 16 stay available.
    output wire                   host_en,
    output wire                   host_stb,
    output wire                   host_din,
    input  wire                   host_dout,

    // machine side
    input  wire [NSM*NSLOT-1:0]   sm_out,
    input  wire [NSM*NSLOT-1:0]   sm_oe,
    output wire [NSM*NIN-1:0]     sm_in,

    // Tiny Tapeout boundary
    input  wire [7:0]             ui_in,
    output wire [7:0]             uo_out,
    input  wire [7:0]             uio_in,
    output wire [7:0]             uio_out,
    output wire [7:0]             uio_oe
);

  localparam integer DRV   = NSM * NSLOT;
  localparam integer OSELW = (DRV  > 1) ? $clog2(DRV)  : 1;
  localparam integer ISELW = (NPIN > 1) ? $clog2(NPIN) : 1;
  localparam integer OBITS = NOUT * OSELW;
  localparam integer IBITS = NSM * NIN * ISELW;
  // Host port fields are APPENDED, so every existing select keeps its bit
  // position in the chain (SPEC section 11.2).
  localparam integer HBITS = 1 + 2 * ISELW;
  localparam integer NBITS = 1 + OBITS + IBITS + HBITS;
  // Output select code 15 is free: there are NSM*NSLOT = 15 drivers numbered
  // 0..14 in a 4-bit field, so the top code matches nothing today. A pin whose
  // select is HOST_CODE carries host_dout instead of a driver.
  localparam [OSELW-1:0] HOST_CODE = {OSELW{1'b1}};
  localparam integer HOST_CODE_FREE = (DRV <= HOST_CODE) ? 1 : 0;

  // One chain: `run` at bit 0, then the output selects, then the input selects.
  //
  // RUN IS BIT 0 AND THE HOST SENDS IT FIRST. New bits enter at the MSB and
  // shift down, so the first bit sent arrives at bit 0 on the LAST shift --
  // which is exactly when run should go high. Taking run from the MSB instead
  // looks equivalent and is not: the MSB holds whichever bit was just shifted
  // in, so run flickers with the data, and the first 1 in the chain gates off
  // sel_ld_en below and freezes the load permanently. That is not a thought
  // experiment; it is what the first run of rtl2/tb/test_chip.py did, sticking
  // at "pinsel bit 6".
  reg [NBITS-1:0] cfg;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)          cfg <= {NBITS{1'b0}};
    else if (sel_ld_en)  cfg <= {sel_ld_in, cfg[NBITS-1:1]};
  end
  assign sel_ld_out = cfg[0];
  assign run        = cfg[0];

  localparam integer O_RUN = 0;
  localparam integer O_OSEL = 1;
  localparam integer O_ISEL = O_OSEL + OBITS;
  localparam integer O_HEN  = O_ISEL + IBITS;
  localparam integer O_HSTB = O_HEN  + 1;
  localparam integer O_HDIN = O_HSTB + ISELW;

  // ---- inputs: every pin is readable, and ui_in/uio_in are the sources ----
  wire [NPIN-1:0] pin_val = {uio_in, ui_in};

  assign host_en  = cfg[O_HEN] & (HOST_CODE_FREE != 0);
  assign host_stb = host_en & pin_val[cfg[O_HSTB +: ISELW]];
  assign host_din = pin_val[cfg[O_HDIN +: ISELW]];

  genvar m, i, p;
  generate
    for (m = 0; m < NSM; m = m + 1) begin : g_min
      for (i = 0; i < NIN; i = i + 1) begin : g_in
        localparam integer K = (m * NIN + i);
        wire [ISELW-1:0] s = cfg[O_ISEL + K*ISELW +: ISELW];
        assign sm_in[K] = pin_val[s];
      end
    end
  endgenerate

  // ---- outputs: one driver per pin ---------------------------------------
  wire [NOUT-1:0] pin_d;
  wire [NOUT-1:0] pin_e;

  generate
    for (p = 0; p < NOUT; p = p + 1) begin : g_pin
      wire [OSELW-1:0] s = cfg[O_OSEL + p*OSELW +: OSELW];
      reg d, e;
      integer k;
      always @* begin
        d = 1'b0;
        e = 1'b0;
        for (k = 0; k < DRV; k = k + 1)
          if (s == k[OSELW-1:0]) begin
            d = sm_out[k];
            e = sm_oe[k];
          end
        // SPEC section 11.2: the free top code carries the host port out.
        if ((HOST_CODE_FREE != 0) && host_en && (s == HOST_CODE)) begin
          d = host_dout;
          e = 1'b1;
        end
      end
      assign pin_d[p] = d;
      assign pin_e[p] = e;
    end
  endgenerate

  // uo_out is output-only and always driven (SPEC section 11); uio carries its
  // driver's output enable.
  assign uo_out  = pin_d[7:0];
  assign uio_out = pin_d[15:8];
  assign uio_oe  = pin_e[15:8];

endmodule
`default_nettype wire
