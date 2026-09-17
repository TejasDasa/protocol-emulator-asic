"""Cycle-exact lockstep between rtl2 and the authoritative Python models.

SPEC section 0: where the models and the RTL disagree, the models win. So this
does not check the RTL against a hand-written expectation; it steps `SttCore`
and the RTL together and compares the whole architectural state on EVERY cycle.
The first cycle they differ fails the test and names the field.

The world, the devices, the payloads and the termination condition all come
from `isa_bench/bench.py` itself rather than being re-specified here: `World.run`
is monkeypatched to stash its arguments instead of running, the benchmark is
called to build everything, and the loop below then drives both the model and
the RTL. That way the testbench cannot drift from the benchmark it claims to
mirror.

The RTL is a shadow: the MODEL drives the world's nets, and the RTL is checked
against the model each cycle. It is not co-simulation, which is the point -- any
divergence is a divergence, not a feedback loop that hides one.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "isa_bench"))

# --- configuration bit map. Mirrors rtl2/stt_config.v; changing one without the
# --- other is exactly the drift this comment exists to make obvious.
TIMER_W, SR_W, CNT_W, NSLOT = 16, 8, 8, 3
O_PERIOD = 0
O_SHIFT  = O_PERIOD + TIMER_W
O_FILL   = O_SHIFT + 1
O_SRW    = O_FILL + 2
O_CA     = O_SRW + 4
O_CB     = O_CA + CNT_W
O_CC     = O_CB + CNT_W
O_C2     = O_CC + CNT_W
O_K      = O_C2 + CNT_W
O_INIT   = O_K + SR_W
O_OD     = O_INIT + NSLOT
# SPEC section 9 wider units, appended (see stt_config.v).
O_C16P   = O_OD + NSLOT
O_C16W   = O_C16P + 16
O_C16R   = O_C16W + 5
O_C16S   = O_C16R + 1
O_STN    = O_C16S + 1
O_STO    = O_STN + 4
O_STS    = O_STO + 1
CFG_BITS = O_STS + NSLOT

FILL_CODE = {"0": 0, "1": 1, "in0": 2}


def config_word(core):
    """Pack an SttCore's configuration the way stt_config.v unpacks it."""
    v = 0
    def put(off, width, val):
        nonlocal v
        assert 0 <= val < (1 << width), (off, width, val)
        v |= val << off
    put(O_PERIOD, TIMER_W, core.P)
    put(O_SHIFT, 1, 1 if core.shift == "left" else 0)
    put(O_FILL, 2, FILL_CODE[core.fill])
    put(O_SRW, 4, core.w)
    put(O_CA, CNT_W, core.cvals[0])
    put(O_CB, CNT_W, core.cvals[1])
    put(O_CC, CNT_W, core.cvals[2])
    put(O_C2, CNT_W, core.c2val)
    put(O_K, SR_W, core.k)
    init = 0
    for i, b in enumerate(core.pinv):
        init |= (b & 1) << i
    put(O_INIT, NSLOT, init)
    od = 0
    for i, (_net, mode) in enumerate(core.slots):
        if mode == "od":
            od |= 1 << i
    put(O_OD, NSLOT, od)
    put(O_C16P, 16, core.crc16_poly)
    put(O_C16W, 5, core.crc16_w)
    put(O_C16R, 1, 1 if core.crc16_reflect else 0)
    put(O_C16S, 1, 1 if core.crc16_seed_ones else 0)
    put(O_STN, 4, core.stuff_n)
    put(O_STO, 1, 1 if core.stuff_ones else 0)
    stuff = 0
    for i in core.stuff_slots:
        stuff |= 1 << i
    put(O_STS, NSLOT, stuff)
    return v


def capture_benchmark(name, period):
    """Build the benchmark's world without running it.

    Returns (core, prog, world, max_cycles, done). Patching World.run is what
    lets the payloads, device models and stop condition come from bench.py
    unchanged.
    """
    import world as W
    import bench
    import jtag_bench
    import jtag_prog
    import programs as P

    # EXPERIMENT: registers the UART detector as a benchmark if it is present.
    # Additive -- it touches no reference program and is not conformance.
    try:
        import detector
        detector.register()
    except ImportError:
        pass
    try:
        import can_prog
        can_prog.register()
    except Exception:
        pass

    stash = {}
    real_run = W.World.run

    def fake_run(self, core, max_cycles, done):
        stash.update(world=self, core=core, max_cycles=max_cycles, done=done)
        return True

    W.World.run = fake_run
    try:
        if name == "jtag":
            jtag_bench.run_jtag(period)
        else:
            # SPEC section 7 allows one pin write per row, so the reference
            # programs are the single-pin-write variants (SPEC section 13).
            saved = dict(P.BUILDERS["STT"])
            P.BUILDERS["STT"].update(P.STT_1PIN)
            try:
                bench.BENCHES[name]("STT", period)
            finally:
                P.BUILDERS["STT"].update(saved)
    finally:
        W.World.run = real_run

    if not stash:
        raise RuntimeError(f"benchmark {name} never called World.run")
    return stash


def encode_rows(prog):
    """The frozen 32-bit encoding, from the same encoder SPEC section 13 uses."""
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        from rowformat import Format
    res = Format("single5", "grouped", tgt_bits=8).encode(prog)
    assert res["row_width"] == 32, res["row_width"]
    return list(res["packed"]), res["decoded"]
