"""EXPERIMENT -- not part of the conformance set.

Does a UART detector plus enough decoding to be useful fit in 32 rows?

A detector watches a pin it does not drive and decides whether the traffic on it
is UART. It does not recover bytes; it confirms a signature:

    a falling edge, the line still low half a bit later (so not a glitch),
    8 bit times, and a stop bit high where one belongs -- N times in a row.

BAUD IS ASSUMED, NOT MEASURED. The timer period P is preconfigured to a
candidate baud and this confirms or rejects that hypothesis. Several machines
each testing a different candidate is what makes that reasonable. What an
auto-baud version would additionally need is in DETECTOR_NOTES.md.

Requiring N CONSECUTIVE good frames is what separates a detector from a
receiver. One well-formed frame can happen by accident on random traffic; three
in a row, at the same assumed baud, is a signature.
"""
import io
import contextlib

with contextlib.redirect_stdout(io.StringIO()):
    from stt import Row, SttProgram, SttCore

# Consecutive well-formed frames required before the signature is called.
# This is CONFIGURATION, not rows -- raising it costs nothing in the 32-row
# budget. Each frame passes random traffic with p ~ 0.25 (start still low at
# mid-bit, stop high), so 3 in a row is ~1.6% per attempt and a few hundred
# attempts produce false positives; measured, 3 gave 1 hit on 200 frames of
# random toggling. At 8 it is 0.25**8 ~ 1.5e-5.
FRAMES_TO_CONFIRM = 8


def stt_uart_detect(P):
    prog = SttProgram([
        # Entry. Loads the frame counter once; BAD returns here to reset it.
        Row("ARM",    "always", "IDLE",           act=["c2load"]),
        # Wait for a falling edge, then aim the timer at the middle of the
        # start bit. thalf only takes effect on a passing row (SPEC 8.4).
        Row("IDLE",   "in0l",   "MID",            act=["thalf"]),
        Row("MID",    "tmr",    "CHKST"),
        # Still low at mid-bit: a real start bit, not a glitch. cload arms the
        # bit counter for the 8 data bits.
        Row("CHKST",  "in0l",   "BITS", "IDLE",   act=["cload"]),
        Row("BITS",   "tmr",    "CNT",            act=["shift", "cdec"]),
        Row("CNT",    "cz",     "STOP", "BITS"),
        Row("STOP",   "tmr",    "STOPCK"),
        # Stop bit must be high. If it is, that frame was well formed.
        Row("STOPCK", "in0h",   "GOOD", "BAD"),
        Row("GOOD",   "always", "CHK",            act=["c2dec"]),
        Row("CHK",    "c2z",    "HIT",  "IDLE"),
        # Signature confirmed. Pushing the shift register both signals the
        # detection and hands the host the byte that confirmed it.
        Row("HIT",    "always", "IDLE",           act=["push"]),
        # Malformed frame: resync to idle-high, then start counting again.
        Row("BAD",    "in0h",   "ARM"),
    ])
    core = SttCore(prog, slots=[], ins=["rx"], period=P, shift="right",
                   fill="in0", c2load=FRAMES_TO_CONFIRM)
    return core, prog


if __name__ == "__main__":
    import sys
    from rowformat import Format
    core, prog = stt_uart_detect(32)
    res = Format("single5", "grouped", tgt_bits=8).encode(prog)
    print(f"source rows          : {len(prog.rows)}")
    print(f"encoded rows         : {res['rows']}  (trampolines: "
          f"{res['rows'] - len(prog.rows)})")
    print(f"row width            : {res['row_width']} bits")
    print(f"program bits         : {res['bits']}")
    print(f"rows remaining of 32 : {32 - res['rows']}")


# ---------------------------------------------------------------- negatives
class ConstDriver:
    """Holds a line at a fixed level."""

    def __init__(self, net, level):
        self.net, self.level = net, level

    def step(self, w):
        w.nets[self.net].drive("const", self.level)


class TogglerDriver:
    """Pseudo-random level changes on a fixed grid.

    Structurally unlike UART: edges anywhere, no start/stop framing, and no
    relationship to the assumed baud. Seeded, so the run is reproducible.
    """

    def __init__(self, net, period, seed=1234, t0=40, phase=0.0):
        import random
        rng = random.Random(seed)
        self.net, self.t0 = net, t0 + int(round(phase))
        self.grid = period
        self.bits = [rng.randrange(2) for _ in range(4000)]

    def step(self, w):
        if w.t < self.t0:
            w.nets[self.net].drive("tog", 1)
        else:
            w.nets[self.net].drive("tog", self.bits[((w.t - self.t0) // self.grid)
                                                    % len(self.bits)])


class SquareDriver:
    """A clock-like square wave, as an SPI SCK line would look.

    Every 'frame' the detector might hypothesise is the same length, so unlike
    random traffic this is regular -- but it has no start bit, no stop bit and
    no idle level, which is exactly what the signature tests for.
    """

    def __init__(self, net, half, t0=40, phase=0.0):
        self.net, self.half, self.t0 = net, half, t0 + int(round(phase))

    def step(self, w):
        if w.t < self.t0:
            w.nets[self.net].drive("sq", 1)
        else:
            w.nets[self.net].drive("sq", ((w.t - self.t0) // self.half) % 2)


def run_detect(kind, P=32, prog_override=None, phase=0.0, jitter=0.0, seed=None):
    """Build a world of the given kind and run the detector on it.

    Returns (detections, cycles, errors).
    """
    with contextlib.redirect_stdout(io.StringIO()):
        from world import World
        from devices import UartDriver

    core, prog = stt_uart_detect(P)
    if prog_override is not None:
        core.p, core.row = prog_override, 0
    w = World([("rx", 1)])

    if kind == "uart":
        # Enough good frames to satisfy FRAMES_TO_CONFIRM with margin.
        frames = [(b, True) for b in
                  (0x55, 0xC3, 0x00, 0xFF, 0xA5, 0x3C, 0x0F, 0xF0,
                   0x81, 0x7E, 0x01, 0x80)]
        drv = UartDriver("rx", P, frames, phase=phase, jitter=jitter, seed=seed)
        w.devices = [drv]
        limit = drv.end + 8 * P
    elif kind == "uart_skew":
        # Real UART at a baud ~3%% fast against the detector's hypothesis. A
        # receiver sampling at MID-BIT tolerates this: 3%% over 10 bits is 0.3
        # of a bit, inside the +/-0.5 margin. One sampling at bit EDGES does not.
        # Without a case like this nothing tests the `thalf` alignment at all --
        # mutation showed dropping thalf survived every other case.
        frames = [(b, True) for b in
                  (0x55, 0xC3, 0x00, 0xFF, 0xA5, 0x3C, 0x0F, 0xF0,
                   0x81, 0x7E, 0x01, 0x80)]
        drv = UartDriver("rx", (P * 33) // 32, frames, phase=phase,
                         jitter=jitter, seed=seed)
        w.devices = [drv]
        limit = drv.end + 8 * P
    elif kind == "uart_badstop":
        # Well-formed edges but every stop bit wrong: the line is UART-shaped
        # and still must be rejected, which is the sharpest negative.
        frames = [(b, False) for b in
                  (0x55, 0xC3, 0x00, 0xFF, 0xA5, 0x3C, 0x0F, 0xF0,
                   0x81, 0x7E, 0x01, 0x80)]
        drv = UartDriver("rx", P, frames, phase=phase, jitter=jitter, seed=seed)
        w.devices = [drv]
        limit = drv.end + 8 * P
    elif kind == "high":
        w.devices = [ConstDriver("rx", 1)]
        limit = 60 * P
    elif kind == "low":
        w.devices = [ConstDriver("rx", 0)]
        limit = 60 * P
    elif kind == "random":
        w.devices = [TogglerDriver("rx", P, phase=phase)]
        limit = 200 * P
    elif kind == "square":
        # Deliberately NOT at the candidate baud: an SPI clock has no reason to
        # match the baud a detector is hypothesising. See "square_aligned".
        w.devices = [SquareDriver("rx", (P * 2) // 3, phase=phase)]
        limit = 200 * P
    elif kind == "square_aligned":
        # A square wave at EXACTLY the candidate baud. This is expected to be
        # detected, and that is correct: low for bit 0, alternating 1,0,1,0,
        # 1,0,1,0 across the data bits, high at bit 9 -- a well-formed frame
        # carrying 0x55, repeating forever. A real UART receiver would decode it
        # as 0x55 and be right. The ambiguity is in the signal, not the detector.
        w.devices = [SquareDriver("rx", P, phase=phase)]
        limit = 200 * P
    else:
        raise ValueError(kind)

    w.run(core, limit, lambda _w: False)
    w.errors = [e for e in w.errors if "timeout" not in e]
    return len(w.rx_fifo), limit, w.errors


# ------------------------------------------------------- conformance harness
CASES = [("uart", True), ("uart_skew", True), ("uart_badstop", False),
         ("high", False), ("low", False), ("random", False),
         ("square", False), ("square_aligned", True)]


# SPEC §16.2. The device models used to drive every waveform from a fixed start
# on an integer-cycle grid, so the detector's timer and the traffic it saw were
# in a deterministic phase relationship BY CONSTRUCTION. Sweeping the phase over
# a whole bit period is what makes mid-bit alignment load-bearing rather than
# lucky: without it, dropping `thalf` survived every case.
PHASES = (0.0, 0.17, 0.33, 0.5, 0.67, 0.83)


def check_all(prog_override=None, P=32, phases=PHASES, jitter=0.0):
    """True if the detector gets every case right at every phase."""
    for kind, want in CASES:
        # Every kind, including the negatives: a detector that rejects noise
        # at one alignment and accepts it at another is not rejecting it.
        for frac in phases:
            try:
                n, _, errs = run_detect(kind, P, prog_override=prog_override,
                                        phase=frac * P, jitter=jitter,
                                        seed=int(frac * 1000) + 1)
            except Exception:
                return False      # a crash is a catch, not a survival
            if (n > 0) != want or errs:
                return False
    return True


def register():
    """Expose the positive case as a benchmark so the rtl2 lockstep can run it.

    EXPERIMENT ONLY. This adds an entry to bench.BENCHES; it does not touch any
    reference program and is not part of the conformance set.
    """
    with contextlib.redirect_stdout(io.StringIO()):
        import bench

    def _run(isa, P):
        core, prog = stt_uart_detect(P)
        from devices import UartDriver
        from world import World
        w = World([("rx", 1)])
        drv = UartDriver("rx", P, [(b, True) for b in
                                   (0x55, 0xC3, 0x00, 0xFF, 0xA5, 0x3C,
                                    0x0F, 0xF0, 0x81, 0x7E, 0x01, 0x80)])
        w.devices = [drv]
        w.run(core, drv.end + 8 * P, lambda _w: False)
        return prog, None

    bench.BENCHES["uart_detect"] = _run
