// Direct evidence for the SPEC 16.1 gap that docs/formal.md P3 found:
// an sr_width outside 1..8 puts an undefined bit on a pin.
//
// The formal side proves only that the bit-select index is out of range.
// This shows what that costs: row 0x00030030 is `always / step / slot0 <- sr`,
// the shift register is read MSB-first, and with sr_width = 0 the MSB index is
// 15 on an 8-bit register. iverilog drives pin_out to x.
`timescale 1ns/1ps
`default_nettype none
module srwidth_demo;
  reg clk = 0, rst_n = 0, en = 0;
  reg [3:0] width = 4'd8;
  wire [4:0] row_addr;
  wire [2:0] pin_out, pin_oe;
  always #5 clk = ~clk;

  stt_core u (
    .clk(clk), .rst_n(rst_n), .en(en),
    .row_addr(row_addr), .row(32'h00030030),
    .cfg_period(16'd4), .cfg_shift_left(1'b1), .cfg_fill(2'd0),
    .cfg_sr_width(width),
    .cfg_cload_a(8'd0), .cfg_cload_b(8'd0), .cfg_cload_c(8'd0),
    .cfg_c2load(8'd0), .cfg_loadk(8'hA5),
    .cfg_init_pins(3'b000), .cfg_od_mask(3'b000),
    .cfg_crc16_poly(16'd0), .cfg_crc16_width(5'd16), .cfg_crc16_reflect(1'b0),
    .cfg_crc16_seed_ones(1'b0), .cfg_stuff_n(4'd0), .cfg_stuff_ones(1'b0),
    .cfg_stuff_slots(3'b000),
    .tx_data(8'd0), .tx_ne(1'b0), .tx_pop(), .rx_data(), .rx_push(),
    .pin_in(2'b00), .pin_out(pin_out), .pin_oe(pin_oe),
    .dbg_sr(), .dbg_cnt(), .dbg_c2(), .dbg_crc(), .dbg_tcount(),
    .dbg_link(), .dbg_pinv(), .dbg_crc16(), .dbg_stuff_run(),
    .dbg_stuff_last(), .dbg_stuff_valid()
  );

  task run_with(input [3:0] w, input [8*8-1:0] label);
    begin
      width = w; rst_n = 0; en = 0;
      repeat (2) @(posedge clk);
      rst_n = 1; @(posedge clk);
      en = 1;
      repeat (4) @(posedge clk);
      $display("  sr_width=%0d (%0s): pin_out = %b", w, label, pin_out);
    end
  endtask

  initial begin
    $display("SPEC 16.1 gap: sr_width has no stated range and nothing clamps it.");
    $display("Row 0x00030030 = always / step / slot0 <- sr, MSB-first.");
    run_with(4'd8, "in range");
    run_with(4'd1, "in range");
    run_with(4'd0, "NO RANGE");
    run_with(4'd9, "NO RANGE");
    run_with(4'd15, "NO RANGE");
    $finish;
  end
endmodule
`default_nettype wire
