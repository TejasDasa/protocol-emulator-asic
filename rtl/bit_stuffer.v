// bit_stuffer -- configurable bit stuffing: insert or remove a bit after N
// identical bits.
//
// Priced separately from the STT core (docs/area-study.md).  Today the USB
// benchmark does stuffing in software, costing rows and a second counter; this
// unit is the alternative.
//
// Two counting rules, both in use in real protocols:
//   run_ones = 1 : count consecutive 1s only, reset on a 0    (USB, HDLC)
//   run_ones = 0 : count consecutive identical bits           (CAN)
//
// Two directions:
//   insert (TX): after N, emit the stuffed bit and do NOT consume an input bit
//   remove (RX): after N, consume the next input bit and mark it dropped
//
// Handshake: `in_valid`/`in_ready` on the input side, `out_valid` on the output.
// During an insert cycle `in_ready` is low: the producer is stalled for one bit.
`default_nettype none

module bit_stuffer #(
    parameter CNT_W = 4            // run length up to 2**CNT_W - 1
) (
    input  wire              clk,
    input  wire              rst_n,

    // configuration
    input  wire [CNT_W-1:0]  n_in,        // stuff after this many identical bits
    input  wire              n_we,
    input  wire              mode_insert_in,
    input  wire              mode_ones_in,
    input  wire              mode_we,

    input  wire              en,
    input  wire              flush,       // clear the run counter (frame boundary)

    input  wire              in_valid,
    input  wire              in_bit,
    output wire              in_ready,

    output wire              out_valid,
    output wire              out_bit,
    output wire              out_stuffed  // this bit was inserted / dropped
);

  reg [CNT_W-1:0] n_cfg;
  reg             mode_insert;
  reg             mode_ones;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)       n_cfg <= {CNT_W{1'b0}};
    else if (n_we)    n_cfg <= n_in;
  end

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      mode_insert <= 1'b0;
      mode_ones   <= 1'b0;
    end else if (mode_we) begin
      mode_insert <= mode_insert_in;
      mode_ones   <= mode_ones_in;
    end
  end

  reg [CNT_W-1:0] run;
  reg             last_bit;

  wire hit = (run == n_cfg) & |n_cfg;      // N reached (N = 0 disables stuffing)

  // On an insert cycle the unit emits the opposite of the run bit and stalls
  // the producer for one cycle.
  wire inserting = en & mode_insert & hit;
  wire removing  = en & ~mode_insert & hit & in_valid;

  assign in_ready   = en & ~inserting;
  assign out_valid  = en & (inserting | (in_valid & ~removing));
  assign out_bit    = inserting ? ~last_bit : in_bit;
  assign out_stuffed = inserting | removing;

  // the bit that actually advances the run counter
  wire        adv     = inserting | (in_valid & en);
  wire        cur_bit = inserting ? ~last_bit : in_bit;
  wire        same    = mode_ones ? cur_bit : (cur_bit == last_bit);

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      run      <= {CNT_W{1'b0}};
      last_bit <= 1'b0;
    end else if (flush) begin
      run      <= {CNT_W{1'b0}};
      last_bit <= 1'b0;
    end else if (adv) begin
      last_bit <= cur_bit;
      if (hit | ~same) run <= {{(CNT_W-1){1'b0}}, 1'b1};
      else             run <= run + {{(CNT_W-1){1'b0}}, 1'b1};
    end
  end

endmodule
`default_nettype wire
