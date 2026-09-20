// stt_loader -- brings the chip up from reset with no host attached.
//
// FPGA BRING-UP INFRASTRUCTURE. Not part of the ASIC submission. On real
// silicon a host drives ui_in over the pins; this exists so a Zynq can do the
// same job with nothing connected, which is what makes an LED blink the proof
// that the loader, the imem write path, the machine and the pin path all work.
//
// Sequence, SPEC section 10 and section 11.1:
//
//   for each machine m:  sm_sel <- m
//                        shift the program   (ui_in[0]), all 32 rows
//                        shift the config    (ui_in[1])
//   shift the pin assignment (ui_in[2]); its LAST bit leaves `run` set
//
// The program and config chains are independent shift registers with separate
// enables, so their order relative to each other is free -- section 10 does not
// fix one, and the lockstep testbenches use the opposite order to this one.
// The pin assignment must come last: `run` is bit 0 of that chain and is sent
// first, so it only reaches its position once the whole chain has shifted, and
// setting it is what ends configuration.
//
// The two-cycle start delay is NOT duplicated here. stt_chip releases the pins
// on `run` and enables the machines two cycles later (section 11.1); the loader
// just stops.
//
// BUSY. Section 10 forbids presenting a bit while imem_ld_busy is high. This
// uses the flag COMBINATIONALLY in the cycle it decides what to drive, and
// never a registered copy of it. A registered copy is one cycle stale, which
// is the same off-by-one that made a cocotb testbench read busy as it stood
// BEFORE the clock edge: a busy that had just risen read as idle, the next bit
// went into a busy memory, and exactly one bit was lost at every 32-bit word
// boundary (docs/writeup.md section 4.3, entry 13). There is no combinational
// loop -- imem_ld_busy is a register output inside the design and does not
// depend on ui_in in the same cycle.
`default_nettype none

module stt_loader (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       busy,        // uo_out[0] carries imem_ld_busy while run=0
    output wire [7:0] ui_in,
    output wire [2:0] sm_sel,      // drives uio_in[7:5] during load
    output wire       done
);

    // Generated from the Python encoder by scripts/gen_fpga_rom.py. Never
    // hand-transcribed: the streams here are the same bits the benchmarks
    // encode, from the same SttProgram and PinPlan objects.
    `include "stt_rom.vh"

    localparam integer NM     = STT_ROM_NSM;
    localparam integer IMEM_N = STT_ROM_IMEM_N;
    localparam integer CFG_N  = STT_ROM_CFG_N;
    localparam integer SEL_N  = STT_ROM_SEL_N;

    // Wide enough for the longest stream.
    localparam integer CNT_W = (IMEM_N > CFG_N)
                             ? ((IMEM_N > SEL_N) ? $clog2(IMEM_N + 1) : $clog2(SEL_N + 1))
                             : ((CFG_N  > SEL_N) ? $clog2(CFG_N  + 1) : $clog2(SEL_N + 1));
    localparam integer MACH_W = (NM > 1) ? $clog2(NM) : 1;

    localparam [2:0] S_IMEM = 3'd0,
                     S_CFG  = 3'd1,
                     S_SEL  = 3'd2,
                     S_DONE = 3'd3;

    reg [2:0]         state;
    reg [CNT_W-1:0]   idx;
    reg [MACH_W-1:0]  mach;

    // Shift registers rather than a variable index into a 1024-bit constant:
    // the stream is presented least-significant bit first and never randomly
    // addressed, so shifting costs flops and no multiplexer.
    reg [IMEM_N-1:0] imem_sr;
    reg [CFG_N-1:0]  cfg_sr;
    reg [SEL_N-1:0]  sel_sr;

    // Per-machine slices of the generated streams. `cfg_of_mach` is the
    // machine being loaded now; `imem_of_next` is the one after it, because
    // the program reload happens on the same edge that advances `mach` and
    // would otherwise re-load the machine just finished.
    wire [MACH_W-1:0] mach_nxt = mach + 1'b1;
    reg [CFG_N-1:0]  cfg_of_mach;
    reg [IMEM_N-1:0] imem_of_next;
    integer k;
    always @* begin
        cfg_of_mach  = STT_ROM_CFG [0 +: CFG_N];
        imem_of_next = STT_ROM_IMEM[0 +: IMEM_N];
        for (k = 0; k < NM; k = k + 1) begin
            if (mach     == k[MACH_W-1:0]) cfg_of_mach  = STT_ROM_CFG [k * CFG_N  +: CFG_N ];
            if (mach_nxt == k[MACH_W-1:0]) imem_of_next = STT_ROM_IMEM[k * IMEM_N +: IMEM_N];
        end
    end

    // Stall only the program chain, and only on the cycle busy is actually
    // high. The config and pin chains have no busy handshake.
    wire stalled = (state == S_IMEM) && busy;
    wire running = (state != S_DONE) && !stalled;

    reg [CNT_W-1:0] len;
    always @* begin
        case (state)
            S_IMEM:  len = IMEM_N[CNT_W-1:0];
            S_CFG:   len = CFG_N[CNT_W-1:0];
            default: len = SEL_N[CNT_W-1:0];
        endcase
    end
    wire last = (idx == len - 1'b1);

    reg bit_out;
    always @* begin
        case (state)
            S_IMEM:  bit_out = imem_sr[0];
            S_CFG:   bit_out = cfg_sr[0];
            default: bit_out = sel_sr[0];
        endcase
    end

    // ui_in[0] program enable, [1] config, [2] pin assignment, [4] serial data
    // (SPEC section 11.1). Nothing is driven while stalled or done.
    assign ui_in = running ? {3'b0, bit_out, 1'b0,
                              (state == S_SEL), (state == S_CFG), (state == S_IMEM)}
                           : 8'h00;
    assign sm_sel = {{(3 - MACH_W){1'b0}}, mach};
    assign done   = (state == S_DONE);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state   <= S_IMEM;
            idx     <= {CNT_W{1'b0}};
            mach    <= {MACH_W{1'b0}};
            imem_sr <= STT_ROM_IMEM[0 +: IMEM_N];
            cfg_sr  <= STT_ROM_CFG [0 +: CFG_N];
            sel_sr  <= STT_ROM_SEL;
        end else if (running) begin
            case (state)
                S_IMEM: begin
                    imem_sr <= {1'b0, imem_sr[IMEM_N-1:1]};
                    if (last) begin
                        idx    <= {CNT_W{1'b0}};
                        cfg_sr <= cfg_of_mach;
                        state  <= S_CFG;
                    end else begin
                        idx <= idx + 1'b1;
                    end
                end
                S_CFG: begin
                    cfg_sr <= {1'b0, cfg_sr[CFG_N-1:1]};
                    if (last) begin
                        idx <= {CNT_W{1'b0}};
                        if (mach == NM[MACH_W-1:0] - 1'b1) begin
                            state <= S_SEL;
                        end else begin
                            mach    <= mach + 1'b1;
                            imem_sr <= imem_of_next;
                            state   <= S_IMEM;
                        end
                    end else begin
                        idx <= idx + 1'b1;
                    end
                end
                S_SEL: begin
                    sel_sr <= {1'b0, sel_sr[SEL_N-1:1]};
                    if (last) begin
                        idx   <= {CNT_W{1'b0}};
                        state <= S_DONE;
                    end else begin
                        idx <= idx + 1'b1;
                    end
                end
                default: ;
            endcase
        end
    end

endmodule

`default_nettype wire
