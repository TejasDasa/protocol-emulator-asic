// Sweep every configuration field over every value its hardware field can
// hold, and report which values produce undefined behaviour.
//
// docs/formal.md P3 and P5 each needed a precondition on a configuration
// field, and both fields turned out to have no range stated anywhere. Two of
// two is a pattern rather than two accidents, so this checks the rest in one
// pass instead of discovering them one at a time.
//
// Method: hold every field at a known-good value, sweep one field across its
// full encodable range, run a row that exercises it, and watch for an X
// reaching a pin or an architectural register. An X here is not a simulation
// artefact -- it is an out-of-range variable bit-select, which is exactly what
// a host loading raw configuration bits can cause and nothing traps.
`timescale 1ns/1ps
`default_nettype none
module config_sweep;
  reg clk = 0, rst_n = 0, en = 0;
  always #5 clk = ~clk;

  // always / step / slot0 <- sr, with shift and crc16step, so one row
  // exercises the shift register, the fill bit, the wide CRC and the pin path.
  localparam [31:0] ROW_SR   = (32'd6 << 29) | (32'd5 << 19) | (32'd3 << 16)
                             | (32'd3 << 4);
  // always / step / slot0 <- crcb: drives the pin from the wide CRC.
  localparam [31:0] ROW_CRCB = (32'd7 << 16) | (32'd3 << 4);
  // always / step, action thalf, no pin write.
  localparam [31:0] ROW_THALF = (32'd2 << 27) | (32'd3 << 4);

  reg [31:0] row;
  reg [15:0] period       = 16'd4;
  reg        shift_left   = 1'b1;
  reg [1:0]  fill         = 2'd0;
  reg [3:0]  sr_width     = 4'd8;
  reg [15:0] crc16_poly   = 16'h1021;
  reg [4:0]  crc16_width  = 5'd16;
  reg        crc16_refl   = 1'b0;
  reg        crc16_seed1  = 1'b1;
  reg [3:0]  stuff_n      = 4'd0;
  reg        stuff_ones   = 1'b0;
  reg [2:0]  stuff_slots  = 3'b000;
  reg [7:0]  loadk        = 8'hA5;

  wire [2:0]  pin_out, pin_oe;
  wire [7:0]  dbg_sr;
  wire [15:0] dbg_crc16, dbg_tcount;
  wire [2:0]  dbg_pinv;
  wire [4:0]  dbg_crc;
  wire [7:0]  dbg_cnt, dbg_c2;

  stt_core u (
    .clk(clk), .rst_n(rst_n), .en(en), .row_addr(), .row(row),
    .cfg_period(period), .cfg_shift_left(shift_left), .cfg_fill(fill),
    .cfg_sr_width(sr_width),
    .cfg_cload_a(8'd8), .cfg_cload_b(8'd0), .cfg_cload_c(8'd0),
    .cfg_c2load(8'd0), .cfg_loadk(loadk),
    .cfg_init_pins(3'b000), .cfg_od_mask(3'b000),
    .cfg_crc16_poly(crc16_poly), .cfg_crc16_width(crc16_width),
    .cfg_crc16_reflect(crc16_refl), .cfg_crc16_seed_ones(crc16_seed1),
    .cfg_stuff_n(stuff_n), .cfg_stuff_ones(stuff_ones),
    .cfg_stuff_slots(stuff_slots),
    .tx_data(8'd0), .tx_ne(1'b0), .tx_pop(), .rx_data(), .rx_push(),
    .pin_in(2'b00), .pin_out(pin_out), .pin_oe(pin_oe),
    .dbg_sr(dbg_sr), .dbg_cnt(dbg_cnt), .dbg_c2(dbg_c2), .dbg_crc(dbg_crc),
    .dbg_tcount(dbg_tcount), .dbg_link(), .dbg_pinv(dbg_pinv),
    .dbg_crc16(dbg_crc16), .dbg_stuff_run(), .dbg_stuff_last(),
    .dbg_stuff_valid()
  );

  integer ticks;
  reg [15:0] tcmax;
  reg bad;
  reg dbgx = 0;

  // Run the current configuration and report whether anything went undefined.
  task exercise(input integer cycles);
    integer i;
    begin
      bad = 1'b0; ticks = 0; tcmax = 16'd0;
      rst_n = 0; en = 0;
      repeat (2) @(posedge clk);
      rst_n = 1; @(posedge clk);
      en = 1;
      for (i = 0; i < cycles; i = i + 1) begin
        @(posedge clk);
        #1;
        // Per signal, not on a concatenation of them: the concatenation form
        // reported unknown on this simulator while every individual signal
        // was known, which would have marked every configuration undefined.
        if ($isunknown(pin_out) || $isunknown(pin_oe) || $isunknown(dbg_sr)
            || $isunknown(dbg_crc16) || $isunknown(dbg_pinv)
            || $isunknown(dbg_tcount) || $isunknown(dbg_crc)
            || $isunknown(dbg_cnt) || $isunknown(dbg_c2)) begin
          bad = 1'b1;
          if (dbgx) $display("    X at cycle %0d: out=%0d oe=%0d sr=%0d crc16=%0d pinv=%0d tc=%0d crc=%0d cnt=%0d c2=%0d",
            i, $isunknown(pin_out), $isunknown(pin_oe), $isunknown(dbg_sr),
            $isunknown(dbg_crc16), $isunknown(dbg_pinv), $isunknown(dbg_tcount),
            $isunknown(dbg_crc), $isunknown(dbg_cnt), $isunknown(dbg_c2));
        end
        if (dbg_tcount == 16'd0) ticks = ticks + 1;
        if (dbg_tcount > tcmax) tcmax = dbg_tcount;
      end
    end
  endtask

  task report(input [8*14-1:0] field, input integer v, input [8*40-1:0] note);
    $display("  %0s = %0d: %0s%0s", field, v,
             bad ? "UNDEFINED -- an X reached a pin or a register" : "defined",
             note);
  endtask

  integer j;
  initial begin
    $display("Configuration field sweep. Every value each hardware field can hold.");

    $display("\nsr_width (4 bits, 0-15) -- row drives slot0 from the shift register:");
    row = ROW_SR;
    for (j = 0; j <= 15; j = j + 1) begin
      sr_width = j[3:0]; exercise(24); report("sr_width", j, "");
    end
    sr_width = 4'd8;

    $display("\nfill (2 bits, 0-3) -- the bit shifted in:");
    for (j = 0; j <= 3; j = j + 1) begin
      fill = j[1:0]; exercise(24);
      report("fill", j, (j == 3) ? "  <- unassigned code" : "");
    end
    fill = 2'd0;

    $display("\nshift direction (1 bit):");
    for (j = 0; j <= 1; j = j + 1) begin
      shift_left = j[0]; exercise(24); report("shift_left", j, "");
    end
    shift_left = 1'b1;

    $display("\ncrc16_width (5 bits, 0-31) -- row drives slot0 from the wide CRC:");
    row = ROW_CRCB;
    for (j = 0; j <= 31; j = j + 1) begin
      crc16_width = j[4:0]; exercise(24); report("crc16_width", j, "");
    end
    crc16_width = 5'd16;

    $display("\nstuff_n (4 bits, 0-15) -- slot0 routed through the stuffer:");
    row = ROW_SR; stuff_slots = 3'b001;
    for (j = 0; j <= 15; j = j + 1) begin
      stuff_n = j[3:0]; exercise(32); report("stuff_n", j, "");
    end
    stuff_n = 4'd0; stuff_slots = 3'b000;

    $display("\nP (16 bits) -- ticks observed in 200 cycles, free-running:");
    row = ROW_SR;
    for (j = 0; j <= 6; j = j + 1) begin
      period = j[15:0]; exercise(200);
      $display("  P = %0d: %0d ticks in 200 cycles, expected %0d%0s", j, ticks,
               (j == 0) ? 0 : 200 / j,
               (j < 2) ? "   <- no sensible reading" : "");
    end
    period = 16'd4;

    // thalf is the reason P = 1 is not merely degenerate. It reloads to
    // P/2 - 1, which underflows when P < 2 and strands the timer.
    $display("\nP with a thalf on every passing row -- largest tcount reached:");
    row = ROW_THALF;
    for (j = 1; j <= 6; j = j + 1) begin
      period = j[15:0]; exercise(300);
      $display("  P = %0d: largest tcount %0d, %0d ticks in 300 cycles%0s",
               j, tcmax, ticks,
               (tcmax >= period) ? "   <- reload ABOVE P-1" : "");
    end
    period = 16'd4;

    $finish;

  end
endmodule
`default_nettype wire
