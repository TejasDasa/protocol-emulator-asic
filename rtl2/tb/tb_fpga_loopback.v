// UART TX -> UART RX loopback on two machines, in simulation.
//
// FPGA bring-up only, not part of the ASIC submission.
//
// First exercise of three things: the UART RX reference program, the SPEC 8.3
// two-cycle input synchronizer, and STT_NSM = 2 (the loader walking more than
// one machine, and the wider pin-assignment chain).
//
// What is checked is the byte machine 1 PUSHES, not the waveform on the wire.
// The RX program declares no output slots -- it reads in0 and pushes -- so the
// push is the only place the received value exists.
`timescale 1ns/1ps
`default_nettype none

module tb_fpga_loopback;
  `include "stt_rom.vh"

  parameter integer INTERNAL = 1;

  reg clk = 0;
  reg btn = 0;
  wire led;
  wire [7:0] uo_out;
  wire [7:0] uio;

  always #4 clk = ~clk;                       // 125 MHz board clock

  stt_fpga_top #(.LOOPBACK_INTERNAL(INTERNAL)) dut (
    .clk(clk), .btn_raw(btn), .led_status(led), .uo_out(uo_out), .uio(uio)
  );

  // Pmod JB floats, except that with INTERNAL=0 a jumper ties JB1 to JA1.
  // The chip must be releasing uio[0] for this not to be contention.
  generate
    if (INTERNAL == 0) assign uio[0] = uo_out[0];
  endgenerate
  pullup (uio[1]); pullup (uio[2]); pullup (uio[3]); pullup (uio[4]);
  pullup (uio[5]); pullup (uio[6]); pullup (uio[7]);

  // Machine 1's RX FIFO write port. rx_push is per machine; rx_data is the
  // shift register as it stood when the row fired.
  wire       m1_push = dut.u_stt.u_chip.rx_push[1];
  wire [7:0] m1_data = dut.u_stt.u_chip.rx_data[1*8 +: 8];

  integer got_n = 0, errors = 0, i;
  reg [7:0] first_bad = 8'h00;

  always @(posedge dut.clk_sys) begin
    if (dut.ldr_done && m1_push === 1'b1) begin
      got_n = got_n + 1;
      if (m1_data !== STT_ROM_BYTE) begin
        if (errors == 0) first_bad = m1_data;
        errors = errors + 1;
        $display("  FAIL byte %0d: machine 1 received 0x%02X, expected 0x%02X",
                 got_n, m1_data, STT_ROM_BYTE);
      end else begin
        $display("  byte %0d: machine 1 received 0x%02X  OK", got_n, m1_data);
      end
    end
  end

  task wait_cycles(input integer n);
    integer k;
    begin for (k = 0; k < n; k = k + 1) @(posedge dut.clk_sys); end
  endtask

  initial begin
    $display("=== UART loopback, %0s route ===",
             INTERNAL ? "INTERNAL" : "EXTERNAL jumper");
    if (STT_ROM_NSM != 2) begin
      $display("FAIL: ROM is for %0d machine(s). Regenerate: --program loopback --nsm 2",
               STT_ROM_NSM);
      $finish;
    end
    $display("  P = %0d cycles/bit, byte = 0x%02X", STT_ROM_PERIOD, STT_ROM_BYTE);

    i = 0;
    while (dut.ldr_done !== 1'b1 && i < 400000) begin
      @(posedge dut.clk_sys);
      i = i + 1;
    end
    if (dut.ldr_done !== 1'b1) begin
      $display("FAIL: loader never finished (state=%0d mach=%0d idx=%0d)",
               dut.u_loader.state, dut.u_loader.mach, dut.u_loader.idx);
      $finish;
    end
    wait_cycles(4);
    $display("  loader done after %0d cycles, run=%b, machines_en=%b",
             i, dut.u_stt.u_chip.run, dut.u_stt.u_chip.dbg_en);

    // The chip must be releasing the loop pin, or an external jumper fights it.
    if (dut.u_stt.u_chip.uio_oe[0] !== 1'b0) begin
      $display("FAIL: uio_oe[0] is %b -- the chip is driving the pin the loop arrives on",
               dut.u_stt.u_chip.uio_oe[0]);
      errors = errors + 1;
    end else begin
      $display("  uio[0] released (uio_oe[0]=0), so a jumper can drive it");
    end

    // Four bytes is 44 bit periods, plus the first frame the RX machine may
    // join late.
    wait_cycles(STT_ROM_PERIOD * 11 * 6);

    // The host port is the only path a pin can reach the received byte by,
    // and it has never run on hardware either. Check it agrees with the push.
    $display("");
    $display("  host port: good=%0d bad=%0d last=0x%02X valid=%b status=%b",
             dut.hr_good, dut.hr_bad, dut.hr_byte, dut.hr_valid, dut.hr_status);
    if (dut.hr_good == 0) begin
      $display("  FAIL: the host port read no matching byte out of machine 1");
      errors = errors + 1;
    end
    if (dut.hr_bad != 0) begin
      $display("  FAIL: the host port read %0d wrong byte(s)", dut.hr_bad);
      errors = errors + 1;
    end

    $display("");
    if (got_n == 0) begin
      $display("FAIL: machine 1 pushed nothing. tx pin now %b, m1 row %0d",
               uo_out[0], dut.u_stt.u_chip.dbg_row[1*5 +: 5]);
    end else if (errors == 0) begin
      $display("PASS: %0d bytes received, every one 0x%02X", got_n, STT_ROM_BYTE);
    end else begin
      $display("FAIL: %0d of %0d bytes wrong, first was 0x%02X",
               errors, got_n, first_bad);
      $display("      0x%02X reversed is 0x%02X, complemented is 0x%02X",
               STT_ROM_BYTE, 8'h00, ~STT_ROM_BYTE);
    end
    $finish;
  end
endmodule
`default_nettype wire
