// Bring-up simulation for stt_fpga_top: reset to a blinking LED, no host.
//
// FPGA bring-up only, not part of the ASIC submission.
//
// Runs the real loader against the real design with the real generated bit
// stream. Shortening the wall-clock time is done by overriding the PROGRAM's
// timer period and counter reload at generation time, not by changing the
// loader -- the load sequence itself runs at full length, all 1024 imem bits.
`timescale 1ns/1ps
`default_nettype none

module tb_fpga_blink;
  reg clk = 0;
  reg btn = 0;
  wire led;
  wire [7:0] uo_out;
  wire [7:0] uio;

  // 125 MHz board clock
  always #4 clk = ~clk;

  // DIV=2 keeps the simulation short; the loader and the design are unchanged.
  stt_fpga_top #(.DIV(2)) dut (
    .clk(clk), .btn_raw(btn), .led_status(led), .uo_out(uo_out), .uio(uio)
  );

  // Pmod JB left floating, as on the board.
  pullup (uio[0]); pullup (uio[1]); pullup (uio[2]); pullup (uio[3]);
  pullup (uio[4]); pullup (uio[5]); pullup (uio[6]); pullup (uio[7]);

  integer edges = 0;
  reg led_q = 1'bx;
  time   t_prev = 0, t_first = 0;
  time   gaps [0:7];
  integer gi = 0;

  always @(posedge dut.clk_sys) begin
    if (dut.ldr_done && led !== led_q) begin
      if (led_q !== 1'bx) begin
        if (edges > 0) begin gaps[gi] = $time - t_prev; gi = (gi + 1) % 8; end
        if (edges == 0) t_first = $time;
        t_prev = $time;
        edges  = edges + 1;
        $display("  %0t  LED -> %b   (edge %0d)", $time, led, edges);
      end
      led_q = led;
    end
  end

  integer i;
  initial begin
    $display("=== FPGA bring-up: reset -> load -> blink ===");
    #200;
    // Wait for the loader to finish, with a bound: an unbounded wait does not
    // fail, it hangs, and a hang says nothing about where it stuck.
    for (i = 0; i < 200000 && !dut.ldr_done; i = i + 1) @(posedge dut.clk_sys);
    if (!dut.ldr_done) begin
      $display("FAIL: loader never finished. state=%0d idx=%0d run=%b",
               dut.u_loader.state, dut.u_loader.idx, dut.u_stt.u_chip.run);
      $finish;
    end
    $display("  loader done at %0t, run=%b, machines_en=%b",
             $time, dut.u_stt.u_chip.run, dut.u_stt.u_chip.dbg_en);
    $display("  pin 0 output select = %0d (expect 1 = machine 0 slot 1)",
             dut.u_stt.u_chip.u_iomux.cfg[1 +: 2]);

    for (i = 0; i < 4000000 && edges < 5; i = i + 1) @(posedge dut.clk_sys);

    $display("");
    if (edges >= 5) begin
      $display("PASS: LED toggled %0d times", edges);
      $display("  interval between toggles: %0t", gaps[0]);
    end else begin
      $display("FAIL: LED toggled %0d times in the window (want >= 5)", edges);
      $display("  uo_out=%b run=%b en=%b row=%0d tcount=%0d cnt=%0d",
               uo_out, dut.u_stt.u_chip.run, dut.u_stt.u_chip.dbg_en,
               dut.u_stt.u_chip.dbg_row, dut.u_stt.u_chip.dbg_tcount,
               dut.u_stt.u_chip.dbg_cnt);
    end
    $finish;
  end
endmodule
`default_nettype wire
