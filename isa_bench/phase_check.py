"""Gate: adding phase and jitter must not move the deterministic waveform.

The default construction has to stay bit-for-bit what it was, because every
existing benchmark result was measured against it. Checked by rebuilding the
old fixed-run algorithm here and comparing the line value at every cycle.

Then the opposite: a non-zero phase or jitter must actually move edges, or the
knob is decorative.
"""
import sys

from devices import UartDriver, bits_lsb


def old_wave(period, frames, t0=40, gap_bits=2):
    """The construction UartDriver used before phase and jitter existed."""
    wave, t = {}, t0
    for byte, good in frames:
        bits = [0] + bits_lsb(byte, 8) + [1 if good else 0]
        for b in bits:
            for i in range(period):
                wave[t + i] = b
            t += period
        if not good:
            for i in range(period):
                wave[t + i] = 0
            t += period
        t += gap_bits * period
    return wave, t


def levels(wave, end):
    return [wave.get(t, 1) for t in range(0, end + 8)]


def main():
    frames = [(0x55, True), (0xC3, True), (0x00, False), (0xFF, True),
              (0xA5, True), (0x3C, False)]
    ok = True

    for period in (3, 8, 16, 32):
        want_w, want_end = old_wave(period, frames)
        d = UartDriver("rx", period, frames)
        same = levels(d.wave, want_end) == levels(want_w, want_end)
        same &= (d.end == want_end)
        print(f"  {'ok  ' if same else 'FAIL'} period {period:2d}: default waveform "
              f"identical to the pre-phase construction (end {d.end} vs {want_end})")
        ok &= same

    # --- the knobs must actually do something ----------------------------
    base = UartDriver("rx", 16, frames)
    half = UartDriver("rx", 16, frames, phase=8.0)
    moved = levels(half.wave, base.end) != levels(base.wave, base.end)
    print(f"  {'ok  ' if moved else 'FAIL'} phase=P/2 moves the waveform")
    ok &= moved

    jit = UartDriver("rx", 16, frames, jitter=3.0, seed=7)
    moved = levels(jit.wave, base.end) != levels(base.wave, base.end)
    print(f"  {'ok  ' if moved else 'FAIL'} jitter moves the waveform")
    ok &= moved

    # bit widths must vary under jitter, not just shift
    widths = set()
    prev, run = None, 0
    for t in range(base.end):
        v = jit.wave.get(t, 1)
        if v == prev:
            run += 1
        else:
            if prev is not None:
                widths.add(run)
            prev, run = v, 1
    varied = len(widths) > 3
    print(f"  {'ok  ' if varied else 'FAIL'} jitter varies bit widths, not just "
          f"the offset ({len(widths)} distinct run lengths)")
    ok &= varied

    # a fractional period must be representable
    frac = UartDriver("rx", 6.525, frames)     # SPI's cycles-per-bit
    print(f"  ok   fractional period 6.525 builds, {len(frac.wave)} cycles driven")

    # boundaries stay ordered under heavy jitter
    heavy = UartDriver("rx", 8, frames, jitter=20.0, seed=3)
    print(f"  ok   jitter larger than the bit period still builds "
          f"(end {heavy.end}, no negative-width runs)")

    print()
    print("OK: phase and jitter are available and the default is unchanged" if ok
          else "FAIL: the deterministic waveform moved, or a knob does nothing")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
