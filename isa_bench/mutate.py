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
    from stt import Row, SttProgram, TESTS_V2, ACT_ORDER

TESTS = sorted(TESTS_V2)
PINOPS = ["hold", "lo", "hi", "sr", "tgl", "d0", "d1"]
SLOTS = [0, 1, 2, "pair"]


def _clone(prog):
    return SttProgram([Row(r.name, r.test, r.t, r.f, dict(r.pins), list(r.act))
                       for r in prog.rows])


def mutants(prog):
    """Yield (class, description, mutated_program) -- one corruption each."""
    n = len(prog.rows)
    names = [r.name for r in prog.rows]

    for i, r in enumerate(prog.rows):
        # --- wrong test code
        alt = TESTS[(TESTS.index(r.test) + 1) % len(TESTS)] if r.test in TESTS else "always"
        if alt != r.test:
            m = _clone(prog); m.rows[i].test = alt
            yield "test", f"row {r.name}: test {r.test} -> {alt}", m

        # --- branch target shifted by one row
        if r.t in names:
            j = (names.index(r.t) + 1) % n
            if names[j] != r.t:
                m = _clone(prog); m.rows[i].t = names[j]
                yield "target", f"row {r.name}: target {r.t} -> {names[j]}", m

        # --- branch mode: swap the true and false exits
        if r.t != r.f:
            m = _clone(prog); m.rows[i].t, m.rows[i].f = r.f, r.t
            yield "mode", f"row {r.name}: swap true/false exits", m

        # --- drop one action
        for a in r.act:
            m = _clone(prog); m.rows[i].act = [x for x in r.act if x != a]
            yield "act_drop", f"row {r.name}: drop action {a}", m

        # --- add one spurious action (first one not already present)
        for a in ACT_ORDER:
            if a not in r.act:
                m = _clone(prog); m.rows[i].act = list(r.act) + [a]
                yield "act_add", f"row {r.name}: add action {a}", m
                break

        # --- wrong pin op / wrong slot
        for slot, op in list(r.pins.items()):
            alt_op = PINOPS[(PINOPS.index(op) + 1) % len(PINOPS)] if op in PINOPS else "hold"
            if alt_op != op:
                m = _clone(prog); m.rows[i].pins = dict(r.pins); m.rows[i].pins[slot] = alt_op
                yield "pinop", f"row {r.name}: pin {slot} op {op} -> {alt_op}", m
            alt_slot = SLOTS[(SLOTS.index(slot) + 1) % len(SLOTS)] if slot in SLOTS else 0
            if alt_slot != slot:
                m = _clone(prog); p = dict(r.pins); p.pop(slot); p[alt_slot] = op
                m.rows[i].pins = p
                yield "pinslot", f"row {r.name}: pin op {op} slot {slot} -> {alt_slot}", m

    # --- swap adjacent rows
    for i in range(n - 1):
        m = _clone(prog)
        m.rows[i], m.rows[i + 1] = m.rows[i + 1], m.rows[i]
        m = SttProgram(m.rows)
        yield "swap", f"swap rows {names[i]} / {names[i+1]}", m


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
