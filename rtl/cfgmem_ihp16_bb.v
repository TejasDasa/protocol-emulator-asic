// Blackbox stub for the DFFRAM.librelane CFGMEM_IHP16 latch-array macro,
// as built for sg13cmos5l by kdp1965/ihp-um-janestreet-prism (macros/).
//
// Port list taken verbatim from macros/CFGMEM_IHP16/CFGMEM_IHP16.nl.v.
// 16 words x 32 bits = 512 bits. WROW is a ONE-HOT write row select, so the
// write-row decode lives outside the macro -- that glue is charged to the
// CFGMEM side in docs/area-study.md, which is the correction to the earlier
// "whole module vs bare macro" comparison.
//
// Declared blackbox so `stat` reports only the surrounding glue; the macro's
// own area is added separately on a stated basis (cell area 21,525.44 um2 from
// its netlist, or 28,794.50 um2 LEF placed footprint).
`default_nettype none

(* blackbox *)
module CFGMEM_IHP16 (
    input  wire        BYP,
    input  wire        EN0,
    input  wire        WE0,
    input  wire [3:0]  A0,
    input  wire [31:0] Di0,
    output wire [31:0] Do0,
    input  wire [15:0] WROW
);
endmodule
`default_nettype wire
