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
import programs as P_REF                            # noqa: E402

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


def uart_tx_program(period, byte):
    """The isa_bench UART TX reference, with its byte source changed.

    RETURNS (program, reference_core). The timing rows -- START, DATA, CHECK
    and STOP, which are what actually make a UART frame -- are copied from
    `programs.stt_uart_tx` untouched. Only the IDLE row changes, and it has to:

        reference   Row("IDLE", "fifo", "START", pins={0:"lo"},
                                 act=["load", "cload", "trst"])
        here        Row("IDLE", "tmr",  "START", pins={0:"lo"},
                                 act=["loadk", "cload", "trst"])

    The reference is a HOST-FED transmitter. `fifo` tests the TX FIFO and
    `load` pops a byte from it, so with no host attached `fifo` is permanently
    false and the machine sits in IDLE forever without sending anything. The
    pin plan cannot fix that -- it is not a pin assignment problem -- so the
    byte source moves to `loadk`, which loads the configured constant K. Both
    are first-class actions in SPEC section 6.

    The gate becomes `tmr` rather than `always`, and that is not cosmetic.
    With `always` the next frame starts the cycle after the stop bit ends, and
    for 0x55 -- which alternates -- the line becomes an unbroken square wave:
    every frame is start,1,0,1,0,1,0,1,0,stop = 0101010101, so the whole
    stream is periodic with a period of two bit times and NO frame boundary
    exists to find. A receiver still decodes 0x55 from any phase, but nothing
    can verify the framing, in simulation or on a scope. `tmr` holds IDLE for
    one more bit period, so each frame is start + 8 data + stop + one idle
    bit, the line is high for two consecutive bit times between frames, and
    the boundary is unambiguous.
    """
    _ref_core, ref = P_REF.STT_1PIN["uart_tx"](period)
    rows = []
    for r in ref.rows:
        test, act = r.test, list(r.act)
        if r.name == "IDLE":
            test = "tmr"
            act = ["loadk" if a == "load" else a for a in act]
        rows.append(Row(r.name, test, r.t, f=r.f, pins=dict(r.pins), act=act))
    return SttProgram(rows), _ref_core


def baud_period(f_sys_hz, baud):
    """(P, achieved baud, error fraction). P is an integer number of cycles,
    so the achieved rate is rarely exactly the requested one."""
    p = max(1, round(f_sys_hz / baud))
    got = f_sys_hz / p
    return p, got, (got - baud) / baud


def toggle_divisor(f_sys_hz, seconds, period):

    """How many timer ticks make one toggle take `seconds`."""
    n = round(seconds * f_sys_hz / period)
    return max(1, min(255, n))       # counter 1 is 8 bits (SPEC section 2)


def build(nsm, f_sys_hz, which, seconds, period, baud, byte):
    """Returns everything the ROM and the report need, for one program."""
    info = {}
    if which == "blink":
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
        tx_slot, park_slot = 1, None
        info["cload"] = cload
        info["toggle_s"] = cload * period / f_sys_hz
    else:
        period, got, err = baud_period(f_sys_hz, baud)
        prog, ref = uart_tx_program(period, byte)
        core = SttCore(
            prog, slots=[("tx", "pp")], ins=("in0", "in1"),
            period=period,
            # Bit order and the idle/stop level come from the reference core,
            # not from this file: shift right puts the LSB out first and the
            # fill bit is 1, so the line returns high after the last data bit.
            shift=ref.shift, fill=ref.fill,
            # K is what `loadk` puts in the shift register -- the byte sent.
            loadk=byte,
            # The reference sends cload_a bits after the start bit.
            cload=ref.cvals,
            sr_width=8, c2load=0,
            # The line idles HIGH. pinv takes this while the machine is held,
            # so the pin is already high when `run` releases it to the iomux.
            init_pins=[1],
        )
        tx_slot, park_slot = 0, 2
        info.update(baud_want=baud, baud_got=got, baud_err=err, byte=byte)
    cload = info.get("cload", 0)

    words = list(Format("single5", "grouped", tgt_bits=8).encode(prog)["packed"])
    if len(words) > STT_ROWS:
        raise SystemExit(f"{len(words)} rows, max {STT_ROWS}")
    # SPEC section 10: the host MUST load all 32 rows. A short load leaves the
    # CFGMEM chain rotated; the behavioural imem is padded identically so the
    # FPGA and ASIC paths take the same stream.
    padded = words + [0] * (STT_ROWS - len(words))

    plan = PinPlan(nsm=nsm)
    # Pin 0 is uo_out[0], Pmod JA pin 1.
    plan.drive(0, tx_slot, 0)
    if park_slot is not None:
        # Every other pin is parked on a slot this program never writes, so it
        # sits at its init value instead of carrying a copy of the signal. The
        # select code for a parked pin is `park_slot`, which is NOT the value
        # those fields reset to, so a chain that shifted the wrong content --
        # all zeros, say -- shows up as traffic on fifteen pins that should be
        # quiet. See the note on select codes in the report below.
        for pin in range(1, 16):
            plan.drive(0, park_slot, pin)
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
                which=which, tx_slot=tx_slot, park_slot=park_slot, info=info,
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
    ap.add_argument("--program", choices=("blink", "uart_tx"), default="blink",
                    help="blink is the known-good fallback: if it stops "
                         "working, something regressed rather than the new "
                         "program being wrong")
    ap.add_argument("--baud", type=int, default=9600)
    ap.add_argument("--byte", type=lambda x: int(x, 0), default=0x55,
                    help="byte to transmit; 0x55 alternates 1010101 so a wrong "
                         "baud gives visibly wrong characters, not plausible ones")
    ap.add_argument("--seconds", type=float, default=0.5,
                    help="seconds per LED toggle")
    ap.add_argument("--period", type=int, default=TIMER_MAX,
                    help="timer period P, in divided-clock cycles")
    ap.add_argument("-o", "--out", default=None)
    a = ap.parse_args()

    f_sys = a.fclk / a.div
    d = build(a.nsm, f_sys, a.program, a.seconds, a.period, a.baud, a.byte)
    i = d["info"]

    if a.program == "blink":
        what = (f"//   timer period P     {d['period']} cycles = "
                f"{d['period'] / f_sys * 1e3:.3f} ms\n"
                f"//   counter 1 reload   {d['cload']} timer ticks\n"
                f"//   LED toggles every  {i['toggle_s']:.3f} s"
                f"  -> {1 / (2 * i['toggle_s']):.3f} Hz blink")
    else:
        what = (f"//   bit period P       {d['period']} cycles = "
                f"{d['period'] / f_sys * 1e6:.3f} us\n"
                f"//   baud requested     {i['baud_want']}\n"
                f"//   baud achieved      {i['baud_got']:.2f}"
                f"  ({i['baud_err'] * 100:+.4f}%)\n"
                f"//   byte transmitted   0x{i['byte']:02X}, LSB first, "
                f"continuously\n"
                f"//   TX pin             uo_out[0] = Pmod JA pin 1")
    real = i.get("toggle_s", 0)
    head = f"""// GENERATED by scripts/gen_fpga_rom.py -- do not edit.
//
// FPGA bring-up only. Not part of the ASIC submission.
//
// Board clock {a.fclk / 1e6:g} MHz / DIV {a.div} = {f_sys / 1e6:.6g} MHz.
// EVERY timing number below is against that divided clock, not the board's.
//
//   program            {a.program}, {len(d['words'])} rows, padded to {STT_ROWS} (SPEC section 10)
//   machines           {a.nsm}
{what}
//
// Streams are shifted LEAST-SIGNIFICANT BIT FIRST, which is what
// rowenc.pack and the staging register in stt_imem.v agree on. Bit i of
// each vector is presented on cycle i.
"""
    body = "\n".join([
        head,
        f"localparam integer STT_ROM_NSM   = {a.nsm};",
        # Emitted so the testbench can assert the bit period without anyone
        # re-typing it. A hand-copied timing constant that disagrees with the
        # ROM is the same class of bug as a hand-copied bit stream.
        f"localparam integer STT_ROM_PERIOD = {d['period']};",
        f"localparam integer STT_ROM_IS_UART = {1 if a.program == 'uart_tx' else 0};",
        f"localparam [7:0]   STT_ROM_BYTE   = 8'h{i.get('byte', 0):02X};",
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

    print(f"  program        {a.program}")
    print(f"  rows           {len(d['words'])} -> padded {STT_ROWS}")
    print(f"  imem stream    {d['imem_n']} bits")
    print(f"  config stream  {d['cfg_n']} bits")
    print(f"  pin chain      {d['sel_n']} bits  (nsm={a.nsm})")
    print(f"  f_sys          {f_sys / 1e6:.6g} MHz")
    if a.program == "blink":
        print(f"  P              {d['period']} = {d['period'] / f_sys * 1e3:.3f} ms")
        print(f"  cload          {d['cload']} ticks -> toggle every {real:.3f} s")
    else:
        print(f"  P              {d['period']} cycles = "
              f"{d['period'] / f_sys * 1e6:.3f} us per bit")
        print(f"  baud           {i['baud_want']} requested, "
              f"{i['baud_got']:.2f} achieved ({i['baud_err'] * 100:+.4f}%)")
        print(f"  byte           0x{i['byte']:02X}, LSB first, continuous")
        print(f"  TX             slot {d['tx_slot']} -> pin 0 (uo_out[0], JA1), "
              f"select code {d['tx_slot']}")
        print(f"  parked         pins 1..15 -> slot {d['park_slot']}, "
              f"select code {d['park_slot']}")
    print(f"  first 3 words  {[hex(w) for w in d['padded'][:3]]}")


if __name__ == "__main__":
    main()
