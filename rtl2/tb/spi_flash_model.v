// A JEDEC-ID-only stand-in for a W25Q128JV, for simulation.
//
// FPGA bring-up only, not part of the ASIC submission.
//
// THIS MODEL IS OURS, so agreeing with it proves nothing about the real
// device -- that is the whole reason the flash test exists. It is here to
// catch plumbing errors (wrong pin, CS never asserted, MISO not released,
// bit order) before anything is wired up, not to validate the protocol.
//
// SPI mode 0 as the datasheet describes it (W25Q128JV-DTR, rev C, 2018-03-02,
// section 8.1.1 and the SPI mode description): DI is sampled on the RISING
// edge of CLK, DO changes on the FALLING edge. DO is left high-Z until a 9Fh
// command has been clocked in, which is what a real part on a pulled-up net
// looks like while the command is still going out.
`timescale 1ns/1ps
`default_nettype none

module spi_flash_model #(
    parameter [7:0] MF  = 8'hEF,      // Winbond
    parameter [7:0] MID = 8'h70,      // ID15-ID8
    parameter [7:0] CAP = 8'h18       // ID7-ID0, 128 Mbit
) (
    input  wire cs_n,
    input  wire clk,
    input  wire di,
    output wire dout
);
    reg [7:0]  shin;
    reg [2:0]  bitc;
    reg [2:0]  bytec;
    reg        armed;
    reg [7:0]  shout;
    reg        drive;

    assign dout = drive ? shout[7] : 1'bz;

    always @(negedge cs_n) begin
        bitc  <= 3'd0;
        bytec <= 3'd0;
        armed <= 1'b0;
        drive <= 1'b0;
    end

    always @(posedge clk) begin
        if (!cs_n) begin
            shin <= {shin[6:0], di};
            bitc <= bitc + 3'd1;
        end
    end

    always @(negedge clk) begin
        if (!cs_n) begin
            if (bitc == 3'd0) begin          // a byte just completed
                if (bytec == 3'd0) begin
                    armed <= (shin == 8'h9F);
                    if (shin == 8'h9F) begin
                        shout <= MF;
                        drive <= 1'b1;
                    end
                end else if (armed) begin
                    case (bytec)
                        3'd1:    shout <= MID;
                        3'd2:    shout <= CAP;
                        default: shout <= 8'h00;
                    endcase
                end
                bytec <= bytec + 3'd1;
            end else if (drive) begin
                shout <= {shout[6:0], 1'b0};
            end
        end
    end
endmodule

`default_nettype wire
