// USB LS loopback on hardware's terms: token TX on machine 0, token RX on
// machine 1, through the pins, with the host port feeding and draining both.
//
// FPGA bring-up only, not part of the ASIC submission.
//
// Checks three things nothing else has: the PAIR SLOT (one row writing two
// pins at once), NRZI, and the SPEC 8.3 synchronizer under a protocol that
// depends on it -- the receiver's decoded bit goes out on a pin and comes back
// through that synchronizer before `shift` can take it.
`timescale 1ns/1ps
`default_nettype none

module tb_fpga_usb;
  `include "stt_rom.vh"

  parameter integer INTERNAL = 1;

  reg clk = 0, btn = 0;
  wire led;
  wire [7:0] uo_out;
  wire [7:0] uio;

  always #4 clk = ~clk;

  stt_fpga_top #(.LOOPBACK_INTERNAL(INTERNAL)) dut (
    .clk(clk), .btn_raw(btn), .led_status(led), .uo_out(uo_out), .uio(uio)
  );

  // With the external route a jumper carries D+ from JA1 to JB1. The chip must
  // be releasing JB1 or it would fight the jumper.
  generate
    if (INTERNAL == 0) assign uio[0] = uo_out[0];
  endgenerate
  pullup (uio[2]); pullup (uio[3]); pullup (uio[4]);
  pullup (uio[5]); pullup (uio[6]); pullup (uio[7]);

  wire dp = uo_out[0];
  wire dm = uo_out[1];

  // Machine 1's RX FIFO write port: the only place a received byte exists.
  wire       m1_push = dut.u_stt.u_chip.rx_push[1];
  wire [7:0] m1_data = dut.u_stt.u_chip.rx_data[1*8 +: 8];

  integer got_n = 0, errors = 0, i, pair_moves = 0, se0 = 0;
  reg [7:0] want [0:3];

  // The pair must move TOGETHER. A pair-slot bug that drove only one half
  // would still make plausible single-ended traffic, so this watches for D+
  // and D- being equal outside the SE0 the transmitter emits deliberately.
  always @(posedge dut.clk_sys) begin
    if (dut.ldr_done && dp === dm) begin
      if (dp === 1'b0) se0 = se0 + 1;      // SE0, the end-of-packet marker
      else begin
        errors = errors + 1;
        if (errors < 4)
          $display("  FAIL: D+ and D- both high -- not a differential state");
      end
    end
    if (dut.ldr_done && m1_push === 1'b1) begin
      if (m1_data !== want[got_n % 4]) begin
        if (errors < 8)
          $display("  FAIL byte %0d: got 0x%02X want 0x%02X",
                   got_n, m1_data, want[got_n % 4]);
        errors = errors + 1;
      end else if (got_n < 8) begin
        $display("  byte %0d: 0x%02X  OK", got_n, m1_data);
      end
      got_n = got_n + 1;
    end
  end

  task wait_cycles(input integer n);
    integer k;
    begin for (k = 0; k < n; k = k + 1) @(posedge dut.clk_sys); end
  endtask

  initial begin
    $display("=== USB LS loopback, %0s route ===",
             INTERNAL ? "INTERNAL" : "EXTERNAL jumper");
    if (STT_ROM_IS_USB != 1) begin
      $display("FAIL: ROM is not the usb_loopback one. Regenerate with --program usb_loopback --nsm 2");
      $finish;
    end
    for (i = 0; i < 4; i = i + 1) want[i] = STT_ROM_HOST_RSEQ[i*8 +: 8];
    $display("  P = %0d cycles/bit, expecting 0x%02X 0x%02X 0x%02X 0x%02X",
             STT_ROM_PERIOD, want[0], want[1], want[2], want[3]);

    i = 0;
    while (dut.ldr_done !== 1'b1 && i < 400000) begin
      @(posedge dut.clk_sys); i = i + 1;
    end
    if (dut.ldr_done !== 1'b1) begin
      $display("FAIL: loader never finished");
      $finish;
    end
    wait_cycles(4);
    $display("  loader done, run=%b, machines_en=%b",
             dut.u_stt.u_chip.run, dut.u_stt.u_chip.dbg_en);
    if (dut.u_stt.u_chip.uio_oe[0] !== 1'b0) begin
      $display("  FAIL: uio[0] is driven -- a jumper would fight the chip");
      errors = errors + 1;
    end else $display("  uio[0] released, so the external route can drive it");
    if (dut.u_stt.u_chip.uio_oe[1] !== 1'b1) begin
      $display("  FAIL: uio[1] is not driven -- the decoded-bit loopback needs it");
      errors = errors + 1;
    end else $display("  uio[1] driven and read back: the self-loopback works");

    wait_cycles(STT_ROM_PERIOD * 40 * 12);

    $display("");
    $display("  bytes received %0d, SE0 cycles seen %0d", got_n, se0);
    $display("  host port: good=%0d bad=%0d last=0x%02X",
             dut.hr_good, dut.hr_bad, dut.hr_byte);
    if (got_n < 8) begin
      $display("FAIL: only %0d bytes received", got_n);
    end else if (se0 == 0) begin
      $display("FAIL: never saw SE0, so the pair is not being driven together");
    end else if (dut.hr_good == 0) begin
      $display("FAIL: the host port read nothing matching out of machine 1");
    end else if (errors == 0) begin
      $display("PASS: %0d bytes, all correct; pair moves together; host port agrees",
               got_n);
    end else begin
      $display("FAIL: %0d problem(s)", errors);
    end
    $finish;
  end
endmodule
`default_nettype wire
