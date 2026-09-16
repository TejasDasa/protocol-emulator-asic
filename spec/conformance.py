#!/usr/bin/env python3
"""Check spec/isa.json field-by-field against the authoritative models.

docs/SPEC.md is generated from spec/isa.json, so the document cannot disagree
with that file. This closes the other half: it verifies spec/isa.json cannot
disagree with isa_bench/, which is where the benchmarks actually run.

Authority, per docs/SPEC.md section 0: the Python models win. This script never
"fixes" a mismatch, it reports one, because a mismatch means either the spec is
wrong or the encoding changed and the spec was not updated -- and those need a
human to tell apart.

Exit 0 if every check passes, 1 otherwise.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "isa_bench"))


def main():
    spec = json.load(open(os.path.join(HERE, "isa.json")))

    from rowenc import TESTS, GROUPS, GROUP_BITS, bits_for
    from rowformat import PINOPS, SLOTS
    from stt import ACT_ORDER, MAX_ROWS

    fails = []

    def check(cond, msg):
        if not cond:
            fails.append(msg)

    # ---- test codes -----------------------------------------------------
    spec_tests = {t["code"]: t["name"] for t in spec["tests"]}
    check(len(spec_tests) == len(TESTS),
          f"test count: spec {len(spec_tests)} vs models {len(TESTS)}")
    for i, name in enumerate(TESTS):
        check(spec_tests.get(i) == name,
              f"test code {i}: spec {spec_tests.get(i)!r} vs models {name!r}")

    # ---- pin ops and slots ----------------------------------------------
    spec_ops = {p["code"]: p["name"] for p in spec["pin_ops"]}
    check(len(spec_ops) == len(PINOPS),
          f"pin_op count: spec {len(spec_ops)} vs models {len(PINOPS)}")
    for i, name in enumerate(PINOPS):
        check(spec_ops.get(i) == name,
              f"pin_op {i}: spec {spec_ops.get(i)!r} vs models {name!r}")

    spec_slots = {s["code"]: s["name"] for s in spec["pin_slots"]}
    for i, s in enumerate(SLOTS):
        want = "pair" if s == "pair" else f"slot{s}"
        check(spec_slots.get(i) == want,
              f"pin_slot {i}: spec {spec_slots.get(i)!r} vs models {want!r}")

    # ---- action groups: names, widths, offsets, and every choice ---------
    spec_groups = {g["name"]: g for g in spec["action_groups"]}
    check(len(spec_groups) == len(GROUPS),
          f"group count: spec {len(spec_groups)} vs models {len(GROUPS)}")
    off = 0
    for name, choices in GROUPS:
        g = spec_groups.get(name)
        if g is None:
            fails.append(f"group {name}: missing from spec")
            off += bits_for(len(choices))
            continue
        w = bits_for(len(choices))
        check(g["width"] == w, f"group {name} width: spec {g['width']} vs models {w}")
        check(g["lsb"] == off, f"group {name} lsb: spec {g['lsb']} vs models {off}")
        check(len(g["choices"]) == len(choices),
              f"group {name} choice count: spec {len(g['choices'])} vs models {len(choices)}")
        spec_ch = {c["code"]: tuple(c["actions"]) for c in g["choices"]}
        for code, acts in enumerate(choices):
            check(spec_ch.get(code) == tuple(acts),
                  f"group {name} code {code}: spec {spec_ch.get(code)} vs models {tuple(acts)}")
        off += w

    # ---- row field layout ------------------------------------------------
    # Rebuild the field list the way rowformat.Format does for the frozen row
    # (single5 pins, grouped actions, 8-bit target) and compare offsets.
    expect = [("test", 4), ("mode", 2), ("target", 8), ("pin_slot", 2), ("pin_op", 3)]
    for name, choices in GROUPS:
        expect.append((f"act_{name}", bits_for(len(choices))))
    spec_fields = {f["name"]: f for f in spec["fields"]}
    o = 0
    for name, w in expect:
        f = spec_fields.get(name)
        if f is None:
            fails.append(f"field {name}: missing from spec")
            o += w
            continue
        check(f["width"] == w, f"field {name} width: spec {f['width']} vs models {w}")
        check(f["lsb"] == o, f"field {name} lsb: spec {f['lsb']} vs models {o}")
        o += w
    check(spec["row_width"] == o, f"row_width: spec {spec['row_width']} vs models {o}")
    check(o == 32, f"frozen row must be 32 bits, computed {o}")
    check(GROUP_BITS == 13, f"GROUP_BITS: models {GROUP_BITS}, spec assumes 13")

    # ---- misc ------------------------------------------------------------
    check(spec["max_rows"] == MAX_ROWS,
          f"max_rows: spec {spec['max_rows']} vs models {MAX_ROWS}")
    tgt_w = spec_fields["target"]["width"]
    check(spec["ret_code"] == (1 << tgt_w) - 1,
          f"ret_code: spec {spec['ret_code']} vs all-ones for a {tgt_w}-bit target")
    check(spec["action_order"] == list(ACT_ORDER),
          "action_order differs from stt.ACT_ORDER")

    # every action named in a group must exist in ACT_ORDER, and vice versa
    in_groups = {a for g in spec["action_groups"] for c in g["choices"] for a in c["actions"]}
    check(in_groups == set(ACT_ORDER),
          f"actions in groups vs ACT_ORDER: only-in-groups={sorted(in_groups-set(ACT_ORDER))}, "
          f"only-in-ACT_ORDER={sorted(set(ACT_ORDER)-in_groups)}")

    # ---- report ----------------------------------------------------------
    if fails:
        print(f"FAIL: {len(fails)} conformance error(s) between spec/isa.json and isa_bench/")
        for f in fails:
            print(f"  {f}")
        print("\nThe Python models are authoritative. Either spec/isa.json is wrong,")
        print("or the encoding changed and the spec was not updated. Do not guess which.")
        return 1

    n = (len(spec["tests"]) + len(spec["pin_ops"]) + len(spec["pin_slots"])
         + sum(len(g["choices"]) for g in spec["action_groups"]) + len(spec["fields"]))
    print(f"OK: spec/isa.json matches isa_bench/ on all {n} encoding entries "
          f"({spec['row_width']}-bit row, {len(spec['tests'])} tests, "
          f"{len(spec['action_groups'])} action groups).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
