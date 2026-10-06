"""Gate: the I2C target RESPONDS, and responds inside the master's window.

Every other program in isa_bench either drives a bus or watches one. This is
the first that has to meet a deadline somebody else sets: the ACK must be on
SDA before the master's ninth rising edge. So the interesting assertion is not
"the byte arrived" -- it is "the byte arrived in time", and the two are easy to
confuse. A target that ACKs one cycle before the rising edge carries exactly
the same data as one that ACKs immediately.

Checked in both directions. The last check breaks the target on purpose, by
inserting dead rows between the falling edge and the drive, and requires the
timing assertion to fail. Without that, a lenient model would let a late ACK
pass and the gate would be measuring nothing.

    python3 isa_bench/i2c_target_check.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from devices import I2cController           # noqa: E402
from programs import stt_i2c_target, stt_i2c  # noqa: E402
from mutlib import mutants                   # noqa: E402
from rowformat import Format                # noqa: E402
from stt import Row, SttCore, SttProgram     # noqa: E402
from world import World                      # noqa: E402

ADDR = 0x42
SYNC = 2            # SPEC section 8.3 input synchronizer, in core clocks
MIN_PERIOD = 8      # measured below, not assumed


def build(P, addr=ADDR, rows=None):
    core, prog = stt_i2c_target(P, addr=addr)
    if rows is not None:
        prog = SttProgram(rows)
        core = SttCore(prog, slots=core.slots, ins=core.ins, period=core.P,
                       shift=core.shift, fill=core.fill, loadk=core.k,
                       cload=core.cvals, c2load=core.c2val, init_pins=[1])
    return core, prog


def run(P, txns, queue=(), addr=ADDR, rows=None, setup_min=1):
    core, prog = build(P, addr=addr, rows=rows)
    w = World([("sda", 1), ("scl", 1)])
    ctl = I2cController("sda", "scl", P, txns, setup_min=setup_min)
    w.devices = [ctl]
    w.tx_fifo.extend(queue)
    w.run(core, 400 * P + 6000, lambda w: ctl.finished(w))
    return ctl, w, prog


class FifoView:
    """A second core in the same World needs its own host queues.

    The master pops the bytes it sends and pushes its status; the target pushes
    what it received. Sharing one pair of FIFOs would mix the two streams and
    make the machine-to-machine result unreadable. Nets stay shared -- that is
    the point -- and everything else delegates.
    """

    def __init__(self, w):
        self._w = w
        self.tx_fifo = __import__("collections").deque()
        self.rx_fifo = []

    def __getattr__(self, k):
        return getattr(self._w, k)


class CoreDevice:
    """Run a second STT core as a World device, so two machines share the bus."""

    def __init__(self, core, view):
        self.core, self.view = core, view

    def step(self, w):
        self.core.step(self.view)


def target_ok(rows_prog):
    """The full oracle, used to decide whether a mutant survived.

    A mutant that still carries the byte but ACKs a cycle late, or ACKs an
    address that is not ours, has changed the target's behaviour and must be
    counted as killed. Checking only "the byte arrived" would let both through.
    """
    rows = list(rows_prog.rows)
    try:
        ctl, w, _ = run(16, [{"addr": ADDR, "rw": 0, "data": 0x5A}], rows=rows)
        if not (all(a["acked"] for a in ctl.acks)
                and [v & 0xFF for v in w.rx_fifo] == [0x5A]
                and all(a["latency"] == SYNC for a in ctl.acks)
                and not w.errors):
            return False
        ctl, w, _ = run(16, [{"addr": ADDR, "rw": 1}], queue=[0xA7], rows=rows)
        if not (ctl.acks[0]["acked"] and ctl.read_bytes == [0xA7] and not w.errors):
            return False
        ctl, w, _ = run(16, [{"addr": 0x21, "rw": 0, "data": 0x5A}], rows=rows)
        if any(a["acked"] for a in ctl.acks) or w.rx_fifo:
            return False
        # Back to back. A single transaction never exercises the return to
        # idle, so every corruption of the last rows and of the START detector
        # survived until this case was added -- the rows were in the program
        # but not in the test.
        ctl, w, _ = run(16, [{"addr": ADDR, "rw": 0, "data": 0x11},
                             {"addr": 0x21, "rw": 0, "data": 0x22},
                             {"addr": ADDR, "rw": 0, "data": 0x33}], rows=rows)
        if ([v & 0xFF for v in w.rx_fifo] != [0x11, 0x33] or w.errors
                or [a["acked"] for a in ctl.acks] != [True, True, False, False,
                                                      True, True]):
            return False
        # A read must also leave the target able to answer the next write.
        ctl, w, _ = run(16, [{"addr": ADDR, "rw": 1},
                             {"addr": ADDR, "rw": 0, "data": 0x7E}],
                        queue=[0xA7], rows=rows)
        return (ctl.read_bytes == [0xA7] and [v & 0xFF for v in w.rx_fifo] == [0x7E]
                and not w.errors)
    except Exception:
        return False        # a crash is a catch, not a survival


def main():
    fails = []

    def check(ok, msg):
        print(("  ok   " if ok else "  FAIL ") + msg)
        if not ok:
            fails.append(msg)

    # ---------------------------------------------------------- 1. row budget
    _, prog = build(16)
    src = len(prog.rows)
    # The number that matters is what the ENCODER emits, not what the source
    # lists. best_order inserts a trampoline row wherever a row's two exits
    # cannot both be reached without one, so the encoded program can be longer
    # than the row list. Taking the source count would under-report the cost
    # against the ceiling by exactly those rows.
    enc = Format("single5", "grouped", tgt_bits=8).encode(prog)
    n = enc["rows"]
    print(f"I2C target: {src} rows written, {n} rows encoded "
          f"({n - src} trampoline) of the 32-row ceiling (SPEC section 10)")
    check(enc["row_width"] == 32, f"encodes at 32 bits a row ({enc['row_width']})")
    check(n <= 32, f"fits the ceiling ({n} <= 32, {32 - n} to spare)")

    # ------------------------------------------------- 2. the latency question
    print("\nResponse latency, from the master's eighth falling edge to SDA low:")
    lat = {}
    for P in (8, 16, 64, 256):
        ctl, w, _ = run(P, [{"addr": ADDR, "rw": 0, "data": 0x5A}])
        a, d = ctl.acks[0], ctl.acks[1]
        lat[P] = (a["latency"], a["setup"], d["latency"])
        print(f"    SCL period {P:>4} cycles: address ACK {a['latency']} cycles "
              f"(setup {a['setup']}), data ACK {d['latency']} cycles")
    check(all(v[0] == SYNC and v[2] == SYNC for v in lat.values()),
          f"latency is the synchronizer depth ({SYNC}) at every period, "
          "and does not grow with SCL rate")

    # --------------------------------------------------------- 3. the protocol
    print("\nTransactions:")
    ctl, w, _ = run(16, [{"addr": ADDR, "rw": 0, "data": 0x5A}])
    check(all(a["acked"] for a in ctl.acks) and [v & 0xFF for v in w.rx_fifo] == [0x5A]
          and not w.errors, "write to our address: both ACKs, byte 0x5A delivered")

    ctl, w, _ = run(16, [{"addr": ADDR, "rw": 1}], queue=[0xA7])
    check(ctl.acks[0]["acked"] and ctl.read_bytes == [0xA7] and not w.errors,
          "read from our address: address ACKed, 0xA7 driven back")

    ctl, w, _ = run(16, [{"addr": 0x21, "rw": 0, "data": 0x5A}])
    check(not any(a["acked"] for a in ctl.acks) and not w.rx_fifo and not w.errors,
          "foreign address: NACKed, nothing delivered, SDA never pulled")

    ctl, w, _ = run(16, [{"addr": ADDR, "rw": 0, "data": 0x11},
                         {"addr": 0x21, "rw": 0, "data": 0x22},
                         {"addr": ADDR, "rw": 0, "data": 0x33}])
    got = [v & 0xFF for v in w.rx_fifo]
    check(got == [0x11, 0x33] and not w.errors,
          "three transactions: STOP returns to idle, the foreign one is skipped")

    # ------------------------------------------------------ 4. the rate limit
    print("\nMinimum SCL period (the target must see both edges of every clock):")
    worked = []
    for P in (6, 8, 10, 12):
        ctl, w, _ = run(P, [{"addr": ADDR, "rw": 0, "data": 0x5A}])
        good = (all(a["acked"] for a in ctl.acks)
                and [v & 0xFF for v in w.rx_fifo] == [0x5A] and not w.errors)
        worked.append((P, good))
        print(f"    period {P:>3} cycles (half {P // 2:>2}): "
              f"{'works' if good else 'FAILS -- loses a bit'}")
    check(dict(worked).get(MIN_PERIOD) and not dict(worked).get(MIN_PERIOD - 2),
          f"minimum SCL period is {MIN_PERIOD} core cycles, "
          f"and {MIN_PERIOD - 2} genuinely fails")

    # --------------------------------- 5. negative test: a late ACK must fail
    print("\nNegative test -- a target that ACKs late must be caught:")
    def delayed(n_dead):
        """The same target with n_dead rows between the falling edge and SDA."""
        _, base = build(8)
        rows = list(base.rows)
        i = next(i for i, r in enumerate(rows) if r.name == "WRA")
        rows[i] = Row("WRA", "in1l", "DLY0", "WRA")
        for k in range(n_dead):
            last = (k == n_dead - 1)
            rows.append(Row(f"DLY{k}", "always", "WRB" if last else f"DLY{k+1}",
                            pins={0: "lo"} if last else None))
        return rows

    # One dead row: the ACK still lands before the rising edge, but with a
    # single cycle of setup. This is the case a lenient model would pass, so
    # demand two cycles and require the window check to fire.
    ctl, w, _ = run(8, [{"addr": ADDR, "rw": 0, "data": 0x5A}],
                    rows=delayed(1), setup_min=2)
    one = ctl.acks[0]
    print(f"    +1 row: latency {one['latency']}, setup {one['setup']}, "
          f"master saw the ACK: {one['acked']}, errors: {len(w.errors)}")
    check(one["latency"] == SYNC + 1 and one["acked"] and bool(w.errors),
          "one extra row costs one cycle of setup, and the window check fires")

    # Two dead rows: the ACK reaches SDA on the rising edge itself, so the
    # master never samples it. Late enough stops being a margin problem and
    # becomes a missing ACK.
    ctl, w, _ = run(8, [{"addr": ADDR, "rw": 0, "data": 0x5A}], rows=delayed(2))
    two = ctl.acks[0]
    print(f"    +2 rows: latency {two['latency']}, "
          f"master saw the ACK: {two['acked']}")
    check(two["acked"] is False,
          "two extra rows miss the window entirely -- the master sees no ACK")

    # ------------------------------- 6. master and target, machine to machine
    print("\nOur I2C master against our I2C target, two machines on one bus:")
    MP = 64
    mcore, _ = stt_i2c(MP)
    tcore, _ = build(MP)
    # Both cores default to the driver name "stt". On a shared net that is one
    # driver key, so each would overwrite the other's value and the bus would
    # show whichever stepped last.
    tcore.name = "stt_target"
    w = World([("sda", 1), ("scl", 1)])
    tview = FifoView(w)
    w.devices = [CoreDevice(tcore, tview)]
    w.tx_fifo.extend([(ADDR << 1) | 0, 0x5A])      # master: address, then data
    w.run(mcore, 600 * MP, lambda w: len(w.rx_fifo) >= 1 and tview.rx_fifo)
    status = [v & 0xFF for v in w.rx_fifo]
    heard = [v & 0xFF for v in tview.rx_fifo]
    print(f"    master status {status}, target received {[hex(v) for v in heard]}, "
          f"errors {w.errors[:2]}")
    check(heard == [0x5A] and status and status[0] == 0 and not w.errors,
          "the master's own ACK check passed and the target got the byte")

    # --------------------------------------------- 7. mutation coverage
    # The oracle is the whole transaction set, not one byte: a corrupted target
    # has to still ACK in time, deliver the right byte, drive the right byte
    # back, and still refuse an address that is not its own.
    print("\nMutation coverage -- every corruption must be caught:")
    _, clean = build(16)
    killed = {}
    survivors = []
    for cls, desc, mprog in mutants(clean):
        k = killed.setdefault(cls, [0, 0])
        k[1] += 1
        if target_ok(mprog):
            survivors.append(f"{cls:9} {desc}")
        else:
            k[0] += 1
    sem = [(c, v) for c, v in killed.items() if c != "swap"]
    tot_k = sum(v[0] for _, v in sem)
    tot_n = sum(v[1] for _, v in sem)
    for c, v in sorted(sem):
        print(f"    {c:9} killed {v[0]:>3}/{v[1]:<3} ({100.0 * v[0] / v[1]:.0f}%)")
    sw = killed.get("swap", [0, 0])
    rate = 100.0 * tot_k / max(tot_n, 1)
    print(f"    {'TOTAL':9} killed {tot_k:>3}/{tot_n:<3} ({rate:.1f}%)   "
          f"[swap, reported separately: {sw[0]}/{sw[1]}]")
    if survivors:
        print("    survivors (the vectors do not exercise these):")
        for s in survivors[:12]:
            print(f"      {s}")
        if len(survivors) > 12:
            print(f"      ... and {len(survivors) - 12} more")
    check(rate >= 85.0, f"semantic kill rate {rate:.1f}% >= 85%")

    print()
    if fails:
        print(f"FAIL: {len(fails)} check(s) failed")
        return 1
    print("OK: the I2C target responds, and responds inside the window")
    return 0


if __name__ == "__main__":
    sys.exit(main())
