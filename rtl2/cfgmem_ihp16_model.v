// CFGMEM_IHP16 -- simulation model of the DFFRAM macro.
//
// Semantics taken from the reference implementation in prism
// (src/user_peripherals/cfgmem/cfgmem.v) and confirmed against the real DFFRAM
// netlist, where SLICE[i].STORAGE has .D(Di0_in[i]) and .Q(Di0_in[i+1]) -- a
// chain, not an array:
//
//     le = WROW & {16{WE0}}
//     row 0 takes Di0; row i takes row i-1
//
// SO ONLY ROW 0 CAN BE WRITTEN DIRECTLY. Loading 16 words means asserting all
// 16 WROW bits and strobing once per word, shifting the chain down. The words
// end up in REVERSE order, which is why stt_imem_cfgmem.v reads with A0
// inverted.
//
// WHY A MODEL AND NOT THE REAL NETLIST. The netlist simulates, but the storage
// is transparent latches: with all 16 enables high and zero gate delay, a value
// on Di0 ripples through the whole chain in one strobe instead of advancing one
// stage. The real macro relies on latch delay to stop the ripple, so the
// netlist is only meaningful with back-annotated timing. prism ships this same
// split -- a behavioural model for simulation, the macro for hardening -- and
// for the same reason. Synthesis still uses the real macro; see rtl2/synth.ys.
`default_nettype none

module CFGMEM_IHP16 (
    input  wire        WE0,
    input  wire [15:0] WROW,
    input  wire        EN0,
    input  wire        BYP,
    input  wire [3:0]  A0,
    input  wire [31:0] Di0,
    output wire [31:0] Do0
);

  reg [31:0] cfgmem [0:15];
  wire [15:0] le = WROW & {16{WE0}};

  integer i;
  always @* begin
    if (le[0]) cfgmem[0] <= Di0;
    for (i = 1; i < 16; i = i + 1)
      if (le[i]) cfgmem[i] <= cfgmem[i-1];
  end

  wire [31:0] do_int = EN0 ? cfgmem[A0] : 32'h0;
  assign Do0 = BYP ? Di0 : do_int;

endmodule
`default_nettype wire
