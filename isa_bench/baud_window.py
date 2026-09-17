"""How far off the assumed baud can the detector be and still be RIGHT?

DETECTOR_NOTES.md says auto-baud is not applicable and that several machines
each testing a candidate baud is the architectural answer. That answer needs a
number: how far apart the candidates can be.

The trap this measures around: "did it detect" is the wrong question. A
detector configured for period P, shown UART 20% faster, still fires -- it
over-runs the frame, and the stop-bit check then passes trivially against the
idle line. It confirms "UART at P" on traffic it is sampling wrongly. So the
window is measured on whether the byte it pushes is one that was actually sent,
not on whether it fired.

Phase is swept for the same reason: a window measured at one alignment would be
the harness's window, not the program's.
"""
import contextlib
import io
import math
import sys

with contextlib.redirect_stdout(io.StringIO()):
    from world import World
    from devices import UartDriver
    import detector

BYTES = (0x55, 0xC3, 0x00, 0xFF, 0xA5, 0x3C, 0x0F, 0xF0, 0x81, 0x7E, 0x01, 0x80)
FRAMES = [(b, True) for b in BYTES]
PHASES = (0.0, 0.25, 0.5, 0.75)


def trial(P, ratio, phase):
    """(fired, all pushed bytes were really sent)."""
    core, _prog = detector.stt_uart_detect(P)
    w = World([("rx", 1)])
    drv = UartDriver("rx", P * ratio, FRAMES, phase=phase)
    w.devices = [drv]
    w.run(core, drv.end + 8 * P, lambda _w: False)
    got = [v & 0xFF for v in w.rx_fifo]
    return bool(got), bool(got) and all(b in BYTES for b in got)


def main():
    P = 32
    ratios = [round(0.80 + 0.01 * k, 2) for k in range(41)]
    fired, correct = [], []
    for r in ratios:
        res = [trial(P, r, f * P) for f in PHASES]
        if all(a for a, _ in res):
            fired.append(r)
        if all(b for _, b in res):
            correct.append(r)

    print(f"  detector configured for P={P}, real UART at P*r, "
          f"{len(PHASES)} phases each")
    print(f"    fires at every phase for            r in "
          f"[{min(fired):.2f}, {max(fired):.2f}]")
    print(f"    fires AND samples correctly for     r in "
          f"[{min(correct):.2f}, {max(correct):.2f}]")
    lo, hi = min(correct), max(correct)
    print()
    print(f"    The gap between those two is the detector firing on traffic it")
    print(f"    cannot sample: it over-runs the frame and the stop-bit check")
    print(f"    then passes against the idle line. Only the second is a window.")
    print()
    print(f"  capture window: r in [{lo:.2f}, {hi:.2f}] "
          f"= {100*(1/hi - 1):+.0f}% to {100*(1/lo - 1):+.0f}% baud error")
    step = hi / lo
    print(f"  adjacent candidates may be spaced by x{step:.3f}")
    print(f"  {5} machines therefore cover a x{step**4:.2f} baud range; "
          f"a x10 range would need {math.ceil(math.log(10)/math.log(step))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
