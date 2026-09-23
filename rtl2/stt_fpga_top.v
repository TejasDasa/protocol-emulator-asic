// stt_fpga_top.v
//
// FPGA wrapper for the STT protocol emulator on a Digilent Cora Z7-07S.
//
// Does three things the ASIC boundary does not need:
//   1. Brings the board's 125 MHz clock down to a bring-up frequency.
//   2. Inverts the active-high button into the design's active-low rst_n.
//   3. Combines uio_in / uio_out / uio_oe into a real bidirectional pin group.
//
// Clocking is a Clocking Wizard MMCM rather than a toggle divider. The divider
// worked, but its output was not a clock Vivado knew about, so nothing
// downstream of it was timed at all -- every register in the design reported
// "clock pin not reached by a timing clock". The IP brings its own constraints.
//
// BEFORE USING:
//   - Generate the Clocking Wizard IP with component name clk_wiz_0:
//       input  125 MHz, single ended clock capable pin
//       output clk_out1 at 15.625 MHz
//       keep the `locked` port, drop `reset`
//   - If you choose an output frequency other than 15.625 MHz, REGENERATE THE
//     ROM. Every timer period P was computed against the clock the generator
//     was told about, and a mismatch silently changes every protocol's timing.
//   - Set STT_NSM via synthesis options (-verilog_define STT_NSM=1). It is a
//     define, not a parameter, so it cannot be overridden from here.

`default_nettype none

module stt_fpga_top #(
    // Where machine 1's RX pin gets its value, for the loopback ROM.
    //   1 = internally, straight from the TX pin inside the FPGA. Removes
    //       wiring as a variable for first bring-up.
    //   0 = from the physical uio[0] pin, so the loop leaves the chip through
    //       a jumper between Pmod JA pin 1 and Pmod JB pin 1. This is the
    //       real test: it goes through the actual IOBUFs and board traces.
    // Override at synthesis with: synth_design -generic LOOPBACK_INTERNAL=0
    //
    // Either way the chip RELEASES uio[0]: the loopback ROM parks that pin on
    // an open-drain slot holding 1, so pin_oe is 0 there. Without that the
    // chip would drive the same net the jumper drives.
    parameter integer LOOPBACK_INTERNAL = 1
) (
    input  wire        clk,         // H16, 125 MHz
    input  wire        btn_raw,     // D20, HIGH when pressed
    output wire        led_status,  // G17, green LED
    output wire [7:0]  uo_out,      // Pmod JA
    inout  wire [7:0]  uio          // Pmod JB
);

    // -----------------------------------------------------------------------
    // Clocking
    // -----------------------------------------------------------------------

    `include "stt_rom.vh"

    wire clk_sys;
    wire locked;

    clk_wiz_0 u_clk (
        .clk_in1  (clk),
        .clk_out1 (clk_sys),
        .locked   (locked)
    );

    // -----------------------------------------------------------------------
    // Reset
    // -----------------------------------------------------------------------
    // `locked` replaces the old power-on counter and does the job properly:
    // it is low until the MMCM output is stable, so the design cannot run on
    // an unsettled clock. The button reads HIGH when pressed, so rst_n is its
    // inverse.

    reg [2:0] rst_sync = 3'b000;
    always @(posedge clk_sys or negedge locked) begin
        if (!locked) rst_sync <= 3'b000;
        else         rst_sync <= {rst_sync[1:0], ~btn_raw};
    end
    wire rst_n = rst_sync[2];

    // -----------------------------------------------------------------------
    // Bidirectional pins
    // -----------------------------------------------------------------------
    // This is what the ASIC's pad ring does. Vivado infers an IOBUF per bit.

    wire [7:0] uio_out;
    wire [7:0] uio_oe;
    wire [7:0] uio_in;

    genvar i;
    generate
        for (i = 0; i < 8; i = i + 1) begin : g_uio
            assign uio[i] = uio_oe[i] ? uio_out[i] : 1'bz;
        end
    endgenerate

    // sm_sel (SPEC section 10) arrives on uio_in[7:5], which on this board is
    // the Pmod JB header. Nothing drives those pins, so they float, and a
    // float that reads anything but 000 means the load enables never reach
    // machine 0 and NOTHING IS EVER LOADED -- with NSM=1 it also indexes a
    // one-element busy array out of range. So while the loader is running the
    // select comes from the loader, and only afterwards from the pins.

    wire [2:0] ldr_sm_sel;
    wire       ldr_done;

    // The loopback source for uio_in[0], which the loopback ROM assigns as
    // machine 1's in0. A machine cannot read back a uo_out pin -- the iomux
    // input map is {uio_in, ui_in}, so pin index p < 8 reads ui_in[p], a
    // different physical pin -- which is why the loop has to arrive on uio.
    wire lb_bit = (LOOPBACK_INTERNAL != 0) ? uo_out[0] : uio[0];
    wire [7:0] uio_pins = {uio[7:1], lb_bit};

    assign uio_in = ldr_done ? uio_pins : {ldr_sm_sel, uio_pins[4:0]};

    // -----------------------------------------------------------------------
    // ui_in -- driven by the on-chip loader, not by pins
    // -----------------------------------------------------------------------
    // The loader shifts in the program, the configuration and the pin
    // assignment, and the last bit of the pin assignment leaves `run` set.
    // After that it drives ui_in to zero and the pins belong to the iomux.
    //
    // busy comes back on uo_out[0]: while run is low that pin carries
    // imem_ld_busy rather than an iomux output (stt_chip.v), which is how the
    // host sees the flag SPEC section 10 requires it to honour.

    wire [7:0] ui_in;
    wire [7:0] ldr_ui;

    stt_loader u_loader (
        .clk    (clk_sys),
        .rst_n  (rst_n),
        .busy   (uo_out[0]),
        .ui_in  (ldr_ui),
        .sm_sel (ldr_sm_sel),
        .done   (ldr_done)
    );

    // -----------------------------------------------------------------------
    // Host port reader (loopback ROM only)
    // -----------------------------------------------------------------------
    // The UART RX reference program drives no pins -- it pushes -- so the only
    // way to see what it received is to read its RX FIFO over the SPEC 11.2
    // host byte port. The loopback pin plan puts that port on
    // dout = uo_out[1], stb = ui_in[7], din = ui_in[6].
    //
    // Harmless under the blink and uart_tx ROMs: those assign no host port, so
    // host_en is 0, the chip ignores the strobe, and every reply reads back
    // rx_ne = 0.

    wire       hr_stb, hr_din;
    wire [7:0] hr_byte;
    localparam integer HOST_WREN_I = STT_ROM_HOST_WREN;
    wire       hr_valid;
    wire [3:0] hr_status;
    wire [31:0] hr_good, hr_bad;

    // Everything about what to write, what to expect and where the data-out
    // pin is comes from the ROM, so switching protocol is a regeneration and
    // not an RTL edit. usb_ls_token_tx needs the write path: it takes three
    // DIFFERENT bytes through `load`, which `loadk` cannot supply.
    stt_hostread #(
        .NW (STT_ROM_HOST_NW),
        .NR (STT_ROM_HOST_NR)
    ) u_hostread (
        .clk         (clk_sys),
        .rst_n       (rst_n),
        .start       (ldr_done),
        .wr_en       (HOST_WREN_I[0]),
        .wr_sel      (STT_ROM_HOST_WSEL),
        .wr_seq      (STT_ROM_HOST_WSEQ),
        .rd_sel      (STT_ROM_HOST_RSEL),
        .rd_seq      (STT_ROM_HOST_RSEQ),
        .wr_gap      (STT_ROM_HOST_WGAP[15:0]),
        .dout        (uo_out[STT_ROM_HOST_DOUT]),
        .stb         (hr_stb),
        .din         (hr_din),
        .last_byte   (hr_byte),
        .last_valid  (hr_valid),
        .last_status (hr_status),
        .good_count  (hr_good),
        .bad_count   (hr_bad)
    );

    // The loader owns ui_in until it is done; the reader owns it afterwards.
    assign ui_in = ldr_done ? {hr_stb, hr_din, 6'b0} : ldr_ui;

    // -----------------------------------------------------------------------
    // The design
    // -----------------------------------------------------------------------

    tt_um_stt u_stt (
        .clk      (clk_sys),
        .rst_n    (rst_n),
        .ena      (1'b1),
        .ui_in    (ui_in),
        .uo_out   (uo_out),
        .uio_in   (uio_in),
        .uio_out  (uio_out),
        .uio_oe   (uio_oe)
    );

    // -----------------------------------------------------------------------
    // Status LED
    // -----------------------------------------------------------------------
    // uo_out[0] is imem_ld_busy while the loader runs and the machine's slot
    // output afterwards, so this is dark through configuration and then
    // blinks. If it blinks, the loader, the imem write path, the machine and
    // the pin path all work -- that is the whole milestone.

    // Under the loopback ROM the LED reports RECEPTION, not the TX waveform:
    // it toggles once per 256 correctly received bytes, so at 9600 baud with a
    // byte every 11 bit times it blinks at a couple of Hz.
    //
    //   blinking  -> bytes are arriving and every one matches
    //   dark      -> nothing is being received at all
    //   solid     -> reception stopped, or bytes are arriving wrong
    //
    // Under blink and uart_tx there is no host port, so hr_good never moves
    // and the LED falls back to mirroring uo_out[0] as before.
    // The bit is chosen by the generator from the protocol's byte rate so the
    // blink lands near 1.5 Hz whether bytes arrive at 900 a second or 190,000.
    assign led_status = (STT_ROM_IS_LOOPBACK != 0) ? hr_good[STT_ROM_LED_BIT]
                                                   : uo_out[0];

endmodule

`default_nettype wire