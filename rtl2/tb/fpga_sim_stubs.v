// Simulation stubs for the Xilinx IP stt_fpga_top instantiates.
//
// FPGA bring-up only, not part of the ASIC submission, and NOT used in
// synthesis -- Vivado binds the real Clocking Wizard there. This exists so the
// bring-up testbenches can run under Icarus without the Xilinx libraries.
//
// The divider below reproduces the RATIO the IP is configured for (125 MHz in,
// 15.625 MHz out). If the real IP is regenerated for a different output
// frequency, this ratio and the ROM both have to follow, which is why
// stt_fpga_top says to regenerate the ROM when the clock changes.
`timescale 1ns/1ps
`default_nettype none

module clk_wiz_0 #(
    parameter integer DIV = 8            // 125 MHz / 8 = 15.625 MHz
) (
    input  wire clk_in1,
    output wire clk_out1,
    output wire locked
);
    reg [15:0] cnt = 16'd0;
    reg        out = 1'b0;
    always @(posedge clk_in1) begin
        if (cnt == DIV[15:0] / 2 - 16'd1) begin
            cnt <= 16'd0;
            out <= ~out;
        end else begin
            cnt <= cnt + 16'd1;
        end
    end
    assign clk_out1 = out;

    // The real MMCM takes time to lock, and the design must not run before it
    // does. Holding locked low for a while exercises that path rather than
    // starting the loader at time zero.
    reg lk = 1'b0;
    initial begin
        #2000;
        lk = 1'b1;
    end
    assign locked = lk;
endmodule

module BUFG (input wire I, output wire O);
    assign O = I;
endmodule

`default_nettype wire
