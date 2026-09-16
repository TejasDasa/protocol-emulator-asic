"""Part B: 21-bit rows vs a 32-bit row, re-encoding all five benchmarks.

The 32-bit row spends its 11 extra bits as:

    test 4 | mode 2 | target 8 | slot 2 | pinop 3 | grouped actions 13 = 32

Two changes from the 21-bit row, and the second is the one that matters:

  * target 5 -> 8 bits. Not because 5 was binding (worst benchmark is 22 rows
    of 31 reachable) but because the bits are free and it retires ambiguity A4,
    where RET=31 made row 31 unreachable by branch.
  * the 5-bit palette INDEX becomes the 13-bit grouped action code INLINE.
    That removes the palette entirely: no 24-entry fixed ROM, no 8 loadable
    entries, and no palette-miss row splitting, at the cost of 8 bits of row.

Run:  python3 widthsweep.py       -> prints the tables and writes width_results.json
"""
import io
import json
import contextlib

_buf = io.StringIO()
with contextlib.redirect_stdout(_buf):        # gensweep sweeps on import
    from collections import Counter
    from gensweep import run, BENCH, SRC
    from rowformat import Format, SINGLES, split_rows

FIXED, LOADABLE, ENTRY_BITS = 24, 8, 13


def palette_for(bench, mode):
    train = BENCH if mode == "in-sample" else [b for b in BENCH if b != bench]
    freq = Counter(tuple(sorted(r.act)) for b in train for r in SRC[b](32)[1].rows
                   if len(r.act) > 1)
    fixed = [()] + sorted(SINGLES) + [s for s, _ in
                                      freq.most_common(FIXED - 1 - len(SINGLES))]
    prog0 = SRC[bench](32)[1]
    need = Counter(tuple(sorted(r.act)) for r in prog0.rows
                   if tuple(sorted(r.act)) not in fixed)
    loaded = [s for s, _ in need.most_common(LOADABLE)]
    return fixed + loaded, loaded, prog0


def encode21(bench, mode):
    pal, loaded, prog0 = palette_for(bench, mode)
    prog, added = split_rows(prog0, pal)
    res = Format("single5", "palette", "silicon", pal).encode(prog)
    ok, speed = run(res["decoded"], bench)
    return dict(rows=res["rows"], split=added, loaded=len(loaded),
                width=res["row_width"],
                bits=res["bits"] + len(loaded) * ENTRY_BITS,
                ok=ok, speed=speed)


def encode32(bench):
    """Inline grouped actions, 8-bit target. No palette, so no split, no
    leave-one-out distinction: the format cannot miss."""
    prog = SRC[bench](32)[1]
    res = Format("single5", "grouped", tgt_bits=8).encode(prog)
    ok, speed = run(res["decoded"], bench)
    return dict(rows=res["rows"], split=0, loaded=0, width=res["row_width"],
                bits=res["bits"], ok=ok, speed=speed)


def main():
    out = {}
    print("=== 21-bit row: test 4 | mode 2 | target 5 | slot 2 | pinop 3 | palette idx 5")
    for mode in ("in-sample", "leave-one-out"):
        print(f"\n-- {mode}")
        print(f"  {'bench':9} {'rows':>5} {'split':>6} {'load/8':>7} {'bits':>6} {'pass':>5} {'cyc/bit':>9}")
        tot = 0
        for b in BENCH:
            r = encode21(b, mode)
            out[f"21/{mode}/{b}"] = r
            tot += r["bits"]
            print(f"  {b:9} {r['rows']:5} {r['split']:6} {r['loaded']:7} {r['bits']:6} "
                  f"{'PASS' if r['ok'] else 'FAIL':>5} {r['speed']:>9}")
        print(f"  total bits: {tot}")
        out[f"21/{mode}/total"] = tot

    print("\n=== 32-bit row: test 4 | mode 2 | target 8 | slot 2 | pinop 3 | grouped 13")
    print("    (no palette -- in-sample and leave-one-out are identical by construction)")
    print(f"\n  {'bench':9} {'rows':>5} {'split':>6} {'load/8':>7} {'bits':>6} {'pass':>5} {'cyc/bit':>9}")
    tot = 0
    for b in BENCH:
        r = encode32(b)
        out[f"32/{b}"] = r
        tot += r["bits"]
        print(f"  {b:9} {r['rows']:5} {r['split']:6} {r['loaded']:7} {r['bits']:6} "
              f"{'PASS' if r['ok'] else 'FAIL':>5} {r['speed']:>9}")
    print(f"  total bits: {tot}")
    out["32/total"] = tot

    worst21 = max(out[f"21/{m}/{b}"]["rows"] for m in ("in-sample", "leave-one-out")
                  for b in BENCH)
    worst32 = max(out[f"32/{b}"]["rows"] for b in BENCH)
    worstload = max(out[f"21/{m}/{b}"]["loaded"] for m in ("in-sample", "leave-one-out")
                    for b in BENCH)
    print(f"\nworst rows: 21-bit {worst21}, 32-bit {worst32}  "
          f"(32 rows = 2 CFGMEM tiles, 64 = 4)")
    print(f"worst loadable-palette usage at 21 bits: {worstload} of {LOADABLE}")
    print(f"32 rows sufficient: {'YES' if max(worst21, worst32) <= 32 else 'NO'}")
    out["summary"] = dict(worst_rows_21=worst21, worst_rows_32=worst32,
                          worst_loaded_21=worstload,
                          fits_32_rows=bool(max(worst21, worst32) <= 32))
    json.dump(out, open("width_results.json", "w"), indent=1)
    print("\nwrote width_results.json")


if __name__ == "__main__":
    main()
