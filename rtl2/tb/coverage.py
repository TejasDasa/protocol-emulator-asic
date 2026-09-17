"""Which of the encoding does the reference set actually exercise?

The six programs pass in cycle-exact lockstep, but they were written to drive
six protocols, not to cover the ISA. Any decode path they never take is a path
whose RTL has never been compared against anything. This counts them.

Two different questions, and the second is the one that matters:

  ENCODED   which field values appear in the 84 rows of the six programs.
  EXECUTED  which field values are actually reached at run time. A row that is
            encoded but never executed, or a pin op on a row whose test never
            passes, proves nothing.

Run from rtl2/:  python3 tb/coverage.py
"""
import io
import contextlib
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "isa_bench"))
sys.path.insert(0, HERE)

from lockstep import capture_benchmark, encode_rows

SPEC = json.load(open(os.path.join(ROOT, "spec", "isa.json")))
PROGRAMS = ["uart_tx", "uart_rx", "spi", "i2c", "usb", "jtag"]
PERIOD = 32

FIELDS = {f["name"]: (f["lsb"], f["width"]) for f in SPEC["fields"]}


def names_for(field):
    """code -> human name, for whichever table describes this field."""
    if field == "test":
        return {t["code"]: t["name"] for t in SPEC["tests"]}
    if field == "mode":
        return {m["code"]: m["name"] for m in SPEC["branch_modes"]}
    if field == "pin_slot":
        return {s["code"]: s["name"] for s in SPEC["pin_slots"]}
    if field == "pin_op":
        return {p["code"]: p["name"] for p in SPEC["pin_ops"]}
    if field.startswith("act_"):
        g = next(g for g in SPEC["action_groups"] if g["name"] == field[4:])
        return {c["code"]: ("-" if not c["actions"] else "+".join(c["actions"]))
                for c in g["choices"]}
    return {}


def main():
    encoded = defaultdict(set)
    executed = defaultdict(set)
    rows_total = rows_executed = 0
    row_exec = defaultdict(set)     # program -> set of row indices reached

    for name in PROGRAMS:
        stash = capture_benchmark(name, PERIOD)
        core, w, done, max_cycles = (stash["core"], stash["world"],
                                     stash["done"], stash["max_cycles"])
        words, decoded = encode_rows(core.p)
        core.p, core.row = decoded, 0
        rows_total += len(words)

        for word in words:
            for f, (lsb, wd) in FIELDS.items():
                encoded[f].add((word >> lsb) & ((1 << wd) - 1))

        # Execute it and record which rows, and which field values, are reached.
        w.resolve()
        for t in range(max_cycles):
            w.t = t
            for d in w.devices:
                d.step(w)
            w.resolve()
            idx = core.row
            row_exec[name].add(idx)
            word = words[idx]
            for f, (lsb, wd) in FIELDS.items():
                executed[f].add((word >> lsb) & ((1 << wd) - 1))
            core.step(w)
            w.resolve()
            for nname, n in w.nets.items():
                w.history[nname].append(n.value)
            if done(w):
                break
        rows_executed += len(row_exec[name])

    print(f"{'field':10} {'cap':>4} {'encoded':>8} {'executed':>9}   never executed")
    total_cap = total_exec = 0
    gaps = {}
    for f, (lsb, wd) in FIELDS.items():
        if f == "target":
            continue                       # 8 bits of row index, not a code space
        nm = names_for(f)
        cap = len(nm) if nm else (1 << wd)
        total_cap += cap
        total_exec += len(executed[f] & set(nm)) if nm else len(executed[f])
        missing = sorted(set(nm) - executed[f])
        gaps[f] = missing
        show = ", ".join(f"{c}:{nm[c]}" for c in missing) or "-"
        print(f"{f:10} {cap:>4} {len(encoded[f]):>8} {len(executed[f]):>9}   {show}")

    print(f"\nrows: {rows_executed} of {rows_total} encoded rows are reached at run time")
    print(f"code coverage: {total_exec}/{total_cap} = "
          f"{100.0*total_exec/total_cap:.1f}% of defined field values executed")
    print(f"unexercised codes: {sum(len(v) for v in gaps.values())}")
    json.dump({k: v for k, v in gaps.items()},
              open(os.path.join(HERE, "coverage_gaps.json"), "w"), indent=1)
    print("wrote tb/coverage_gaps.json")


if __name__ == "__main__":
    main()
