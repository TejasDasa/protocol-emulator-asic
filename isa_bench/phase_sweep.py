"""Does the REFERENCE uart_rx program survive arbitrary edge phase and jitter?

The detector was the case that exposed the gap, but it is an experiment. This
asks the same question of a conformance program, which is where it matters:
every timing result in the repository was measured with the driver starting at
a fixed cycle on an integer grid, so a program could depend on that alignment
without anyone noticing.
"""
import contextlib
import io
import sys

with contextlib.redirect_stdout(io.StringIO()):
    from world import World
    from devices import UartDriver
    import programs as P

FRAMES = [(0x55, True), (0xC3, True), (0x7E, False), (0x00, True), (0xFF, True),
          (0x81, True), (0x01, True)]
WANT = [b for b, good in FRAMES if good]


def run(period, phase, jitter, seed):
    core, _prog = P.STT_1PIN["uart_rx"](period)
    w = World([("rx", 1)])
    drv = UartDriver("rx", period, FRAMES, phase=phase, jitter=jitter, seed=seed)
    w.devices = [drv]
    w.run(core, drv.end + 4 * period, lambda _w: False)
    got = [v & 0xFF for v in w.rx_fifo]
    errs = [e for e in w.errors if "timeout" not in e]
    return got == WANT and not errs, got


def main():
    period = 32
    ok = True

    print(f"  uart_rx at P={period}, phase swept over a whole bit period:")
    bad = []
    for k in range(16):
        frac = k / 16.0
        good, got = run(period, frac * period, 0.0, None)
        if not good:
            bad.append((frac, got))
    print(f"    {16 - len(bad)}/16 phases decode correctly")
    for frac, got in bad[:4]:
        print(f"      FAIL phase {frac:.3f}P: got {[hex(b) for b in got]}")
    ok &= not bad

    # Push jitter until it breaks, because "passed everything I tried" is not a
    # margin. The interesting number is where the program stops working.
    print(f"  uart_rx at P={period}, jitter raised until it fails:")
    last_good = None
    for jit in (0.5, 1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 16):
        bad = []
        for k in range(8):
            frac = k / 8.0
            good, _got = run(period, frac * period, float(jit), 1000 + k)
            if not good:
                bad.append(frac)
        pct = 100.0 * jit / period
        state = "all 8 phases decode" if not bad else f"{len(bad)}/8 phases FAIL"
        print(f"    +/-{jit:>4} cycles ({pct:4.1f}% of a bit): {state}")
        if not bad:
            last_good = jit
        else:
            break
    print(f"    margin: correct up to +/-{last_good} cycles of per-edge jitter "
          f"({100.0*last_good/period:.1f}% of a bit time)")
    ok &= (last_good is not None and last_good >= 1)

    print()
    if ok:
        print("OK: uart_rx decodes at every phase and has real jitter margin")
        return 0
    print("FAIL: uart_rx depends on the driver's start alignment")
    return 1


if __name__ == "__main__":
    sys.exit(main())
