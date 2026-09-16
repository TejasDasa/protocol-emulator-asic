// stt_palette -- 32-entry action-set lookup.
//
// Split into two separately measurable submodules, as the area study requires:
//   stt_palette_fixed : entries 0..23, constants frozen at tapeout (no flops)
//   stt_palette_load  : entries 24..31, 8 x 13 = 104 flops + serial load chain
// stt_palette itself holds the 2:1 select between them and the group decode
// that turns a 13-bit entry into the individual action strobes.
//
// See rtl/ISA_NOTES.md section 5 and section 6.
`default_nettype none
`include "stt_pkg.vh"
`include "stt_palette_rom.vh"

// ---------------------------------------------------------------- fixed ROM
module stt_palette_fixed #(
    parameter ENTRY_W = 13
) (
    input  wire [4:0]          index,
    output reg  [ENTRY_W-1:0]  entry
);
  always @* begin
    case (index[4:0])
      5'd0 : entry = `STT_PAL_00;
      5'd1 : entry = `STT_PAL_01;
      5'd2 : entry = `STT_PAL_02;
      5'd3 : entry = `STT_PAL_03;
      5'd4 : entry = `STT_PAL_04;
      5'd5 : entry = `STT_PAL_05;
      5'd6 : entry = `STT_PAL_06;
      5'd7 : entry = `STT_PAL_07;
      5'd8 : entry = `STT_PAL_08;
      5'd9 : entry = `STT_PAL_09;
      5'd10: entry = `STT_PAL_10;
      5'd11: entry = `STT_PAL_11;
      5'd12: entry = `STT_PAL_12;
      5'd13: entry = `STT_PAL_13;
      5'd14: entry = `STT_PAL_14;
      5'd15: entry = `STT_PAL_15;
      5'd16: entry = `STT_PAL_16;
      5'd17: entry = `STT_PAL_17;
      5'd18: entry = `STT_PAL_18;
      5'd19: entry = `STT_PAL_19;
      5'd20: entry = `STT_PAL_20;
      5'd21: entry = `STT_PAL_21;
      5'd22: entry = `STT_PAL_22;
      5'd23: entry = `STT_PAL_23;
      default: entry = {ENTRY_W{1'b0}};
    endcase
  end
endmodule

// ------------------------------------------------- 8 loadable entries (104 ff)
module stt_palette_load #(
    parameter ENTRY_W = 13,
    parameter NLOAD   = 8
) (
    input  wire                clk,
    input  wire                rst_n,
    input  wire [2:0]          index,      // index[2:0] within the loadable bank
    input  wire                ld_en,      // serial shift enable
    input  wire                ld_in,      // serial data in
    output wire                ld_out,     // serial data out (chain continues)
    output wire [ENTRY_W-1:0]  entry
);
  // One flat shift chain across all NLOAD*ENTRY_W bits: the host clocks the
  // whole palette bank in, exactly like the imem load path.
  localparam integer NBITS = NLOAD * ENTRY_W;

  reg [NBITS-1:0] bank;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)      bank <= {NBITS{1'b0}};
    else if (ld_en)  bank <= {bank[NBITS-2:0], ld_in};
  end

  assign ld_out = bank[NBITS-1];

  // read mux: NLOAD:1 over ENTRY_W bits
  reg [ENTRY_W-1:0] sel;
  integer i;
  always @* begin
    sel = {ENTRY_W{1'b0}};
    for (i = 0; i < NLOAD; i = i + 1)
      if (index == i[2:0]) sel = bank[i*ENTRY_W +: ENTRY_W];
  end
  assign entry = sel;
endmodule

// ------------------------------------------------------------------- palette
module stt_palette #(
    parameter ENTRY_W   = 13,
    parameter NFIXED    = 24,
    parameter NLOAD     = 8,
    // EXT_FIXED=1 removes the 24-entry constant ROM from this instance and
    // takes the looked-up entry from fixed_entry_i instead, so one ROM can be
    // shared by several state machines. Default 0 keeps the original
    // self-contained behaviour, so every earlier measurement reproduces.
    parameter EXT_FIXED = 0,
    // INLINE_ENTRY=1 is the 32-bit-row format: the 13-bit action group comes
    // straight out of the row, so there is no palette at all -- no fixed ROM,
    // no loadable bank, no 2:1 select. Only the group decode survives.
    parameter INLINE_ENTRY = 0
) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire [4:0] index,
    input  wire [ENTRY_W-1:0] fixed_entry_i,   // used only when EXT_FIXED=1
    input  wire [ENTRY_W-1:0] inline_entry_i,  // used only when INLINE_ENTRY=1
    output wire [4:0]         index_o,         // index out to the shared ROM
    input  wire       ld_en,
    input  wire       ld_in,
    output wire       ld_out,

    output wire [ENTRY_W-1:0] entry,

    // decoded action strobes (unqualified by `fire`; stt_core gates them)
    output wire act_load,
    output wire act_loadk,
    output wire act_loadcrc,
    output wire act_clr,
    output wire act_shift,
    output wire act_push,
    output wire act_cload,
    output wire act_cload_b,
    output wire act_cload_c,
    output wire act_cdec,
    output wire act_c2load,
    output wire act_c2dec,
    output wire act_trst,
    output wire act_thalf,
    output wire act_crcrst,
    output wire act_crcstep,
    output wire act_call
);

  wire [ENTRY_W-1:0] e_fixed;
  wire [ENTRY_W-1:0] e_load;

  assign index_o = index;

  generate
    if (INLINE_ENTRY != 0) begin : g_no_fixed
      assign e_fixed = {ENTRY_W{1'b0}};
    end else if (EXT_FIXED != 0) begin : g_ext_fixed
      assign e_fixed = fixed_entry_i;
    end else begin : g_own_fixed
      stt_palette_fixed #(.ENTRY_W(ENTRY_W)) u_fixed (
          .index (index),
          .entry (e_fixed)
      );
    end
  endgenerate

  generate
    if (INLINE_ENTRY != 0) begin : g_no_load
      assign e_load = {ENTRY_W{1'b0}};
      assign ld_out = ld_in;          // chain passes through
    end else begin : g_have_load
      stt_palette_load #(.ENTRY_W(ENTRY_W), .NLOAD(NLOAD)) u_load (
          .clk    (clk),
          .rst_n  (rst_n),
          .index  (index[2:0]),
          .ld_en  (ld_en),
          .ld_in  (ld_in),
          .ld_out (ld_out),
          .entry  (e_load)
      );
    end
  endgenerate

  generate
    if (INLINE_ENTRY != 0) begin : g_inline
      assign entry = inline_entry_i;
    end else begin : g_lookup
      wire use_load = (index >= NFIXED[4:0]);
      assign entry = use_load ? e_load : e_fixed;
    end
  endgenerate

  // ---- group decode (ISA_NOTES section 5) ------------------------------
  wire [2:0] g_sr = entry[`STT_G_SR_LSB +: `STT_G_SR_W];
  wire [2:0] g_c1 = entry[`STT_G_C1_LSB +: `STT_G_C1_W];
  wire [1:0] g_c2 = entry[`STT_G_C2_LSB +: `STT_G_C2_W];
  wire [1:0] g_tm = entry[`STT_G_TM_LSB +: `STT_G_TM_W];
  wire [2:0] g_xx = entry[`STT_G_XX_LSB +: `STT_G_XX_W];

  assign act_load    = (g_sr == `STT_SR_LOAD);
  assign act_loadk   = (g_sr == `STT_SR_LOADK);
  assign act_loadcrc = (g_sr == `STT_SR_LOADCRC);
  assign act_clr     = (g_sr == `STT_SR_CLR) | (g_sr == `STT_SR_CLRSH);
  assign act_shift   = (g_sr == `STT_SR_SHIFT) | (g_sr == `STT_SR_CLRSH);
  assign act_push    = (g_sr == `STT_SR_PUSH);

  assign act_cload   = (g_c1 == `STT_C1_LDA);
  assign act_cload_b = (g_c1 == `STT_C1_LDB);
  assign act_cload_c = (g_c1 == `STT_C1_LDC);
  assign act_cdec    = (g_c1 == `STT_C1_DEC);

  assign act_c2load  = (g_c2 == `STT_C2_LD);
  assign act_c2dec   = (g_c2 == `STT_C2_DEC);

  assign act_trst    = (g_tm == `STT_TM_RST);
  assign act_thalf   = (g_tm == `STT_TM_HALF);

  assign act_crcrst  = (g_xx == `STT_XX_CRCRST) | (g_xx == `STT_XX_RSTCALL);
  assign act_crcstep = (g_xx == `STT_XX_CRCSTP);
  assign act_call    = (g_xx == `STT_XX_CALL)   | (g_xx == `STT_XX_RSTCALL);

endmodule
`default_nettype wire
