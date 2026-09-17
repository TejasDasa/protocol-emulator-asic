"""Random 32-row programs in lockstep: the decode paths nothing else reaches.

Mutation reaches 100% of individual field values but only combinations near the
six programs somebody wrote, and it structurally cannot reach `next` wrapping
from row 31 (SPEC section 5) because no reference program has 32 rows and
mutation does not add rows. These programs do.
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cocotb
from cocotb.clock import Clock

from coverage_util import CodeCoverage
from steps import PERIOD_NS, Divergence, reset_and_load, run_lockstep
from randprog import decode, random_words

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "isa_bench")))
from world import World
from stt import SttCore

OUTS = ["o0", "o1", "o2"]
INS = ["i0", "i1"]


class RandomStimulus:
    """Wiggles the input pins and keeps the TX FIFO sometimes empty.

    Sometimes empty on purpose: `load` from an empty FIFO is unspecified
    (SPEC section 16.1) and is where the mutation suite found the one real RTL
    bug, so it should stay under test rather than be arranged away.
    """

    def __init__(self, rng):
        self.rng = rng

    def step(self, w):
        for n in INS:
            if self.rng.random() < 0.15:
                w.nets[n].drive("stim", self.rng.randrange(2))
        if self.rng.random() < 0.10:
            w.tx_fifo.append(self.rng.randrange(256))


def build(seed):
    rng = random.Random(seed)
    words = random_words(rng)
    prog = decode(words)
    w = World([(n, 0) for n in OUTS] + [(n, 1) for n in INS])
    w.devices = [RandomStimulus(rng)]
    for _ in range(rng.randrange(1, 6)):
        w.tx_fifo.append(rng.randrange(256))
    core = SttCore(
        prog,
        slots=[(n, "pp") for n in OUTS],
        ins=list(INS),
        period=rng.choice([2, 3, 4, 8, 16]),
        shift=rng.choice(["left", "right"]),
        fill=rng.choice(["0", "1", "in0"]),
        sr_width=8,
        cload=(rng.randrange(256), rng.randrange(256), rng.randrange(256)),
        c2load=rng.randrange(256),
        loadk=rng.randrange(256),
        init_pins=[rng.randrange(2) for _ in OUTS],
    )
    return core, prog, w, words


@cocotb.test()
async def random_lockstep(dut):
    n = int(os.environ.get("RAND_N", "40"))
    cycles = int(os.environ.get("RAND_CYCLES", "400"))
    seed0 = int(os.environ.get("RAND_SEED", "20260916"))

    cocotb.start_soon(Clock(dut.clk, PERIOD_NS, unit="ns").start())
    cov = CodeCoverage()
    diverged = []
    ran = 0

    for k in range(n):
        seed = seed0 + k
        core, prog, w, words = build(seed)
        await reset_and_load(dut, core, words, w)
        try:
            c, _ = await run_lockstep(dut, core, w, lambda _w: False, cycles,
                                      f"random/seed={seed}", len(core.slots),
                                      words, cov=cov)
            ran += 1
            if 31 in {int(x) for x in cov.seen.get("__rows", set())}:
                pass
        except Divergence as d:
            diverged.append(str(d))
            dut._log.error(str(d))
        except Exception as e:
            dut._log.info(f"random/seed={seed}: model raised "
                          f"{type(e).__name__}: {e}; not comparable, skipped")

    hit, capn = cov.summary()
    dut._log.info(f"random programs run in lockstep: {ran}/{n}, "
                  f"{cycles} cycles each, 32 rows each")
    dut._log.info(f"  executed code coverage: {hit}/{capn} = {100.0*hit/capn:.1f}%  "
                  f"missing={cov.missing() or 'none'}")
    dut._log.info(f"  RTL/model divergences: {len(diverged)}")

    assert ran > 0, "no random programs were comparable"
    if diverged:
        raise AssertionError(
            f"{len(diverged)} random program(s) made the RTL and the model "
            f"disagree.\n" + "\n".join(diverged[:3]))
