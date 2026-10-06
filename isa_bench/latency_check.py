"""The minimum response latency of this architecture, measured.

The question this answers: how many core clock cycles from an externally driven
edge to a driven output? It is the number that decides whether this design can
act as a test peer for anything -- I2C target, SPI target, USB device -- and it
generalises past any one protocol, so it is measured on its own rather than
inferred from a protocol program that happens to pass.

The probe is the smallest program that can respond at all: one row waits on a
falling edge and drives a pin, with a configurable number of dead rows inserted
between seeing the edge and driving. Reading the result off the recorded net
history gives the cycle the BUS changed, which is the honest reference -- a
device model sampling at the top of its own step would read one cycle later,
because devices step before the core.

Expected shape:  latency = SYNC + (rows between detection and drive),
with SYNC = 2, the input synchronizer of SPEC section 8.3.

    python3 isa_bench/latency_check.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from stt import Row, SttCore, SttProgram      # noqa: E402
from world import World                       # noqa: E402

SYNC = 2
EDGE_AT = 20


class EdgeAt:
    """Pull `scl` low once, at a known cycle, and leave it there."""

    def __init__(self, t_edge):
        self.t_edge, self.fired = t_edge, False

    def step(self, w):
        if w.t >= self.t_edge and not self.fired:
            w.nets["scl"].drive("drv", 0)
            self.fired = True


def probe(dead_rows):
    """Latency in cycles with `dead_rows` rows between detection and drive."""
    first_target = "D0" if dead_rows else "HOLD"
    rows = [Row("W", "in1l", first_target, "W",
                pins=None if dead_rows else {0: "lo"})]
    for i in range(dead_rows):
        last = (i == dead_rows - 1)
        rows.append(Row(f"D{i}", "always", "HOLD" if last else f"D{i + 1}",
                        pins={0: "lo"} if last else None))
    rows.append(Row("HOLD", "always", "HOLD"))

    core = SttCore(SttProgram(rows), slots=[("sda", "od"), ("scl", "od")],
                   ins=["sda", "scl"], period=8, shift="left", fill="0",
                   init_pins=[1, 1])
    w = World([("sda", 1), ("scl", 1)])
    w.devices = [EdgeAt(EDGE_AT)]
    w.run(core, 120, lambda w: False)

    scl, sda = w.history["scl"], w.history["sda"]
    t_fall = next(i for i, v in enumerate(scl) if v == 0)
    t_drive = next((i for i, v in enumerate(sda) if v == 0), None)
    if t_drive is None:
        return None
    return t_drive - t_fall


def main():
    print("Minimum response latency, externally driven edge -> driven output")
    print(f"(input synchronizer depth {SYNC}, SPEC section 8.3; one row per cycle)\n")
    print(f"  {'rows after detection':>22}   {'latency':>7}")
    bad = []
    for n in range(4):
        lat = probe(n)
        want = SYNC + n
        mark = "" if lat == want else f"   <-- expected {want}"
        if lat != want:
            bad.append(n)
        print(f"  {n:>22}   {str(lat):>7} cycles{mark}")

    floor = probe(0)
    print(f"\n  floor = {floor} cycles, reached when one row both tests the edge")
    print("  and drives the pin -- which requires the decision to be already made.")
    if bad:
        print(f"\nFAIL: latency did not follow SYNC + rows at {bad}")
        return 1
    print(f"\nOK: latency is {SYNC} + (rows between detection and drive)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
