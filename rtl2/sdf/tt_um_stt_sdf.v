// Annotation wrapper. cocotb cannot call $sdf_annotate from Python, and the
// call has to name the instance whose hierarchy the SDF describes, so the
// gate netlist is wrapped one level deep and annotated here.
//
// Ports are identical to tt_um_stt, so the cocotb testbench is unchanged.
`timescale 1ns/1ps
`default_nettype none

module tt_um_stt_sdf (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);
  tt_um_stt dut (
      .ui_in(ui_in), .uo_out(uo_out),
      .uio_in(uio_in), .uio_out(uio_out), .uio_oe(uio_oe),
      .ena(ena), .clk(clk), .rst_n(rst_n)
  );

  initial begin
`ifdef SDF_FILE
    $sdf_annotate(`SDF_FILE, dut);
    $display("SDF: annotated %s", `SDF_FILE);
`else
    $display("SDF: NOT ANNOTATED -- measurements would be meaningless");
`endif
  end
endmodule
`default_nettype wire
