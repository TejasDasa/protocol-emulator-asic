"""Hybrid palette: 24 entries fixed in silicon + 8 loadable per program (13-bit grouped entries,
counted in program bits). Leave-one-out; anything still missing is split."""
import json
from collections import Counter
import programs as P
from gensweep import run, BENCH, SRC
from rowformat import Format, SINGLES, split_rows

FIXED, LOADABLE, ENTRY_BITS = 24, 8, 13
out = {}
for mode in ["in-sample", "leave-one-out"]:
    tot4 = tot5 = 0
    print(f"\n== {mode}")
    for b in BENCH:
        train = BENCH if mode == "in-sample" else [x for x in BENCH if x != b]
        freq = Counter(tuple(sorted(r.act)) for x in train for r in SRC[x](32)[1].rows
                       if len(r.act) > 1)
        fixed = [()] + sorted(SINGLES) + [s for s, _ in freq.most_common(FIXED - 1 - len(SINGLES))]
        prog0 = SRC[b](32)[1]
        need = Counter(tuple(sorted(r.act)) for r in prog0.rows if tuple(sorted(r.act)) not in fixed)
        loaded = [s for s, _ in need.most_common(LOADABLE)]
        pal = fixed + loaded
        prog, added = split_rows(prog0, pal)
        res = Format("single5", "palette", "silicon", pal).encode(prog)
        bits = res["bits"] + len(loaded) * ENTRY_BITS
        ok, speed = run(res["decoded"], b)
        print(f"  {b:8} rows={res['rows']:2} (+{added} split) loaded={len(loaded)} width={res['row_width']} "
              f"bits={bits:4} {'PASS' if ok else 'FAIL'} cyc/bit={speed}")
        out[f"{mode}/{b}"] = dict(rows=res["rows"], added=added, loaded=len(loaded), bits=bits,
                                  ok=ok, speed=speed)
        tot5 += bits
        if b != "usb":
            tot4 += bits
    print(f"  totals: first four {tot4}, all five {tot5}   (PIO: 864, 1264 with host-side CRC)")
json.dump(out, open("hybrid_results.json", "w"), indent=1)
