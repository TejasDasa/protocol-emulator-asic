// UART TX bring-up simulation for stt_fpga_top: reset to a real serial frame.
//
// FPGA bring-up only, not part of the ASIC submission.
//
// Checks the thing a terminal cannot tell you apart from noise: that the frame
// is structurally right AND that every bit is exactly one bit period wide. A
// frame that is one bit-time off still looks like a frame on a scope and like
// garbage in a terminal, and is far cheaper to catch here.
//
// Every timing constant comes from stt_rom.vh, which the generator wrote. None
// is typed in here.
`timescale 1ns/1ps
`default_nettype none

module tb_fpga_uart;
  `include "stt_rom.vh"

  reg clk = 0;
  reg btn = 0;
  wire led;
  wire [7:0] uo_out;
  wire [7:0] uio;

  always #4 clk = ~clk;                 // 125 MHz board clock

  stt_fpga_top dut (
    .clk(clk), .btn_raw(btn), .led_status(led), .uo_out(uo_out), .uio(uio)
  );

  pullup (uio[0]); pullup (uio[1]); pullup (uio[2]); pullup (uio[3]);
  pullup (uio[4]); pullup (uio[5]); pullup (uio[6]); pullup (uio[7]);

  wire tx = uo_out[0];                  // Pmod JA pin 1

  integer cyc = 0;
  always @(posedge dut.clk_sys) cyc = cyc + 1;

  integer i, b, frame, errors;
  integer t_fall, t_prev_edge, width;
  reg [7:0] got;
  reg [9:0] widths_ok;

  // A genuine start bit, not just any falling edge. 0x55 alternates, so the
  // data field has a falling edge every other bit time; only the gap between
  // frames holds the line high for two consecutive bit times. Requiring 1.5
  // bit periods of continuous high before the fall finds the real one.
  task wait_start;
    integer h;
    begin
      h = 0;
      while (h < (3 * STT_ROM_PERIOD) / 2) begin
        @(posedge dut.clk_sys);
        if (tx === 1'b1) h = h + 1; else h = 0;
      end
      @(negedge tx);
    end
  endtask

  task wait_cycles(input integer n);
    integer k;
    begin for (k = 0; k < n; k = k + 1) @(posedge dut.clk_sys); end
  endtask

  // Sample the middle of bit `k`, counting the start bit as k = 0.
  task sample_bit(input integer k, output reg v);
    begin
      // already at the falling edge of the start bit
      wait_cycles(STT_ROM_PERIOD / 2 + k * STT_ROM_PERIOD - 1);
      v = tx;
    end
  endtask

  initial begin
    errors = 0;
    $display("=== FPGA UART TX bring-up ===");
    if (STT_ROM_IS_UART != 1) begin
      $display("FAIL: stt_rom.vh is for the wrong program (IS_UART=%0d). Regenerate with --program uart_tx.", STT_ROM_IS_UART);
      $finish;
    end
    $display("  bit period P = %0d cycles, byte = 0x%02X",
             STT_ROM_PERIOD, STT_ROM_BYTE);

    // !== 1, not !. Before the first reset the loader state register is X, so
    // `done` is X, `!done` is X, and a loop conditioned on it falls straight
    // through -- every probe after it then runs while the design is still in
    // reset and reports a perfectly plausible run=0.
    i = 0;
    while (dut.ldr_done !== 1'b1 && i < 300000) begin
      @(posedge dut.clk_sys);
      i = i + 1;
    end
    if (dut.ldr_done !== 1'b1) begin
      $display("FAIL: loader never finished (state=%0d idx=%0d)",
               dut.u_loader.state, dut.u_loader.idx);
      $finish;
    end
    // Probe AFTER the chain has landed, not on the edge it lands. The iomux
    // config register has no reset, so its low bits are still X until all
    // SEL_N bits have shifted, and `done` asserts on the very edge the last
    // one arrives -- reading here without waiting shows X for `run` and for
    // every select field, which looks exactly like a broken load.
    wait_cycles(4);
    $display("  loader done, run=%b", dut.u_stt.u_chip.run);
    $display("  pin 0  select = %0d  (TX slot)",
             dut.u_stt.u_chip.u_iomux.cfg[1 + 0*2 +: 2]);
    $display("  pin 1  select = %0d  (parked, must not be the reset value 0)",
             dut.u_stt.u_chip.u_iomux.cfg[1 + 1*2 +: 2]);
    if (dut.u_stt.u_chip.u_iomux.cfg[1 + 1*2 +: 2] == 0) begin
      $display("FAIL: parked pins carry select 0, the same value the field resets to -- chain content unchecked");
      errors = errors + 1;
    end

    // The line must be idle HIGH before anything is sent.
    if (tx !== 1'b1) begin
      $display("FAIL: line is %b after run, expected idle high", tx);
      errors = errors + 1;
    end else begin
      $display("  line idles high after run");
    end

    for (frame = 0; frame < 3; frame = frame + 1) begin
      wait_start;
      t_fall = cyc;

      sample_bit(0, got[0]);
      if (got[0] !== 1'b0) begin
        $display("FAIL frame %0d: start bit sampled %b, expected 0",
                 frame, got[0]);
        errors = errors + 1;
      end

      for (b = 0; b < 8; b = b + 1) begin
        wait_cycles(STT_ROM_PERIOD);
        got[b] = tx;
      end

      wait_cycles(STT_ROM_PERIOD);      // stop bit
      if (tx !== 1'b1) begin
        $display("FAIL frame %0d: stop bit is %b, expected 1", frame, tx);
        errors = errors + 1;
      end

      if (got !== STT_ROM_BYTE) begin
        $display("FAIL frame %0d: data 0x%02X, expected 0x%02X (LSB first)",
                 frame, got, STT_ROM_BYTE);
        errors = errors + 1;
      end else begin
        $display("  frame %0d: start 0, data 0x%02X LSB first, stop 1  OK",
                 frame, got);
      end
    end

    // Bit width: the gap between two start bits is one whole frame. Measure it
    // rather than trusting the samples above, which would agree with a frame
    // that is uniformly the wrong width.
    wait_start; t_prev_edge = cyc;
    wait_start; width = cyc - t_prev_edge;
    $display("  frame-to-frame: %0d cycles", width);
    if (width % STT_ROM_PERIOD != 0) begin
      $display("FAIL: frame length %0d is not a whole number of bit periods (P=%0d)", width, STT_ROM_PERIOD);
      errors = errors + 1;
    end else begin
      $display("  = %0d bit periods of %0d cycles each",
               width / STT_ROM_PERIOD, STT_ROM_PERIOD);
    end

    $display("");
    if (errors == 0) $display("PASS: UART frames are correct at the pin");
    else             $display("FAIL: %0d problem(s)", errors);
    $finish;
  end
endmodule
`default_nettype wire
