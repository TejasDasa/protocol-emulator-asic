// SPI flash JEDEC ID: machine 0 drives the bus, machine 1 prints the answer.
//
// FPGA bring-up only, not part of the ASIC submission.
//
// The flash here is spi_flash_model.v, which WE wrote, so passing proves
// nothing about a real W25Q128JV. It proves the plumbing: CS asserted, the
// right pins, MISO released, bit order, and the bytes reaching the UART.
`timescale 1ns/1ps
`default_nettype none

module tb_fpga_spi;
  `include "stt_rom.vh"

  reg clk = 0, btn = 0;
  wire led;
  wire [7:0] uo_out;
  wire [7:0] uio;

  always #4 clk = ~clk;

  stt_fpga_top dut (
    .clk(clk), .btn_raw(btn), .led_status(led), .uo_out(uo_out), .uio(uio)
  );

  // JA1 MOSI, JA2 SCK, JA3 CS, JA4 UART TX; JB1 MISO.
  wire mosi = uo_out[0];
  wire sck  = uo_out[1];
  wire cs_n = uo_out[2];
  wire utx  = uo_out[3];

  spi_flash_model u_flash (.cs_n(cs_n), .clk(sck), .di(mosi), .dout(uio[0]));
  pullup (uio[0]);                      // the breakout's net, and the chip released it
  pullup (uio[1]); pullup (uio[2]); pullup (uio[3]);
  pullup (uio[4]); pullup (uio[5]); pullup (uio[6]); pullup (uio[7]);

  wire       m0_push = dut.u_stt.u_chip.rx_push[0];
  wire [7:0] m0_data = dut.u_stt.u_chip.rx_data[0*8 +: 8];

  integer i, got_n = 0, errors = 0, uart_n = 0;
  reg [7:0] want [0:3];
  reg [7:0] uart_got [0:7];

  task automatic wait_cycles(input integer n);
    integer k;
    begin for (k = 0; k < n; k = k + 1) @(posedge dut.clk_sys); end
  endtask

  // What machine 0 clocked in off MISO.
  always @(posedge dut.clk_sys) begin
    if (dut.ldr_done && m0_push === 1'b1) begin
      if (got_n < 4) begin
        if (m0_data !== want[got_n]) begin
          $display("  FAIL byte %0d off MISO: 0x%02X, want 0x%02X",
                   got_n, m0_data, want[got_n]);
          errors = errors + 1;
        end else begin
          $display("  byte %0d off MISO: 0x%02X  OK", got_n, m0_data);
        end
      end
      got_n = got_n + 1;
    end
  end

  // Decode machine 1's UART line, so the check covers the path a terminal sees.
  integer b;
  reg [7:0] ub;
  initial begin
    wait (dut.ldr_done === 1'b1);
    forever begin
      @(negedge utx);
      wait_cycles(STT_ROM_UART_P / 2);
      if (utx === 1'b0) begin
        for (b = 0; b < 8; b = b + 1) begin
          wait_cycles(STT_ROM_UART_P);
          ub[b] = utx;
        end
        wait_cycles(STT_ROM_UART_P);
        if (uart_n < 8) uart_got[uart_n] = ub;
        $display("  UART out: 0x%02X (stop bit %b)", ub, utx);
        uart_n = uart_n + 1;
      end
    end
  end

  initial begin
    $display("=== SPI flash JEDEC ID ===");
    if (STT_ROM_HOST_RELAY != 1) begin
      $display("FAIL: ROM is not spi_flash. Regenerate: --program spi_flash --nsm 2");
      $finish;
    end
    for (i = 0; i < 4; i = i + 1) want[i] = STT_ROM_HOST_RSEQ[i*8 +: 8];
    $display("  SCK divisor from the ROM, UART bit period %0d cycles",
             STT_ROM_UART_P);
    $display("  expecting off MISO: 0x%02X 0x%02X 0x%02X 0x%02X",
             want[0], want[1], want[2], want[3]);

    i = 0;
    while (dut.ldr_done !== 1'b1 && i < 400000) begin
      @(posedge dut.clk_sys); i = i + 1;
    end
    if (dut.ldr_done !== 1'b1) begin $display("FAIL: loader never finished"); $finish; end
    wait_cycles(4);
    $display("  loader done, run=%b", dut.u_stt.u_chip.run);
    if (dut.u_stt.u_chip.uio_oe[0] !== 1'b0) begin
      $display("  FAIL: uio[0] is driven -- the chip would fight the flash");
      errors = errors + 1;
    end else $display("  uio[0] released, so the flash can drive MISO");
    if (cs_n !== 1'b1)
      $display("  NOTE: CS is %b just after run (should idle high)", cs_n);

    wait_cycles(300000);

    $display("");
    $display("  %0d bytes off MISO, %0d bytes out the UART, host good=%0d bad=%0d",
             got_n, uart_n, dut.hr_good, dut.hr_bad);
    // The UART must carry the SEQUENCE, not just something. A relay that
    // forwards only the first byte of each transaction still prints, and a
    // check for "at least one byte" cannot tell the two apart -- that is
    // exactly the bug this test missed once already.
    if (uart_n >= 4) begin
      for (i = 0; i < 4 && i < uart_n && i < 8; i = i + 1) begin
        if (uart_got[i] !== want[i]) begin
          $display("  FAIL UART byte %0d: 0x%02X, want 0x%02X",
                   i, uart_got[i], want[i]);
          errors = errors + 1;
        end
      end
      // The program loops, so the next four must repeat the same answer.
      for (i = 4; i < 8 && i < uart_n; i = i + 1) begin
        if (uart_got[i] !== want[i-4]) begin
          $display("  FAIL UART byte %0d: 0x%02X, want 0x%02X (second pass)",
                   i, uart_got[i], want[i-4]);
          errors = errors + 1;
        end
      end
      if (errors == 0)
        $display("  UART carried 0x%02X 0x%02X 0x%02X 0x%02X, in order",
                 uart_got[0], uart_got[1], uart_got[2], uart_got[3]);
    end

    if (got_n < 4) begin
      $display("FAIL: only %0d bytes clocked in off MISO", got_n);
    end else if (uart_n < 4) begin
      $display("FAIL: %0d byte(s) out the UART, want at least 4 -- the relay is dropping bytes", uart_n);
    end else if (errors == 0) begin
      $display("PASS: JEDEC ID read off the bus and printed. Model is ours -- this is plumbing, not protocol.");
    end else begin
      $display("FAIL: %0d problem(s)", errors);
    end
    $finish;
  end
endmodule
`default_nettype wire
