// stt_iomux -- maps NSM state machines onto the fixed Tiny Tapeout boundary.
//
// TT gives every project the same pins: ui_in[7:0] (in), uo_out[7:0] (out) and
// uio[7:0] (bidirectional). A multi-SM chip has NSM*NSLOT drivers competing for
// 16 drivable pins (uo_out + uio), so each output pin carries a small select
// register naming which SM drives it. That select logic is the part that grows
// with NSM and it is why the per-SM slope in the stt_chip sweep is larger than
// stt_core alone.
//
// Inputs are broadcast: every SM sees the same ui_in/uio_in bits, and picks the
// two it cares about via its own pin_in mapping.
`default_nettype none

module stt_iomux #(
    parameter NSM   = 2,
    parameter NSLOT = 3,
    parameter NIN   = 2,
    parameter NOUT  = 16          // uo_out[8] + uio[8]
) (
    input  wire                    clk,
    input  wire                    rst_n,

    // from the state machines
    input  wire [NSM*NSLOT-1:0]    sm_out,
    input  wire [NSM*NSLOT-1:0]    sm_oe,

    // to the state machines (broadcast)
    output wire [NSM*NIN-1:0]      sm_in,

    // Tiny Tapeout boundary
    input  wire [7:0]              ui_in,
    output wire [7:0]              uo_out,
    input  wire [7:0]              uio_in,
    output wire [7:0]              uio_out,
    output wire [7:0]              uio_oe,

    // serial load of the pin-assignment registers
    input  wire                    sel_ld_en,
    input  wire                    sel_ld_in,
    output wire                    sel_ld_out
);

  function integer clog2;
    input integer value;
    integer v;
    begin
      v = value - 1; clog2 = 0;
      while (v > 0) begin clog2 = clog2 + 1; v = v >> 1; end
    end
  endfunction

  localparam integer DRV  = NSM * NSLOT;          // total drivers competing
  localparam integer SELW = (DRV > 1) ? clog2(DRV) : 1;
  localparam integer NBITS = NOUT * SELW;

  // ---- one select field per drivable pin, loaded as a shift chain --------
  reg [NBITS-1:0] sel;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)          sel <= {NBITS{1'b0}};
    else if (sel_ld_en)  sel <= {sel_ld_in, sel[NBITS-1:1]};
  end
  assign sel_ld_out = sel[0];

  // ---- per-pin NSM*NSLOT : 1 mux on both data and output-enable ----------
  wire [NOUT-1:0] pin_d;
  wire [NOUT-1:0] pin_e;

  genvar p;
  generate
    for (p = 0; p < NOUT; p = p + 1) begin : g_pin
      wire [SELW-1:0] s = sel[p*SELW +: SELW];
      reg d, e;
      integer k;
      always @* begin
        d = 1'b0;
        e = 1'b0;
        for (k = 0; k < DRV; k = k + 1)
          if (s == k[SELW-1:0]) begin
            d = sm_out[k];
            e = sm_oe[k];
          end
      end
      assign pin_d[p] = d;
      assign pin_e[p] = e;
    end
  endgenerate

  assign uo_out  = pin_d[7:0];        // dedicated outputs, always driven
  assign uio_out = pin_d[15:8];
  assign uio_oe  = pin_e[15:8];

  // ---- broadcast the inputs ---------------------------------------------
  genvar m;
  generate
    for (m = 0; m < NSM; m = m + 1) begin : g_in
      // SM m takes ui_in[2m], ui_in[2m+1] where they exist, else wraps into
      // uio_in. Structurally this is a fixed tap, not a mux.
      assign sm_in[m*NIN +: NIN] =
          (m*NIN + NIN <= 8) ? ui_in[m*NIN +: NIN]
                             : uio_in[((m*NIN) % 8) +: NIN];
    end
  endgenerate

endmodule
`default_nettype wire
