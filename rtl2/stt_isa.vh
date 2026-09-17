// GENERATED from spec/isa.json by rtl2/gen_isa_vh.py -- do not edit.
// `make check` regenerates this and fails if it differs.
`ifndef STT_ISA_VH
`define STT_ISA_VH

`define STT_ROW_W   32
`define STT_ROWS    32
`define STT_ADDR_W  5
`define STT_RET     8'd255

// ---- row fields: [msb:lsb] ----
`define STT_F_TEST  3:0
`define STT_F_MODE  5:4
`define STT_F_TARGET  13:6
`define STT_F_PIN_SLOT  15:14
`define STT_F_PIN_OP  18:16
`define STT_F_ACT_SR  21:19
`define STT_F_ACT_C1  24:22
`define STT_F_ACT_C2  26:25
`define STT_F_ACT_TM  28:27
`define STT_F_ACT_XX  31:29

// ---- test codes ----
`define STT_T_ALWAYS  4'd0
`define STT_T_C2Z     4'd1
`define STT_T_CZ      4'd2
`define STT_T_FIFO    4'd3
`define STT_T_IN0H    4'd4
`define STT_T_IN0L    4'd5
`define STT_T_IN1H    4'd6
`define STT_T_IN1L    4'd7
`define STT_T_SRBIT   4'd8
`define STT_T_TMR     4'd9

// ---- branch modes ----
`define STT_M_WAIT    2'd0
`define STT_M_BRANCH  2'd1
`define STT_M_SKIP    2'd2
`define STT_M_STEP    2'd3

// ---- pin slots ----
`define STT_SLOT_SLOT0  2'd0
`define STT_SLOT_SLOT1  2'd1
`define STT_SLOT_SLOT2  2'd2
`define STT_SLOT_PAIR   2'd3

// ---- pin ops ----
`define STT_P_HOLD  3'd0
`define STT_P_LO    3'd1
`define STT_P_HI    3'd2
`define STT_P_SR    3'd3
`define STT_P_TGL   3'd4
`define STT_P_D0    3'd5
`define STT_P_D1    3'd6

// ---- action groups: one `define per (group, choice) ----
// group sr: 3 bits at row bit 0 of the action field
`define STT_AW_SR 3
`define STT_ASR_NONE         3'd0
`define STT_ASR_LOAD         3'd1
`define STT_ASR_LOADK        3'd2
`define STT_ASR_LOADCRC      3'd3
`define STT_ASR_CLR          3'd4
`define STT_ASR_SHIFT        3'd5
`define STT_ASR_CLR_SHIFT    3'd6
`define STT_ASR_PUSH         3'd7

// group c1: 3 bits at row bit 3 of the action field
`define STT_AW_C1 3
`define STT_AC1_NONE         3'd0
`define STT_AC1_CLOAD        3'd1
`define STT_AC1_CLOAD_B      3'd2
`define STT_AC1_CLOAD_C      3'd3
`define STT_AC1_CDEC         3'd4

// group c2: 2 bits at row bit 6 of the action field
`define STT_AW_C2 2
`define STT_AC2_NONE         2'd0
`define STT_AC2_C2LOAD       2'd1
`define STT_AC2_C2DEC        2'd2

// group tm: 2 bits at row bit 8 of the action field
`define STT_AW_TM 2
`define STT_ATM_NONE         2'd0
`define STT_ATM_TRST         2'd1
`define STT_ATM_THALF        2'd2

// group xx: 3 bits at row bit 10 of the action field
`define STT_AW_XX 3
`define STT_AXX_NONE         3'd0
`define STT_AXX_CRCRST       3'd1
`define STT_AXX_CRCSTEP      3'd2
`define STT_AXX_CALL         3'd3
`define STT_AXX_CRCRST_CALL  3'd4

`endif
