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

module stt_fpga_top (
    input  wire        clk,         // H16, 125 MHz
    input  wire        btn_raw,     // D20, HIGH when pressed
    output wire        led_status,  // G17, green LED
    output wire [7:0]  uo_out,      // Pmod JA
    inout  wire [7:0]  uio          // Pmod JB
);

    // -----------------------------------------------------------------------
    // Clocking
    // -----------------------------------------------------------------------

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

    assign uio_in = ldr_done ? uio : {ldr_sm_sel, uio[4:0]};

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

    stt_loader u_loader (
        .clk    (clk_sys),
        .rst_n  (rst_n),
        .busy   (uo_out[0]),
        .ui_in  (ui_in),
        .sm_sel (ldr_sm_sel),
        .done   (ldr_done)
    );

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

    assign led_status = uo_out[0];

endmodule

`default_nettype wire