"""Mutation suite: prove the benchmarks actually CATCH a corrupted program.

Why this exists
---------------
`isa_bench/README.md` claims, of the row-encoding study, that "a deliberately
corrupted decode is caught". That claim was never implemented: nothing in the
repository ever corrupted anything. The property is plausible -- every sweep
re-runs the DECODED program through the device models, so a bad decode should
show up -- but "should" is not evidence, and every "PASS" in this study rests
on the benchmarks being able to fail.

This module makes that claim testable. For each benchmark it takes the working
program, applies one deliberate single-point corruption, re-runs it against the
real device models, and asserts the run FAILS. A mutation that still passes is
a SURVIVOR: either that behaviour is not exercised by the test vectors, or the
benchmark cannot see the difference. Survivors are reported, not hidden -- they
are the honest measure of how much a PASS is worth.

Mutation classes (single point, one per mutant):
    test        wrong test code on a row
    mode        wrong branch mode
    target      branch target shifted by one row
    act_drop    one action removed
    act_add     one spurious action added
    pinop       wrong pin operation
    pinslot     pin driven on the wrong slot
    swap        two adjacent rows exchanged  [order probe, see below]

Equivalent mutants
-----------------
`swap` is reported separately and NOT counted in the headline kill rate.
Branch targets resolve by NAME, so exchanging two adjacent rows only changes
behaviour for rows that fall through to `next`. Most rows carry explicit
targets, so most swap mutants are semantically identical programs -- classic
equivalent mutants, which a kill rate must not be penalised for. They are kept
because the ones that DO die tell you which rows depend on physical order.

Run:  python3 mutate.py            all benchmarks, summary + survivors
      python3 mutate.py --json     also write mutation_results.json
"""
import argparse
import copy
import io
import json
import contextlib

_buf = io.StringIO()
with contextlib.redirect_stdout(_buf):          # gensweep sweeps on import
    from gensweep import run, BENCH, SRC

from mutlib import PINOPS, SLOTS, TESTS, mutants  # noqa: F401


def survives(prog, bench):
    """True if the (mutated) program still passes the benchmark."""
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            ok, _ = run(prog, bench)
        return bool(ok)
    except Exception:
        return False        # a crash is a catch, not a survival


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--bench", default=None)
    ap.add_argument("--gate", action="store_true",
                    help="exit non-zero if the score regresses (validity gate)")
    ap.add_argument("--min-score", type=float, default=85.0,
                    help="floor for the semantic kill rate, percent")
    ap.add_argument("--min-mutants", type=int, default=340,
                    help="floor for the semantic mutant COUNT: catches a "
                         "benchmark being dropped, which would raise the "
                         "percentage while testing less")
    args = ap.parse_args()

    benches = [args.bench] if args.bench else BENCH
    out, grand_k, grand_n = {}, 0, 0
    grand_sk = grand_sn = 0
    all_survivors = []

    print("=== mutation suite: every mutant should FAIL the benchmark ===\n")
    for b in benches:
        base = SRC[b](32)[1]
        if not survives(base, b):
            print(f"{b}: BASELINE DOES NOT PASS -- mutation results meaningless")
            continue
        per = {}
        surv = []
        for cls, desc, m in mutants(base):
            per.setdefault(cls, [0, 0])
            per[cls][1] += 1
            if survives(m, b):
                surv.append((cls, desc))
            else:
                per[cls][0] += 1
        k = sum(v[0] for c, v in per.items() if c != "swap")
        n = sum(v[1] for c, v in per.items() if c != "swap")
        sk, sn = per.get("swap", [0, 0])
        grand_k += k; grand_n += n
        grand_sk += sk; grand_sn += sn
        all_survivors += [(b, c, d) for c, d in surv]
        pct = 100.0 * k / n if n else 0.0
        print(f"{b:9} killed {k:4}/{n:<4} ({pct:5.1f}%) semantic   "
              + "  ".join(f"{c}:{v[0]}/{v[1]}" for c, v in sorted(per.items())
                          if c != "swap")
              + (f"   [order swap:{sk}/{sn}]" if sn else ""))
        out[b] = dict(killed=k, total=n, pct=pct,
                      by_class={c: dict(killed=v[0], total=v[1]) for c, v in per.items()},
                      survivors=[f"{c}: {d}" for c, d in surv])

    pct = 100.0 * grand_k / grand_n if grand_n else 0.0
    spct = 100.0 * grand_sk / grand_sn if grand_sn else 0.0
    print(f"\nTOTAL semantic: killed {grand_k}/{grand_n} ({pct:.1f}%)")
    print(f"TOTAL order swap: killed {grand_sk}/{grand_sn} ({spct:.1f}%) "
          f"-- mostly equivalent mutants, excluded from the headline")

    if all_survivors:
        print(f"\n=== {len(all_survivors)} SURVIVORS (mutation not detected) ===")
        for b, c, d in all_survivors:
            print(f"  {b:9} [{c}] {d}")
        print("\nA survivor means the test vectors do not exercise that behaviour.")
    else:
        print("\nNo survivors: every single-point corruption is caught.")

    out["_total"] = dict(killed=grand_k, total=grand_n, pct=pct,
                         survivors=len(all_survivors))

    if args.gate:
        bad = []
        if pct < args.min_score:
            bad.append(f"semantic kill rate {pct:.1f}% < floor {args.min_score}%")
        if grand_n < args.min_mutants:
            bad.append(f"only {grand_n} semantic mutants < floor {args.min_mutants} "
                       f"(a benchmark may have been dropped)")
        if bad:
            print("\nFAIL (validity gate):")
            for m in bad:
                print("  " + m)
            print("A falling mutation score means the benchmarks got weaker, "
                  "which is exactly how the SPI/I2C timing gap went unnoticed.")
            return 1
        print(f"\nOK: mutation gate passed "
              f"({pct:.1f}% >= {args.min_score}%, {grand_n} >= {args.min_mutants} mutants)")
    if args.json:
        json.dump(out, open("mutation_results.json", "w"), indent=1)
        print("\nwrote mutation_results.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
