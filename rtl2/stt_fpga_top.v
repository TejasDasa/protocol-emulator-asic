// stt_fpga_top.v
//
// FPGA wrapper for the STT protocol emulator on a Digilent Cora Z7-07S.
//
// Does three things the ASIC boundary does not need:
//   1. Divides the board's 125 MHz clock down to something sane for bring-up.
//   2. Inverts the active-high button into the design's active-low rst_n.
//   3. Combines uio_in / uio_out / uio_oe into a real bidirectional pin group.
//
// CHECK BEFORE USING:
//   - That tt_um_stt instantiates stt_top (behavioural imem) and NOT
//     stt_top_cfgmem. There are no CFGMEM macros on a Zynq. If it hardcodes
//     the cfgmem variant, instantiate stt_chip here instead and tie off its
//     dbg_* ports.
//   - The NSM parameter. Five machines may not fit the 07S (~14,400 LUTs).
//     Start at 1, check utilization, then raise it.

`default_nettype none

module stt_fpga_top #(
    // 125 MHz / DIV. Must be even (this is a toggle divider).
    // DIV=8 -> 15.625 MHz, DIV=10 -> 12.5 MHz, DIV=4 -> 31.25 MHz.
    // Whatever you pick, the timer period P in every program must be
    // computed against THIS frequency, not 125 MHz and not 45 MHz.
    parameter integer DIV = 8
) (
    input  wire        clk,         // H16, 125 MHz
    input  wire        btn_raw,     // D20, HIGH when pressed
    output wire        led_status,  // G17, green LED
    output wire [7:0]  uo_out,      // Pmod JA
    inout  wire [7:0]  uio          // Pmod JB
);

    // -----------------------------------------------------------------------
    // Clock division
    // -----------------------------------------------------------------------
    // A toggle divider plus a BUFG. For anything beyond bring-up, replace this
    // with a Clocking Wizard MMCM — it gives a proper duty cycle and lets the
    // tools reason about the clock properly.

    localparam integer HALF = DIV / 2;

    reg [15:0] divcnt = 16'd0;
    reg        clk_div_r = 1'b0;

    always @(posedge clk) begin
        if (divcnt == HALF[15:0] - 16'd1) begin
            divcnt    <= 16'd0;
            clk_div_r <= ~clk_div_r;
        end else begin
            divcnt <= divcnt + 16'd1;
        end
    end

    wire clk_sys;
    BUFG u_bufg (.I(clk_div_r), .O(clk_sys));

    // -----------------------------------------------------------------------
    // Reset
    // -----------------------------------------------------------------------
    // The button reads HIGH when pressed, so rst_n is its inverse. Also hold
    // reset for a while after configuration, because the design must not be
    // enabled before its inputs have been stable — see SPEC 8.3.

    reg [7:0] por_cnt = 8'd0;
    wire      por_done = por_cnt[7];

    always @(posedge clk_sys) begin
        if (!por_done) por_cnt <= por_cnt + 8'd1;
    end

    wire rst_n = por_done & ~btn_raw;

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
    // Currently mirrors uo_out[0], so a slow pin-toggle program is visible
    // without any test equipment. That is the step-3 milestone: if this
    // blinks, the loader, the machine and the pin path all work.
    //
    // Once you are past that, change it to the loader's "done" flag so you can
    // tell "configured" from "running".

    // uo_out[0] is imem_ld_busy while the loader runs and the machine's slot
    // output afterwards, so this is dark through configuration and then
    // blinks. If it blinks, the loader, the imem write path, the machine and
    // the pin path all work -- that is the whole milestone.
    assign led_status = uo_out[0];

endmodule

`default_nettype wire