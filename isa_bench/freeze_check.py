"""The freeze, as a gate: the reference programs must encode to the same words.

This replaces the amendment-simulation that sharedunits.py performed. That check
asked "would appending the reserved codes change anything?" and was useful while
they were hypothetical. Now they are implemented, so the question is the
permanent one: has ANY change re-encoded a reference program?

Golden words are committed. Regenerating them is a deliberate act -- run with
--bless and explain in the commit why the frozen encoding moved.

Verified at the time of writing by extracting HEAD's encoder with `git archive`
and running both: all six programs byte-identical after the wider units of SPEC
section 9 were implemented.
"""
import contextlib
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN = os.path.join(HERE, "golden_words.json")


def encode_all():
    with contextlib.redirect_stdout(io.StringIO()):
        import programs as P
        import jtag_prog
        from rowformat import Format
    src = dict(P.STT_1PIN)
    src["jtag"] = jtag_prog.stt_jtag
    out = {}
    for n, b in src.items():
        _core, prog = b(32)
        r = Format("single5", "grouped", tgt_bits=8).encode(prog)
        assert r["row_width"] == 32, f"{n} encoded at {r['row_width']} bits"
        out[n] = list(r["packed"])
    return out


def main():
    now = encode_all()
    if "--bless" in sys.argv:
        json.dump(now, open(GOLDEN, "w"), indent=1)
        print(f"blessed {len(now)} programs, "
              f"{sum(len(v) for v in now.values())} rows")
        return 0
    if not os.path.exists(GOLDEN):
        print(f"FAIL: {GOLDEN} missing. Create it with --bless.")
        return 1
    want = json.load(open(GOLDEN))
    bad = []
    for n in sorted(set(want) | set(now)):
        if want.get(n) != now.get(n):
            bad.append(n)
            a, b = want.get(n, []), now.get(n, [])
            if len(a) != len(b):
                print(f"  {n}: {len(a)} rows -> {len(b)} rows")
            for i, (x, y) in enumerate(zip(a, b)):
                if x != y:
                    print(f"  {n} row {i}: 0x{x:08x} -> 0x{y:08x}")
    if bad:
        print(f"FAIL: the frozen encoding moved for {', '.join(bad)}.\n"
              f"If that was intended, re-bless and say why in the commit.")
        return 1
    print(f"OK: frozen encoding intact -- {len(now)} programs, "
          f"{sum(len(v) for v in now.values())} rows, every word unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
