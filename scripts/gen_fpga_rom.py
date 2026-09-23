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
from devices import crc5_usb, bits_lsb              # noqa: E402
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


# Loopback pin assignment. TX must be a uo_out pin and RX must read a uio pin,
# because the iomux's input map is pin_val = {uio_in, ui_in}: pin index p < 8
# reads ui_in[p], NOT uo_out[p]. uo_out and ui_in are different physical pins
# that happen to share an index, so a machine CANNOT read back a uo_out pin and
# the loop has to leave the chip and come back on uio.
LB_TX_PIN    = 0    # uo_out[0], Pmod JA pin 1
LB_RX_PIN    = 8    # uio[0],    Pmod JB pin 1
LB_DOUT_PIN  = 1    # uo_out[1], Pmod JA pin 2 -- host port data out
LB_STB_PIN   = 7    # ui_in[7]  -- host port strobe
LB_DIN_PIN   = 6    # ui_in[6]  -- host port data in

# USB loopback. The transmitter's pair writes two slots at once, so D+ and D-
# take two pins; only D+ is looped back, because the receiver has two inputs
# and the second is spent on the decoded-bit loopback NRZI needs.
UB_DP_PIN    = 0    # uo_out[0], JA1 -- D+, the loop source
UB_DM_PIN    = 1    # uo_out[1], JA2 -- D-, observable but not looped
UB_DOUT_PIN  = 2    # uo_out[2], JA3 -- host port data out
UB_ARRIVE    = 8    # uio[0],    JB1 -- where D+ comes back
UB_DEC_PIN   = 9    # uio[1],    JB2 -- the decoded-bit loopback
#
# UB_DEC_PIN needs no wire. A uio pin is bidirectional and its input path sees
# what the chip drives, so a machine can read its own output back through the
# pad. That is the whole of the self-loopback on this side.


def pad_rows(prog):
    words = list(Format("single5", "grouped", tgt_bits=8).encode(prog)["packed"])
    if len(words) > STT_ROWS:
        raise SystemExit(f"{len(words)} rows, max {STT_ROWS}")
    # SPEC section 10: the host MUST load all 32 rows. A short load leaves the
    # CFGMEM chain rotated; the behavioural imem is padded identically so the
    # FPGA and ASIC paths take the same stream.
    return words, words + [0] * (STT_ROWS - len(words))


def build(nsm, f_sys_hz, which, seconds, period, baud, byte,
          usb_period=10, usb_token=(0x2D, 0x3A)):
    """Returns everything the ROM and the report need.

    `cores` and `progs` are per machine, index 0 first. A machine with no
    program of its own gets an all-zero one, which decodes to
    `always / WAIT / target 0` -- a self-loop at row 0 that performs no action
    and writes no pin -- but still takes a real configuration, because an
    all-zero config would mean P = 0.
    """
    info = {}
    cores, progs = [], []

    if which == "blink":
        prog = blink_program()
        cload = toggle_divisor(f_sys_hz, seconds, period)
        core = SttCore(
            prog, slots=[("idle", "pp"), ("led", "pp")], ins=("in0", "in1"),
            period=period, cload=(cload, 0, 0),
            # Both start low, so the only pin that ever changes is the LED.
            init_pins=[0, 0],
            sr_width=8, c2load=0, loadk=0,
        )
        cores, progs = [core], [prog]
        info.update(cload=cload, toggle_s=cload * period / f_sys_hz)

        def plan_of(plan):
            plan.drive(0, 1, 0)          # slot 1 -> pin 0: select code 1
            for m in range(nsm):
                for i in range(2):
                    plan.read(m, i, 0)
            return None

    elif which == "uart_tx":
        period, got, err = baud_period(f_sys_hz, baud)
        prog, ref = uart_tx_program(period, byte)
        core = SttCore(
            prog, slots=[("tx", "pp")], ins=("in0", "in1"), period=period,
            # Bit order and the idle/stop level come from the reference core,
            # not from this file.
            shift=ref.shift, fill=ref.fill, loadk=byte, cload=ref.cvals,
            sr_width=8, c2load=0, init_pins=[1],
        )
        cores, progs = [core], [prog]
        info.update(baud_want=baud, baud_got=got, baud_err=err, byte=byte)

        def plan_of(plan):
            plan.drive(0, 0, LB_TX_PIN)
            # Every other pin parks on machine 0 slot 2, which this program
            # never writes. Select code 2 is NOT what those fields reset to,
            # so a chain carrying the wrong content shows up as traffic on
            # pins that should be quiet.
            for pin in range(1, 16):
                plan.drive(0, 2, pin)
            for m in range(nsm):
                for i in range(2):
                    plan.read(m, i, 0)
            return None

    elif which == "usb_loopback":
        if nsm < 2:
            raise SystemExit("usb_loopback needs --nsm 2")
        period = usb_period
        tx_core_ref, tx_prog = P_REF.STT_1PIN["usb"](period)
        rx_core_ref, rx_prog = P_REF.stt_usb_rx(period)

        # The transmitter unchanged, but with a second slot that releases the
        # pin D+ comes back on, so an external jumper does not fight the chip.
        tx_core = SttCore(
            tx_prog, slots=[("dp", "pp"), ("dm", "pp")], period=period,
            shift=tx_core_ref.shift, fill=tx_core_ref.fill,
            cload=tx_core_ref.cvals, c2load=tx_core_ref.c2val,
            loadk=tx_core_ref.k, sr_width=8, init_pins=[0, 1],
        )
        rx_core = SttCore(
            rx_prog, slots=[("dec", "pp"), ("release", "od")],
            ins=["dec", "dp"], period=period,
            shift=rx_core_ref.shift, fill=rx_core_ref.fill,
            cload=rx_core_ref.cvals, c2load=rx_core_ref.c2val,
            sr_width=8, loadk=0,
            # slot 1 is open drain holding 1, so the pin D+ arrives on is
            # released; slot 0 drives the decoded bit and is read back.
            init_pins=[0, 1],
        )
        cores, progs = [tx_core, rx_core], [tx_prog, rx_prog]
        pid, field = usb_token
        crc = crc5_usb(bits_lsb(field, 11))
        wseq = [pid, field & 0xFF, field >> 8]
        rseq = [0x80, pid, field & 0xFF, ((field >> 8) & 0x7) | (crc << 3)]
        info.update(period=period, pid=pid, field=field, crc5=crc,
                    wseq=wseq, rseq=rseq, bitrate=f_sys_hz / period,
                    host=dict(wr_en=1, wsel=0, rsel=1,
                              dout_pin=UB_DOUT_PIN, stb_pin=LB_STB_PIN,
                              din_pin=LB_DIN_PIN))

        def plan_of(plan):
            plan.drive(0, 0, UB_DP_PIN)                    # D+
            plan.drive(0, 1, UB_DM_PIN)                    # D-
            plan.drive(1, 1, UB_ARRIVE, od=True)           # release the arrival
            plan.drive(1, 0, UB_DEC_PIN)                   # decoded-bit loopback
            plan.read(1, 0, UB_DEC_PIN)                    # in0 = it, read back
            plan.read(1, 1, UB_ARRIVE)                     # in1 = D+
            plan.read(0, 0, UB_ARRIVE)
            plan.read(0, 1, UB_ARRIVE)
            plan.host_port(UB_DOUT_PIN, LB_STB_PIN, LB_DIN_PIN)
            for pin in range(3, 16):
                if pin not in (UB_ARRIVE, UB_DEC_PIN):
                    plan.drive(0, 2, pin)
            return None

    else:                                 # loopback

        if nsm < 2:
            raise SystemExit("loopback needs --nsm 2: TX on machine 0, "
                             "RX on machine 1")
        period, got, err = baud_period(f_sys_hz, baud)
        tx_prog, tx_ref = uart_tx_program(period, byte)
        rx_ref, rx_prog = P_REF.STT_1PIN["uart_rx"](period)

        tx_core = SttCore(
            tx_prog, slots=[("tx", "pp")], ins=("in0", "in1"), period=period,
            shift=tx_ref.shift, fill=tx_ref.fill, loadk=byte,
            cload=tx_ref.cvals, sr_width=8, c2load=0, init_pins=[1],
        )
        # The RX reference declares slots=[] -- it drives nothing, it only
        # reads in0 and pushes. But the hardware always has NSLOT slots per
        # machine, and every pin's output select names SOME driver, so the pin
        # the loop arrives on would be driven by whatever slot its select
        # happens to hold. Giving machine 1 one OPEN-DRAIN slot that holds 1
        # releases that pin: pin_oe = ~od_mask | ~pinv = 0. Without this an
        # external jumper fights the chip's own driver.
        rx_core = SttCore(
            rx_prog, slots=[("rx_pullup", "od")], ins=("rx", "unused"),
            period=period, shift=rx_ref.shift, fill=rx_ref.fill,
            cload=rx_ref.cvals, sr_width=8, c2load=0, loadk=0,
            init_pins=[1],
        )
        cores, progs = [tx_core, rx_core], [tx_prog, rx_prog]
        info.update(baud_want=baud, baud_got=got, baud_err=err, byte=byte,
                    tx_pin=LB_TX_PIN, rx_pin=LB_RX_PIN,
                    dout_pin=LB_DOUT_PIN, stb_pin=LB_STB_PIN,
                    din_pin=LB_DIN_PIN)

        def plan_of(plan):
            plan.drive(0, 0, LB_TX_PIN)                    # m0 slot 0 -> JA1
            plan.drive(1, 0, LB_RX_PIN, od=True)           # release JB1
            plan.read(1, 0, LB_RX_PIN)                     # m1 in0 <- JB1
            plan.read(1, 1, LB_RX_PIN)
            plan.read(0, 0, LB_RX_PIN)                     # unused by TX
            plan.read(0, 1, LB_RX_PIN)
            # machine 1 pushes, so SPEC 11.2 requires a host port; it is also
            # the only way to see what RX received, since RX drives no pin.
            plan.host_port(LB_DOUT_PIN, LB_STB_PIN, LB_DIN_PIN)
            for pin in range(2, 16):
                if pin != LB_RX_PIN:
                    plan.drive(0, 2, pin)                  # quiet, select 2
            return None

    period = cores[0].P
    plan = PinPlan(nsm=nsm)
    plan_of(plan)
    sel, nsel = plan.chain(progs + [None] * (nsm - len(progs)))

    imem_n, cfg_n = ROW_W * STT_ROWS, CFG_BITS
    imem_bits = cfg_bits = 0
    rows0 = None
    for m in range(nsm):
        if m < len(progs):
            words, padded = pad_rows(progs[m])
            if rows0 is None:
                rows0 = words
            one = 0
            for i, w in enumerate(padded):
                one |= w << (ROW_W * i)
            imem_bits |= one << (m * imem_n)
            cfg_bits |= config_word(cores[m]) << (m * cfg_n)
        else:
            cfg_bits |= config_word(cores[0]) << (m * cfg_n)

    return dict(cores=cores, progs=progs, core=cores[0], prog=progs[0],
                words=rows0, cload=info.get("cload", 0),
                which=which, info=info,
                imem_bits=imem_bits, imem_n=imem_n,
                cfg_bits=cfg_bits, cfg_n=cfg_n, nsm=nsm,
                sel_bits=sel, sel_n=nsel, period=period, f_sys=f_sys_hz)


def seq_word(seq):
    """Bytes packed so index 0 is the low byte, which is how the RTL slices."""
    v = 0
    for k, b in enumerate(seq):
        v |= (b & 0xFF) << (8 * k)
    return v


def vh(b, name, nbits):
    """A Verilog localparam holding `nbits` of `b`, LSB presented first."""
    return f"localparam [{nbits - 1}:0] {name} = {nbits}'b{b:0{nbits}b};"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fclk", type=float, default=125e6, help="board clock Hz")
    ap.add_argument("--div", type=int, default=8, help="stt_fpga_top DIV")
    ap.add_argument("--nsm", type=int, default=1)
    ap.add_argument("--program",
                    choices=("blink", "uart_tx", "loopback", "usb_loopback"),
                    default="blink",
                    help="blink is the known-good fallback: if it stops "
                         "working, something regressed rather than the new "
                         "program being wrong")
    ap.add_argument("--baud", type=int, default=9600)
    ap.add_argument("--usb-period", type=int, default=10,
                    help="clocks per USB bit cell. The receiver needs at "
                         "least 9: it drives each decoded bit on a pin and "
                         "reads it back through the two-cycle synchronizer "
                         "before `shift` can take it.")
    ap.add_argument("--byte", type=lambda x: int(x, 0), default=None,
                    help="byte to transmit. Default 0x55 for uart_tx and 0x47 "
                         "for loopback -- see the notes in the header")
    ap.add_argument("--seconds", type=float, default=0.5,
                    help="seconds per LED toggle")
    ap.add_argument("--period", type=int, default=TIMER_MAX,
                    help="timer period P, in divided-clock cycles")
    ap.add_argument("-o", "--out", default=None)
    a = ap.parse_args()

    f_sys = a.fclk / a.div
    # 0x55 is right for a TX-only test: it alternates, so baud error shows up
    # as visibly wrong characters. It is the WRONG choice once RX is in the
    # loop, because 0x55 bit-reversed is 0xAA, which is also ~0x55 -- so a
    # bit-order fault and an inversion fault produce the SAME wrong byte and
    # cannot be told apart. 0x47 has no such collision: reversed it is 0xE2,
    # complemented 0xB8, shifted 0x8E or 0x23, all distinct from each other
    # and from 0x00 and 0xFF. It also has a run of three identical bits, where
    # baud error accumulates fastest, and it is ASCII 'G', so the same stream
    # is still readable on a terminal.
    byte = a.byte if a.byte is not None else (0x47 if a.program == "loopback"
                                              else 0x55)
    d = build(a.nsm, f_sys, a.program, a.seconds, a.period, a.baud, byte,
              usb_period=a.usb_period)
    i = d["info"]

    if a.program == "blink":
        what = (f"//   timer period P     {d['period']} cycles = "
                f"{d['period'] / f_sys * 1e3:.3f} ms\n"
                f"//   counter 1 reload   {d['cload']} timer ticks\n"
                f"//   LED toggles every  {i['toggle_s']:.3f} s"
                f"  -> {1 / (2 * i['toggle_s']):.3f} Hz blink")
    elif a.program == "usb_loopback":
        what = (f"//   bit cell P         {d['period']} cycles = "
                f"{i['bitrate'] / 1e6:.4f} Mbit/s\n"
                f"//   token              PID 0x{i['pid']:02X}, "
                f"field 0x{i['field']:03X}, CRC5 0x{i['crc5']:02X}\n"
                f"//   machine 0          usb_ls_token_tx, D+ pin {UB_DP_PIN} "
                f"(JA1), D- pin {UB_DM_PIN} (JA2)\n"
                f"//   machine 1          usb_rx, D+ arrives pin {UB_ARRIVE} "
                f"(JB1), decoded bit loops on pin {UB_DEC_PIN} (JB2)\n"
                f"//   host writes        "
                f"{[hex(x) for x in i['wseq']]} -> machine 0\n"
                f"//   host expects       "
                f"{[hex(x) for x in i['rseq']]} <- machine 1")
    elif a.program == "loopback":
        what = (f"//   bit period P       {d['period']} cycles = "
                f"{d['period'] / f_sys * 1e6:.3f} us\n"
                f"//   baud achieved      {i['baud_got']:.2f}"
                f"  ({i['baud_err'] * 100:+.4f}%)\n"
                f"//   byte              0x{i['byte']:02X}, LSB first\n"
                f"//   machine 0          uart_tx  -> pin {i['tx_pin']} "
                f"(uo_out[{i['tx_pin']}], JA{i['tx_pin'] + 1})\n"
                f"//   machine 1          uart_rx  <- pin {i['rx_pin']} "
                f"(uio[{i['rx_pin'] - 8}], JB{i['rx_pin'] - 7}), released "
                f"open-drain\n"
                f"//   host port          dout pin {i['dout_pin']}, "
                f"stb pin {i['stb_pin']}, din pin {i['din_pin']}")
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
    # Host-port driver settings, and how fast the LED should blink. The LED
    # toggles once per 2^LED_BIT correctly received bytes, so the bit is chosen
    # from the byte rate to land near 1.5 Hz whatever the protocol.
    host = i.get("host", dict(wr_en=0, wsel=0, rsel=1,
                              dout_pin=LB_DOUT_PIN, stb_pin=LB_STB_PIN,
                              din_pin=LB_DIN_PIN))
    wseq = i.get("wseq", [0])
    rseq = i.get("rseq", [i.get("byte", 0)])
    if a.program == "usb_loopback":
        byte_rate = i["bitrate"] / 33 * 4        # 4 bytes per 33-bit packet
    elif a.program == "loopback":
        byte_rate = f_sys / d["period"] / 11     # one byte per 11 bit times
    else:
        byte_rate = 0
    # Idle clocks to leave after each packet. The USB receiver needs a run of
    # ones longer than stuffing allows to see end of packet, which takes more
    # than seven bit times; 16 is margin.
    wgap = 16 * d['period'] if a.program == 'usb_loopback' else 0
    led_bit = 8
    if byte_rate > 0:
        import math
        led_bit = max(1, min(31, round(math.log2(max(1.0, byte_rate / 3.0)))))

    body = "\n".join([
        head,
        f"localparam integer STT_ROM_NSM   = {a.nsm};",
        # Emitted so the testbench can assert the bit period without anyone
        # re-typing it. A hand-copied timing constant that disagrees with the
        # ROM is the same class of bug as a hand-copied bit stream.
        f"localparam integer STT_ROM_PERIOD = {d['period']};",
        f"localparam integer STT_ROM_IS_UART = {1 if a.program in ('uart_tx', 'loopback') else 0};",
        f"localparam integer STT_ROM_IS_LOOPBACK = {1 if a.program in ('loopback', 'usb_loopback') else 0};",
        f"localparam integer STT_ROM_IS_USB = {1 if a.program == 'usb_loopback' else 0};",
        # What the host-port driver should do. A program with no host port in
        # its pin plan simply reads rx_ne = 0 for ever, so these are harmless
        # when unused.
        f"localparam integer STT_ROM_HOST_WREN = {host['wr_en']};",
        f"localparam [2:0]   STT_ROM_HOST_WSEL = 3'd{host['wsel']};",
        f"localparam [2:0]   STT_ROM_HOST_RSEL = 3'd{host['rsel']};",
        f"localparam integer STT_ROM_HOST_NW   = {len(wseq)};",
        f"localparam integer STT_ROM_HOST_NR   = {len(rseq)};",
        vh(seq_word(wseq), "STT_ROM_HOST_WSEQ", 8 * len(wseq)),
        vh(seq_word(rseq), "STT_ROM_HOST_RSEQ", 8 * len(rseq)),
        f"localparam integer STT_ROM_HOST_DOUT = {host['dout_pin']};",
        f"localparam [15:0]  STT_ROM_HOST_WGAP = 16'd{wgap};",
        f"localparam integer STT_ROM_LED_BIT   = {led_bit};",
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
    elif a.program == "usb_loopback":
        print(f"  P              {d['period']} cycles per bit "
              f"({i['bitrate'] / 1e6:.4f} Mbit/s)")
        print(f"  token          PID 0x{i['pid']:02X}, field 0x{i['field']:03X}, "
              f"CRC5 0x{i['crc5']:02X}")
        print(f"  host writes    {[hex(x) for x in i['wseq']]} -> machine 0")
        print(f"  host expects   {[hex(x) for x in i['rseq']]} <- machine 1")
        print(f"  D+ pin {UB_DP_PIN} (JA1), D- pin {UB_DM_PIN} (JA2), "
              f"arrives pin {UB_ARRIVE} (JB1), decoded pin {UB_DEC_PIN} (JB2)")
    elif a.program == "loopback":
        print(f"  P              {d['period']} cycles = "
              f"{d['period'] / f_sys * 1e6:.3f} us per bit")
        print(f"  baud           {i['baud_want']} requested, "
              f"{i['baud_got']:.2f} achieved ({i['baud_err'] * 100:+.4f}%)")
        print(f"  byte           0x{i['byte']:02X} "
              f"(reversed 0x{int(format(i['byte'], '08b')[::-1], 2):02X}, "
              f"complement 0x{~i['byte'] & 0xFF:02X})")
        print(f"  machine 0      uart_tx -> pin {i['tx_pin']}")
        print(f"  machine 1      uart_rx <- pin {i['rx_pin']} (open drain, released)")
        print(f"  host port      dout {i['dout_pin']}, stb {i['stb_pin']}, "
              f"din {i['din_pin']}")
    else:
        print(f"  P              {d['period']} cycles = "
              f"{d['period'] / f_sys * 1e6:.3f} us per bit")
        print(f"  baud           {i['baud_want']} requested, "
              f"{i['baud_got']:.2f} achieved ({i['baud_err'] * 100:+.4f}%)")
        print(f"  byte           0x{i['byte']:02X}, LSB first, continuous")
        print(f"  TX             slot 0 -> pin {LB_TX_PIN} "
              f"(uo_out[{LB_TX_PIN}], JA{LB_TX_PIN + 1})")
        print( "  parked         pins 1..15 -> machine 0 slot 2, select code 2")
    print(f"  first 3 words  {[hex(w) for w in d['words'][:3]]}")


if __name__ == "__main__":
    main()
