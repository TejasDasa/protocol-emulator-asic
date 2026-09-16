// Shared encoding constants for the STT protocol-emulator core.
// Every value here is traceable to rtl/ISA_NOTES.md, which is derived from
// isa_bench/. Verilog-2005 compatible (no packages, no enums).
`ifndef STT_PKG_VH
`define STT_PKG_VH

// ---- row field positions (ISA_NOTES §1) ----------------------------------
`define STT_TEST_LSB   0
`define STT_TEST_W     4
`define STT_MODE_LSB   4
`define STT_MODE_W     2
`define STT_TGT_LSB    6
`define STT_TGT_W      5
`define STT_SLOT_LSB  11
`define STT_SLOT_W     2
`define STT_POP_LSB   13
`define STT_POP_W      3
`define STT_ACT_LSB   16
`define STT_ACT_W      5

// ---- test codes (ISA_NOTES §2) -------------------------------------------
`define STT_T_ALWAYS 4'd0
`define STT_T_C2Z    4'd1
`define STT_T_CZ     4'd2
`define STT_T_FIFO   4'd3
`define STT_T_IN0H   4'd4
`define STT_T_IN0L   4'd5
`define STT_T_IN1H   4'd6
`define STT_T_IN1L   4'd7
`define STT_T_SRBIT  4'd8
`define STT_T_TMR    4'd9

// ---- branch modes (ISA_NOTES §3) -----------------------------------------
`define STT_M_WAIT   2'd0
`define STT_M_BRANCH 2'd1
`define STT_M_SKIP   2'd2
`define STT_M_STEP   2'd3
`define STT_RET      5'd31

// ---- pin ops (ISA_NOTES §4) ----------------------------------------------
`define STT_P_HOLD 3'd0
`define STT_P_LO   3'd1
`define STT_P_HI   3'd2
`define STT_P_SR   3'd3
`define STT_P_TGL  3'd4
`define STT_P_D0   3'd5
`define STT_P_D1   3'd6
`define STT_SLOT_PAIR 2'd3

// ---- palette entry groups (ISA_NOTES §5), entry = {xx,tm,c2,c1,sr} = 13b --
`define STT_G_SR_LSB  0
`define STT_G_SR_W    3
`define STT_G_C1_LSB  3
`define STT_G_C1_W    3
`define STT_G_C2_LSB  6
`define STT_G_C2_W    2
`define STT_G_TM_LSB  8
`define STT_G_TM_W    2
`define STT_G_XX_LSB 10
`define STT_G_XX_W    3

// group sr: -, load, loadk, loadcrc, clr, shift, clr+shift, push
`define STT_SR_NONE    3'd0
`define STT_SR_LOAD    3'd1
`define STT_SR_LOADK   3'd2
`define STT_SR_LOADCRC 3'd3
`define STT_SR_CLR     3'd4
`define STT_SR_SHIFT   3'd5
`define STT_SR_CLRSH   3'd6
`define STT_SR_PUSH    3'd7
// group c1: -, cload, cload_b, cload_c, cdec
`define STT_C1_NONE 3'd0
`define STT_C1_LDA  3'd1
`define STT_C1_LDB  3'd2
`define STT_C1_LDC  3'd3
`define STT_C1_DEC  3'd4
// group c2: -, c2load, c2dec
`define STT_C2_NONE 2'd0
`define STT_C2_LD   2'd1
`define STT_C2_DEC  2'd2
// group tm: -, trst, thalf
`define STT_TM_NONE 2'd0
`define STT_TM_RST  2'd1
`define STT_TM_HALF 2'd2
// group xx: -, crcrst, crcstep, call, crcrst+call
`define STT_XX_NONE   3'd0
`define STT_XX_CRCRST 3'd1
`define STT_XX_CRCSTP 3'd2
`define STT_XX_CALL   3'd3
`define STT_XX_RSTCALL 3'd4

`endif
