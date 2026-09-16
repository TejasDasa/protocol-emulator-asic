"""Generalization test: fixed 32-entry palette (21-bit rows), with row splitting as fallback."""
import json
import programs as P
import bench as B
from rowformat import Format, principled_palette, split_rows

BENCH = ["uart_tx", "uart_rx", "spi", "i2c", "usb"]
SRC = P.STT_1PIN
ORIG = {b: P.BUILDERS["STT"][b] for b in BENCH}


def run(prog_b, b):
    def build(T):
        core, _ = SRC[b](T)
        core.p, core.row = prog_b, 0
        return core, prog_b
    P.BUILDERS["STT"][b] = build
    _, r = B.BENCHES[b]("STT", 32)
    speed = B.fastest("STT", b)[1]
    P.BUILDERS["STT"][b] = ORIG[b]
    return r.ok, speed


out = {}
for mode in ["in-sample", "leave-one-out"]:
    print(f"\n== {mode}")
    tot4 = tot5 = 0
    for b in BENCH:
        train = BENCH if mode == "in-sample" else [x for x in BENCH if x != b]
        rows = [r for x in train for r in SRC[x](32)[1].rows]
        pal = principled_palette(rows, 32)
        prog, added = split_rows(SRC[b](32)[1], pal)
        res = Format("single5", "palette", "silicon", pal).encode(prog)
        ok, speed = run(res["decoded"], b)
        base_ok, base_speed = run(SRC[b](32)[1], b)
        print(f"  {b:8} rows={res['rows']:2} (+{added} split) width={res['row_width']} "
              f"bits={res['bits']:4} {'PASS' if ok else 'FAIL'} cyc/bit={speed} (unsplit {base_speed})")
        out[f"{mode}/{b}"] = dict(rows=res["rows"], added=added, bits=res["bits"], ok=ok,
                                  speed=speed, base_speed=base_speed)
        tot5 += res["bits"]
        if b != "usb":
            tot4 += res["bits"]
    print(f"  totals: first four {tot4}, all five {tot5}   (PIO: 864, 1264 with host-side CRC)")
json.dump(out, open("generalization_results.json", "w"), indent=1)
