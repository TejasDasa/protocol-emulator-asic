"""Generate the FPGA loader's bit stream from the Python encoder.

FPGA BRING-UP INFRASTRUCTURE. Not part of the ASIC submission: nothing here
is taped out, and `rtl2/stt_loader.v` exists so a Zynq can bring the design
up with no host attached.

Everything this emits comes from the same objects the benchmarks use --
`SttProgram`, `SttCore`, `PinPlan`, `Format(...).encode`, `config_word` --
because a hand-copied stream that disagrees with the encoder by one bit is
the failure this project has already paid for twice (docs/writeup.md 4.3).

    python3 scripts/gen_fpga_rom.py --div 8 --nsm 1 -o rtl2/stt_rom.vh

The first program is a pin toggle, not a protocol: the simplest thing that
proves the loader, the imem write path, the machine and the pin path all
work at once. If the LED blinks, all four are good.

The LED is driven from slot 1, not slot 0, and that is deliberate. An output
select field holds the driver index directly, and those fields RESET to zero
-- so a pin fed by slot 0 (driver 0) would blink even if the pin-assignment
chain had never shifted a single bit. Slot 1 is driver 1, a value the chain
has to carry, so the blink distinguishes "chain loaded" from "chain matched
its reset value". The other fifteen pins keep select 0 and sit at whatever
slot 0 was initialised to, which this program never writes.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "isa_bench"))
sys.path.insert(0, os.path.join(ROOT, "rtl2", "tb"))

from lockstep import CFG_BITS, config_word          # noqa: E402
from pinmap import PinPlan                          # noqa: E402
from rowformat import Format                        # noqa: E402
from stt import Row, SttCore, SttProgram            # noqa: E402

STT_ROWS = 32
ROW_W = 32
TIMER_MAX = 0xFFFF       # cfg_period is 16 bits (SPEC section 2)


def blink_program():
    """Toggle slot 1 once every CLOAD timer periods.

    The timer alone cannot reach human time: P is 16 bits, so at 15.625 MHz a
    full period is 4.2 ms. Counter 1 supplies the rest of the ratio -- one
    decrement per timer tick, toggle when it reaches zero.

    Five rows, and the loop is exactly P cycles per iteration: TICK waits for
    the tick, DEC and CHK cost two cycles, and the timer free-runs through
    them so the next tick lands P-2 cycles later.
    """
    return SttProgram([
        Row("INIT",   "always", "TICK",              act=["cload", "trst"]),
        Row("TICK",   "tmr",    "DEC",   f="TICK"),
        Row("DEC",    "always", "CHK",               act=["cdec"]),
        Row("CHK",    "cz",     "TOGGLE", f="TICK"),
        Row("TOGGLE", "always", "TICK",   pins={1: "tgl"}, act=["cload"]),
    ])


def toggle_divisor(f_sys_hz, seconds, period):
    """How many timer ticks make one toggle take `seconds`."""
    n = round(seconds * f_sys_hz / period)
    return max(1, min(255, n))       # counter 1 is 8 bits (SPEC section 2)


def build(nsm, f_sys_hz, seconds, period):
    prog = blink_program()
    cload = toggle_divisor(f_sys_hz, seconds, period)

    core = SttCore(
        prog, slots=[("idle", "pp"), ("led", "pp")], ins=("in0", "in1"),
        period=period, cload=(cload, 0, 0),
        # Both start low, so the only pin that ever changes is the LED.
        init_pins=[0, 0],
        # Unused by this program, but every field is still a real
        # configuration value and is range-checked at construction.
        sr_width=8, c2load=0, loadk=0,
    )

    words = list(Format("single5", "grouped", tgt_bits=8).encode(prog)["packed"])
    if len(words) > STT_ROWS:
        raise SystemExit(f"{len(words)} rows, max {STT_ROWS}")
    # SPEC section 10: the host MUST load all 32 rows. A short load leaves the
    # CFGMEM chain rotated; the behavioural imem is padded identically so the
    # FPGA and ASIC paths take the same stream.
    padded = words + [0] * (STT_ROWS - len(words))

    plan = PinPlan(nsm=nsm)
    plan.drive(0, 1, 0)      # machine 0 SLOT 1 -> pin 0: driver index 1, so the
                             # chain must carry a non-zero select for this pin
    for m in range(nsm):
        for i in range(2):
            plan.read(m, i, 0)
    # No host port: this program never touches `fifo`, `load` or `push`.
    sel, nsel = plan.chain([prog] + [None] * (nsm - 1))

    one_imem = 0
    for i, w in enumerate(padded):
        one_imem |= w << (ROW_W * i)
    imem_n, cfg_n = ROW_W * STT_ROWS, CFG_BITS
    one_cfg = config_word(core)

    # One slice per machine, so the loader per-machine indexing is valid at any
    # NSM. Machine 0 runs the blink program; the rest get an all-zero program,
    # which decodes to always / WAIT / target 0 -- a self-loop at row 0 that
    # performs no action and writes no pin. They still take a real
    # configuration, because an all-zero config would mean P = 0.
    imem_bits, cfg_bits = one_imem, one_cfg
    for m in range(1, nsm):
        cfg_bits |= one_cfg << (m * cfg_n)

    return dict(core=core, prog=prog, words=words, padded=padded, cload=cload,
                imem_bits=imem_bits, imem_n=imem_n, one_imem=one_imem,
                cfg_bits=cfg_bits, cfg_n=cfg_n, nsm=nsm,
                sel_bits=sel, sel_n=nsel, period=period, f_sys=f_sys_hz)


def vh(b, name, nbits):
    """A Verilog localparam holding `nbits` of `b`, LSB presented first."""
    return f"localparam [{nbits - 1}:0] {name} = {nbits}'b{b:0{nbits}b};"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fclk", type=float, default=125e6, help="board clock Hz")
    ap.add_argument("--div", type=int, default=8, help="stt_fpga_top DIV")
    ap.add_argument("--nsm", type=int, default=1)
    ap.add_argument("--seconds", type=float, default=0.5,
                    help="seconds per LED toggle")
    ap.add_argument("--period", type=int, default=TIMER_MAX,
                    help="timer period P, in divided-clock cycles")
    ap.add_argument("-o", "--out", default=None)
    a = ap.parse_args()

    f_sys = a.fclk / a.div
    d = build(a.nsm, f_sys, a.seconds, a.period)

    real = d["cload"] * d["period"] / f_sys
    head = f"""// GENERATED by scripts/gen_fpga_rom.py -- do not edit.
//
// FPGA bring-up only. Not part of the ASIC submission.
//
// Board clock {a.fclk / 1e6:g} MHz / DIV {a.div} = {f_sys / 1e6:.6g} MHz.
// EVERY timing number below is against that divided clock, not the board's.
//
//   program            {len(d['words'])} rows, padded to {STT_ROWS} (SPEC section 10)
//   machines           {a.nsm}
//   timer period P     {d['period']} cycles = {d['period'] / f_sys * 1e3:.3f} ms
//   counter 1 reload   {d['cload']} timer ticks
//   LED toggles every  {real:.3f} s  -> {1 / (2 * real):.3f} Hz blink
//
// Streams are shifted LEAST-SIGNIFICANT BIT FIRST, which is what
// rowenc.pack and the staging register in stt_imem.v agree on. Bit i of
// each vector is presented on cycle i.
"""
    body = "\n".join([
        head,
        f"localparam integer STT_ROM_NSM   = {a.nsm};",
        f"localparam integer STT_ROM_IMEM_N = {d['imem_n']};",
        f"localparam integer STT_ROM_CFG_N  = {d['cfg_n']};",
        f"localparam integer STT_ROM_SEL_N  = {d['sel_n']};",
        "",
        vh(d["imem_bits"], "STT_ROM_IMEM", d["imem_n"] * a.nsm),
        vh(d["cfg_bits"], "STT_ROM_CFG", d["cfg_n"] * a.nsm),
        vh(d["sel_bits"], "STT_ROM_SEL", d["sel_n"]),
        "",
    ])

    if a.out:
        with open(os.path.join(ROOT, a.out), "w") as f:
            f.write(body)
        print(f"wrote {a.out}")
    else:
        print(body)

    print(f"  rows           {len(d['words'])} -> padded {STT_ROWS}")
    print(f"  imem stream    {d['imem_n']} bits")
    print(f"  config stream  {d['cfg_n']} bits")
    print(f"  pin chain      {d['sel_n']} bits  (nsm={a.nsm})")
    print(f"  f_sys          {f_sys / 1e6:.6g} MHz")
    print(f"  P              {d['period']} = {d['period'] / f_sys * 1e3:.3f} ms")
    print(f"  cload          {d['cload']} ticks -> toggle every {real:.3f} s")
    print(f"  first 3 words  {[hex(w) for w in d['padded'][:3]]}")


if __name__ == "__main__":
    main()
