#!/usr/bin/env python3
"""Dump the STT 21-bit row encoding and the 24+8 action palette from isa_bench/.

Run from isa_bench/:   cd isa_bench && python3 ../scripts/dump_isa.py
Everything printed here is read out of the Python models, not restated by hand.
Importing gensweep re-runs the generalization sweep first; that output is the
model's, and is left visible on purpose.
"""
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, os.pardir, "isa_bench"))

from rowenc import TESTS, GROUPS, GROUP_BITS, bits_for, RET          # noqa: E402
from rowformat import PINOPS, SLOTS, SINGLES                          # noqa: E402
from gensweep import BENCH, SRC                                       # noqa: E402

FIXED, LOADABLE, ENTRY_BITS = 24, 8, 13

print("\n" + "=" * 70)
print("ROW FIELDS (rowformat.Format.encode, pins='single5', acts='palette')")
print("=" * 70)
lo = 0
for name, w in [("test", 4), ("branch mode", 2), ("target", 5),
                ("pin slot", 2), ("pin op", 3), ("action-set index", 5)]:
    print(f"  [{lo+w-1:2}:{lo:2}]  {w}  {name}")
    lo += w
print(f"  row width = {lo} bits")

print("\nTEST CODES (sorted(TESTS_V2)):")
for i, t in enumerate(TESTS):
    print(f"  {i:2}  {t}")
print(f"  {len(TESTS)}..15  unassigned")

print("\nPIN SLOT CODES:", {i: s for i, s in enumerate(SLOTS)})
print("PIN OP CODES:  ", {i: p for i, p in enumerate(PINOPS)})
print(f"RET target code = {RET}")

print(f"\nPALETTE ENTRY = {GROUP_BITS} bits (rowenc.GROUP_BITS)")
for name, choices in GROUPS:
    print(f"  group {name}: {bits_for(len(choices))} bits, {len(choices)} choices: {list(choices)}")
assert GROUP_BITS == ENTRY_BITS
print(f"  loadable palette flops = {LOADABLE} x {ENTRY_BITS} = {LOADABLE * ENTRY_BITS}")

print("\n" + "=" * 70)
print("FIXED PALETTE (hybridsweep.py recipe), in-sample = train on all five")
print("=" * 70)
freq = Counter(tuple(sorted(r.act)) for b in BENCH for r in SRC[b](32)[1].rows
               if len(r.act) > 1)
fixed = [()] + sorted(SINGLES) + [s for s, _ in freq.most_common(FIXED - 1 - len(SINGLES))]
for i, e in enumerate(fixed):
    kind = "empty" if i == 0 else ("single" if i <= 17 else "multi")
    print(f"  {i:2}  {kind:6}  {', '.join(e) if e else '-'}")
print(f"  {len(fixed)} fixed entries; {LOADABLE} loadable -> {len(fixed) + LOADABLE} total")

print("\nPer-benchmark loadable entries needed with that fixed set:")
for b in BENCH:
    prog = SRC[b](32)[1]
    need = Counter(tuple(sorted(r.act)) for r in prog.rows
                   if tuple(sorted(r.act)) not in fixed)
    loaded = [s for s, _ in need.most_common(LOADABLE)]
    print(f"  {b:8} rows={len(prog.rows):2} loaded={len(loaded)} {loaded}")

print("\nStability of the first 18 entries across all leave-one-out runs:")
base = fixed[:18]
ok = True
for b in BENCH:
    train = [x for x in BENCH if x != b]
    f2 = Counter(tuple(sorted(r.act)) for x in train for r in SRC[x](32)[1].rows
                 if len(r.act) > 1)
    loo = [()] + sorted(SINGLES) + [s for s, _ in f2.most_common(FIXED - 1 - len(SINGLES))]
    same = loo[:18] == base
    ok &= same
    print(f"  hold out {b:8} first18_same={same}  tail={loo[18:]}")
print(f"  ALL FIRST-18 IDENTICAL: {ok}")
