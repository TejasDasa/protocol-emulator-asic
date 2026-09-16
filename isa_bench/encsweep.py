"""Evaluate every row encoding: bits, trampolines, and benchmark pass/speed on decoded programs."""
import json
import programs as P
import bench as B
from rowenc import Baseline, OneTarget, Palette, GROUP_BITS

BENCH = ["uart_tx", "uart_rx", "spi", "i2c", "usb"]
orig = {b: P.BUILDERS["STT"][b] for b in BENCH}

key = lambda r: (tuple(sorted(r.pins.items())), tuple(sorted(r.act)))
union = set()
for b in BENCH:
    union |= {key(r) for r in orig[b](32)[1].rows}
global_palette = [((), ())] + sorted(union - {((), ())})

schemes = [Baseline(), OneTarget(False), OneTarget(True),
           Palette(True, False), Palette(True, True),
           Palette(False, False, global_palette)]

results = {}
for sch in schemes:
    results[sch.name] = {}
    for b in BENCH:
        prog = orig[b](32)[1]
        _, pal_bits, bits, dec = sch.encode(prog)

        def build(T, b=b, dec=dec):
            core, _ = orig[b](T)
            core.p, core.row = dec, 0
            return core, dec
        P.BUILDERS["STT"][b] = build
        _, r = B.BENCHES[b]("STT", 32)
        _, speed = B.fastest("STT", b)
        P.BUILDERS["STT"][b] = orig[b]
        tramps = sum(1 for x in dec.rows if x.name.startswith("_T_"))
        results[sch.name][b] = dict(bits=bits, rows=len(dec.rows), tramps=tramps,
                                    palette_bits=pal_bits, ok=r.ok, speed=speed)
        print(f"{sch.name:45} {b:8} bits={bits:4} rows={len(dec.rows):2} "
              f"tramp={tramps} pal={pal_bits:3} {'PASS' if r.ok else 'FAIL ' + r.detail[:60]} "
              f"cyc/bit={speed}")
print("global palette entries (incl. empty):", len(global_palette), " grouped action bits:", GROUP_BITS)
json.dump(results, open("encoding_results.json", "w"), indent=1)
